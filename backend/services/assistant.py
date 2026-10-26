"""Gemini fantasy assistant grounded in CourtVision's own tools.

Gemini receives function declarations for the app's analytics (player reports, comparisons, rankings,
team analysis, trades, matchup simulation, streaming, breakouts, schedule). It decides which tools to
call; the backend executes them against real data and returns JSON results; Gemini then answers using
only those results. Every number in the final answer is checked against the tool outputs.

Without a Gemini key (or on API failure) a deterministic rule-based assistant routes the question to
the same tools by keyword and writes a templated answer, clearly labelled as a fallback.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from core.categories import CATEGORIES
from services import breakouts, comparison, matchup, rankings, rosters, streaming, team, trade
from services import players as player_svc
from services.gemini_service import _describe_error, gemini, genai_types, grounding_check
from services.projections import Projection, player_row
from services.schedule import schedule_summary

log = logging.getLogger("courtvision.assistant")
MAX_STEPS = 5
CAT_LABEL = {c.key: c.label for c in CATEGORIES}
# word stems that signal each category in free text (matched at the start of a word)
CAT_WORDS = {
    "pts": ["point", "scor", "pts"], "reb": ["rebound", "board", "reb"],
    "ast": ["assist", "ast", "playmak", "passer"], "stl": ["steal", "stl"],
    "blk": ["block", "blk", "rim protect"], "fg3m": ["three", "3pm", "3s", "3-point", "3 point"],
    "fg_pct": ["fg%", "field goal", "fg pct"], "ft_pct": ["ft%", "free throw", "ft pct"], "tov": ["turnover", "tov"],
}


@dataclass
class Ctx:
    proj: Projection
    roster_id: int | None = None
    opponent_id: int | None = None
    trace: list[dict] = field(default_factory=list)

    @property
    def roster(self) -> list[int]:
        r = rosters.get_roster(self.roster_id) if self.roster_id else None
        return r["player_ids"] if r else []

    @property
    def opponent(self) -> list[int]:
        r = rosters.get_roster(self.opponent_id) if self.opponent_id else None
        return r["player_ids"] if r else []


class ToolError(ValueError):
    pass


# ----------------------------------------------------------------------------- tool implementations
def _resolve(ctx: Ctx, name: str) -> int:
    hits = player_svc.search(name, limit=1, ranking=ctx.proj.players)
    if not hits:
        raise ToolError(f"No player found matching '{name}'")
    return hits[0]["id"]


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def _week_line(row: dict | None) -> dict | None:
    if not row:
        return None
    return {"games": row.get("games"), "status": row.get("status"), "rank": row.get("rank"),
            "weekly_9cat_value": _r(row.get("value")), "value_80pct_range": [_r(row.get("value_lo")), _r(row.get("value_hi"))],
            "weekly": {CAT_LABEL[c.key]: _r(row.get(c.key), 3 if c.is_pct else 1) for c in CATEGORIES},
            "per_game_z": {CAT_LABEL[c.key]: _r(row.get(f"pg_z_{c.key}")) for c in CATEGORIES},
            "per_game_value": _r(row.get("pg_value"))}


def t_find_player(ctx: Ctx, name: str) -> dict:
    return {"matches": player_svc.search(name, limit=5, ranking=ctx.proj.players)}


def t_player_report(ctx: Ctx, name: str) -> dict:
    pid = _resolve(ctx, name)
    prof = player_svc.player_profile(pid)
    keys = ["games", "min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fg_pct", "ft_pct"]
    brief = lambda s: {k: _r(s.get(k), 3 if k.endswith("pct") else 1) for k in keys} if s else None  # noqa: E731
    return {"name": prof["name"], "team": prof["team_abbr"], "position": prof["position"],
            "injury": prof["injury"], "season_averages": {k: brief(v) for k, v in prof["seasons"].items()},
            "last5": brief(prof["last5"]), "last10": brief(prof["last10"]),
            "projection_" + ctx.proj.window.key: _week_line(player_row(ctx.proj, pid))}


def t_compare_players(ctx: Ctx, player_a: str, player_b: str) -> dict:
    comp = comparison.build(ctx.proj, _resolve(ctx, player_a), _resolve(ctx, player_b))
    return comparison.ai_payload(comp)


def t_rankings(ctx: Ctx, category: str | None = None, position: str | None = None, limit: int = 10) -> dict:
    sort = category if category in CAT_LABEL else "value"
    res = rankings.weekly(ctx.proj, sort=sort, position=position, limit=min(int(limit or 10), 25))
    return {"week": res["window"]["label"], "sorted_by": sort, "players": [
        {"rank": r["rank"], "name": r["name"], "team": r["team_abbr"], "games": r["games"], "value": _r(r["value"]),
         "sort_value": _r(r.get(sort), 3 if sort.endswith("pct") else 1), "status": r["status"]} for r in res["rows"]]}


def _need_roster(ctx: Ctx) -> list[int]:
    if not ctx.roster:
        raise ToolError("No roster selected. Ask the user to pick or create a roster on the My Team page.")
    return ctx.roster


def t_my_team(ctx: Ctx, basis: str = "week") -> dict:
    res = team.analyze(ctx.proj, _need_roster(ctx), "season" if basis == "season" else "week", set(),
                       rosters.rostered_elsewhere(ctx.roster_id))
    payload = team.ai_payload(res)
    payload["roster_ranked_by_weekly_value"] = [
        {"name": p["name"], "games": p["games"], "value": _r(p["value"]), "status": p["status"]} for p in res["roster"]]
    return payload


def t_evaluate_trade(ctx: Ctx, give: list[str], get: list[str]) -> dict:
    roster = _need_roster(ctx)
    give_ids, get_ids = [_resolve(ctx, n) for n in give], [_resolve(ctx, n) for n in get]
    try:
        res = trade.evaluate(ctx.proj, roster, give_ids, get_ids, "season", set(), rosters.rostered_elsewhere(ctx.roster_id))
    except trade.TradeError as exc:
        raise ToolError(str(exc)) from None
    return trade.ai_payload(res)


def t_simulate_matchup(ctx: Ctx) -> dict:
    roster = _need_roster(ctx)
    if not ctx.opponent:
        raise ToolError("No opponent roster selected. Ask the user to choose one on the Matchup page.")
    return matchup.ai_payload(matchup.simulate(ctx.proj, roster, ctx.opponent))


def t_streaming(ctx: Ctx, limit: int = 8) -> dict:
    res = streaming.optimize(ctx.proj, _need_roster(ctx), exclude=rosters.rostered_elsewhere(ctx.roster_id),
                             limit=min(int(limit or 8), 15))
    return {"week": res["window"]["label"], "open_slots_by_day": {d["weekday"]: d["open_slots"] for d in res["days"]},
            "suggested_drop": res["drop_candidate"]["name"] if res["drop_candidate"] else None,
            "candidates": [{"name": c["name"], "team": c["team_abbr"], "games": c["games"],
                            "usable_games": _r(c["usable_games"], 1), "stream_value": _r(c["stream_value"]),
                            "helps": [CAT_LABEL[k] for k in c["helps"]], "status": c["status"]} for c in res["candidates"]]}


def t_breakouts(ctx: Ctx, limit: int = 8) -> dict:
    return breakouts.ai_payload(breakouts.detect(limit=min(int(limit or 8), 15)), top=min(int(limit or 8), 15))


def t_schedule(ctx: Ctx, team_abbr: str | None = None) -> dict:
    s = schedule_summary(ctx.proj.window)
    teams = s["games_by_team"]
    if team_abbr:
        teams = [t for t in teams if t["abbr"].upper() == team_abbr.upper()]
    return {"week": s["window"]["label"], "games_by_day": s["games_by_day"],
            "games_by_team": [{"team": t["abbr"], "games": t["games"]} for t in teams]}


TOOLS: dict[str, tuple[Callable[..., dict], str, dict]] = {
    "find_player": (t_find_player, "Search players by (partial) name.",
                    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
    "player_report": (t_player_report, "Season averages, last 5/10 games, injury status and this week's projection for one player.",
                      {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
    "compare_players": (t_compare_players, "Head-to-head 9-category comparison of two players for the selected week.",
                        {"type": "object", "properties": {"player_a": {"type": "string"}, "player_b": {"type": "string"}},
                         "required": ["player_a", "player_b"]}),
    "rankings": (t_rankings, "Weekly projected leaderboard, overall 9-cat value or sorted by one category.",
                 {"type": "object", "properties": {
                     "category": {"type": "string", "enum": list(CAT_LABEL)},
                     "position": {"type": "string", "enum": ["G", "F", "C"]},
                     "limit": {"type": "integer"}}}),
    "my_team": (t_my_team, "Analyze the user's selected roster: category strengths/weaknesses, roster values, pickup ideas.",
                {"type": "object", "properties": {"basis": {"type": "string", "enum": ["week", "season"]}}}),
    "evaluate_trade": (t_evaluate_trade, "Evaluate a trade for the user's roster (give players on the roster, get other players).",
                       {"type": "object", "properties": {"give": {"type": "array", "items": {"type": "string"}},
                                                         "get": {"type": "array", "items": {"type": "string"}}},
                        "required": ["give", "get"]}),
    "simulate_matchup": (t_simulate_matchup, "Monte Carlo simulation of the user's roster vs the selected opponent for the week.",
                         {"type": "object", "properties": {}}),
    "streaming_pickups": (t_streaming, "Best free-agent streamers for the week given the user's open lineup slots and needs.",
                          {"type": "object", "properties": {"limit": {"type": "integer"}}}),
    "breakout_candidates": (t_breakouts, "Players with measurable recent increases in minutes, usage and production.",
                            {"type": "object", "properties": {"limit": {"type": "integer"}}}),
    "schedule": (t_schedule, "Games per day and per team in the selected week.",
                 {"type": "object", "properties": {"team_abbr": {"type": "string"}}}),
}


def execute(ctx: Ctx, name: str, args: dict | None) -> dict:
    args = dict(args or {})
    entry = TOOLS.get(name)
    if entry is None:
        result = {"error": f"unknown tool {name}"}
    else:
        try:
            result = entry[0](ctx, **args)
        except ToolError as exc:
            result = {"error": str(exc)}
        except TypeError as exc:
            result = {"error": f"bad arguments: {exc}"}
        except Exception as exc:  # noqa: BLE001 - surface to the model, never crash the chat
            log.exception("tool %s failed", name)
            result = {"error": f"{type(exc).__name__}: {exc}"}
    ctx.trace.append({"tool": name, "args": args, "ok": "error" not in result, "result": result})
    return result


# ----------------------------------------------------------------------------- Gemini loop
SYSTEM = """You are the CourtVision AI fantasy basketball assistant for head-to-head 9-category leagues
(PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO; fewer turnovers is better).
Rules:
- ALWAYS call tools to get data before answering questions about players, rosters, trades, matchups or pickups.
- Use ONLY numbers returned by tools. Never invent statistics, injuries, news or schedules. If a tool returns an
  error or lacks the data, say so plainly and suggest what the user can do in the app.
- Format (strict): first line = the recommendation in at most 12 words. Then at most 4 bullets ("- "),
  each at most 15 words, each with a number from the tools. No paragraphs, no markdown tables or bold.
- Plain words: never say "z-score" or "z"; say "above/below average" or quote the real stat."""


def _declarations():
    return [genai_types.FunctionDeclaration(name=n, description=d, parameters_json_schema=s) for n, (_, d, s) in TOOLS.items()]


def ask(proj: Projection, message: str, history: list[dict], roster_id: int | None, opponent_id: int | None) -> dict:
    ctx = Ctx(proj, roster_id, opponent_id)
    if gemini.available:
        try:
            if gemini.provider == "agy":
                return _ask_agy(ctx, message, history)
            return _ask_gemini(ctx, message, history)
        except Exception as exc:  # noqa: BLE001
            notice = f"Gemini unavailable ({_describe_error(exc)}); answered with the rule-based assistant."
            log.warning(notice)
            ctx.trace.clear()
            return _ask_fallback(ctx, message) | {"notice": notice}
    return _ask_fallback(ctx, message) | {"notice": "Gemini is not available (no API key or agy CLI); answered with the rule-based assistant."}


def _context_note(ctx: Ctx) -> str:
    r = rosters.get_roster(ctx.roster_id) if ctx.roster_id else None
    o = rosters.get_roster(ctx.opponent_id) if ctx.opponent_id else None
    return (f"Context: projection window = {ctx.proj.window.label}. "
            f"User roster = {r['name'] + ' (' + str(len(r['player_ids'])) + ' players)' if r else 'none selected'}. "
            f"Opponent roster = {o['name'] if o else 'none selected'}.")


def _ask_gemini(ctx: Ctx, message: str, history: list[dict]) -> dict:
    T = genai_types
    contents = []
    for h in history[-10:]:
        role = "model" if h.get("role") == "assistant" else "user"
        if h.get("content"):
            contents.append(T.Content(role=role, parts=[T.Part(text=str(h["content"])[:4000])]))
    contents.append(T.Content(role="user", parts=[T.Part(text=message)]))
    config = T.GenerateContentConfig(
        system_instruction=SYSTEM + "\n" + _context_note(ctx),
        tools=[T.Tool(function_declarations=_declarations())],
        automatic_function_calling=T.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.3,
    )
    answer = None
    for _ in range(MAX_STEPS):
        resp = gemini.request(contents, config)
        calls = resp.function_calls or []
        if not calls:
            answer = resp.text
            break
        contents.append(resp.candidates[0].content)  # keeps thought signatures intact
        parts = [T.Part.from_function_response(name=c.name, response={"result": execute(ctx, c.name, c.args)})
                 for c in calls]
        contents.append(T.Content(role="user", parts=parts))
    if not answer:
        raise RuntimeError("no final answer after tool calls")
    grounding = grounding_check({"answer": answer}, {"tools": [t["result"] for t in ctx.trace]})
    return {"answer": answer, "source": "gemini", "model": gemini.label, "tool_calls": _public_trace(ctx),
            "grounding": grounding,
            "notice": None if grounding["passed"] else
            f"Some numbers could not be matched to tool data: {', '.join(grounding['ungrounded'][:5])}"}


# ----------------------------------------------------------------------------- agy tool loop
STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["call_tool", "final_answer"]},
        "tool": {"type": "string", "description": "Tool name when action is call_tool"},
        "args_json": {"type": "string", "description": "JSON object of tool arguments, e.g. {\"name\": \"Nikola Jokic\"}"},
        "answer": {"type": "string", "description": "Final answer to the user when action is final_answer"},
    },
    "required": ["action"],
}


def _tool_catalog() -> str:
    return "\n".join(f"- {n}: {d} Arguments schema: {json.dumps(s)}" for n, (_, d, s) in TOOLS.items())


def _ask_agy(ctx: Ctx, message: str, history: list[dict]) -> dict:
    """Tool loop over the agy CLI: each step Gemini returns a tool call or the final answer as JSON."""
    convo = [f"{'Assistant' if h.get('role') == 'assistant' else 'User'}: {str(h.get('content', ''))[:2000]}"
             for h in history[-10:] if h.get("content")]
    steps: list[str] = []
    answer = None
    for _ in range(MAX_STEPS):
        prompt = (f"{SYSTEM}\n{_context_note(ctx)}\n\nAVAILABLE COURTVISION TOOLS (call them through this protocol, "
                  f"not through your own tools):\n{_tool_catalog()}\n\n"
                  + ("CONVERSATION SO FAR:\n" + "\n".join(convo) + "\n\n" if convo else "")
                  + f"USER QUESTION: {message}\n\n"
                  + ("TOOL RESULTS SO FAR:\n" + "\n".join(steps) + "\n\n" if steps else "")
                  + "Decide the next step. Return action=call_tool with tool and args_json to fetch data you still need, "
                    "or action=final_answer with the complete answer once the tool results are enough. "
                    "Never answer with statistics that are not in the tool results. "
                    "Do not use any of your own tools, files or commands.")
        step = gemini.generate_json(prompt, STEP_SCHEMA)
        if step.get("action") == "final_answer" and step.get("answer"):
            answer = step["answer"]
            break
        name = step.get("tool") or ""
        try:
            args = json.loads(step.get("args_json") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as exc:
            result = {"error": f"invalid args_json: {exc}"}
            ctx.trace.append({"tool": name, "args": {}, "ok": False, "result": result})
        else:
            result = execute(ctx, name, args)
        steps.append(f"{name}({json.dumps(args if isinstance(args, dict) else {})}) -> "
                     f"{json.dumps(result, separators=(',', ':'), default=str)[:6000]}")
    if not answer:
        raise RuntimeError("no final answer after tool calls")
    grounding = grounding_check({"answer": answer}, {"tools": [t["result"] for t in ctx.trace]})
    return {"answer": answer, "source": "gemini", "model": gemini.label, "tool_calls": _public_trace(ctx),
            "grounding": grounding,
            "notice": None if grounding["passed"] else
            f"Some numbers could not be matched to tool data: {', '.join(grounding['ungrounded'][:5])}"}


def _public_trace(ctx: Ctx) -> list[dict]:
    return [{"tool": t["tool"], "args": t["args"], "ok": t["ok"],
             "error": t["result"].get("error") if not t["ok"] else None} for t in ctx.trace]


# ----------------------------------------------------------------------------- rule-based fallback
def mentioned_players(ctx: Ctx, text: str, limit: int = 4) -> list[str]:
    """Player names found in free text (full name, or a distinctive last name), in order of appearance."""
    low = player_svc._norm(text)
    df = ctx.proj.players
    found: list[tuple[int, str]] = []
    for name in df["name"].dropna():
        n = player_svc._norm(name)
        pos = low.find(n)
        if pos < 0:
            last = n.split()[-1]
            if len(last) >= 5 and re.search(rf"\b{re.escape(last)}\b", low):
                pos = re.search(rf"\b{re.escape(last)}\b", low).start()
        if pos >= 0:
            found.append((pos, name))
    found.sort()
    out: list[str] = []
    for _, name in found:
        if name not in out:
            out.append(name)
    return out[:limit]


def mentioned_categories(text: str) -> list[str]:
    low = text.lower()
    low = re.sub(r"\b(three|3) games?\b", "", low)  # "three games" is about schedule, not 3PM
    return [k for k, stems in CAT_WORDS.items() if any(re.search(rf"(?<![\w%]){re.escape(w)}", low) for w in stems)]


def _fmt_list(items: list[str]) -> str:
    return "\n".join(f"• {i}" for i in items)


def _ask_fallback(ctx: Ctx, message: str) -> dict:
    low = message.lower()
    names = mentioned_players(ctx, message)
    cats = mentioned_categories(message)
    answer = _route(ctx, low, names, cats)
    return {"answer": answer, "source": "fallback", "model": None, "tool_calls": _public_trace(ctx), "grounding": None}


def _route(ctx: Ctx, low: str, names: list[str], cats: list[str]) -> str:
    if re.search(r"\btrad(e|es|ed|ing)\b", low) and len(names) >= 2:
        mine = set(ctx.roster)
        ids = {n: _safe_id(ctx, n) for n in names}
        give = [n for n in names if ids[n] in mine]
        get = [n for n in names if ids[n] not in mine]
        if give and get:
            r = execute(ctx, "evaluate_trade", {"give": give, "get": get})
            if "error" in r:
                return f"I couldn't evaluate that trade: {r['error']}"
            ch = sorted(r["category_changes"], key=lambda c: c["z_delta"], reverse=True)
            return (f"Trade verdict: {r['computed_verdict'].upper()} (need-weighted change {r['need_weighted_delta']:+.2f}, "
                    f"total 9-cat change {r['total_value_delta']:+.2f}).\n"
                    + _fmt_list([f"{c['category']}: {c['before']} -> {c['after']}" for c in ch[:2] + ch[-2:]]))
        return "Tell me which players you give (from your roster) and which you get, and pick your roster on the My Team page."
    if len(names) >= 2 and any(w in low for w in ("better", " vs", "versus", "compare", " or ", "who should")):
        r = execute(ctx, "compare_players", {"player_a": names[0], "player_b": names[1]})
        if "error" in r:
            return r["error"]
        a, b = r["players"]
        focus = cats or ["pts", "reb", "ast", "stl", "blk", "fg3m", "fg_pct", "ft_pct", "tov"]
        lines = []
        score = {a["name"]: 0.0, b["name"]: 0.0}
        for k in focus:
            lb = CAT_LABEL[k]
            za, zb = a["per_game_z_scores"][lb] or 0, b["per_game_z_scores"][lb] or 0
            score[a["name"]] += za
            score[b["name"]] += zb
            lines.append(f"{lb}: {a['name']} {a['weekly_projection'][lb]} vs {b['name']} {b['weekly_projection'][lb]} this week")
        best = max(score, key=score.get)
        scope = " and ".join(CAT_LABEL[k] for k in cats) if cats else "overall fantasy value"
        head = (f"For {scope}, {best} is the better option."
                if cats else f"{best} projects better this week (weekly value {a['weekly_9cat_value']} vs {b['weekly_9cat_value']}"
                f" for {a['name']} vs {b['name']}).")
        return head + "\n" + _fmt_list(lines)
    if any(w in low for w in ("pick up", "pickup", "waiver", "stream", "add ", "free agent")):
        r = execute(ctx, "streaming_pickups", {"limit": 5})
        if "error" in r:
            return r["error"]
        return (f"Top pickups for {r['week']} (based on your open lineup slots and category needs):\n"
                + _fmt_list([f"{c['name']} ({c['team']}): {c['usable_games']} usable of {c['games']} games, "
                             f"stream value {c['stream_value']}, helps {', '.join(c['helps']) or 'overall'}" for c in r["candidates"]])
                + (f"\nSuggested drop: {r['suggested_drop']}." if r["suggested_drop"] else ""))
    if any(w in low for w in ("win", "5-4", "matchup", "chance", "odds")):
        r = execute(ctx, "simulate_matchup", {})
        if "error" in r:
            return r["error"]
        cats_sorted = sorted(r["categories"], key=lambda c: c["p_win"])
        swing = [c for c in cats_sorted if 0.3 <= c["p_win"] <= 0.7]
        return (f"You win {round(r['p_win_matchup'] * 100)}% of {r['simulations']} simulations and get 5+ categories "
                f"{round(r['p_win_5_or_more_categories'] * 100)}% of the time (expected {r['expected_categories_won']} categories).\n"
                "Swing categories to target:\n"
                + _fmt_list([f"{c['category']}: {round(c['p_win'] * 100)}% (you {c['my_projected']} vs {c['opponent_projected']})"
                             for c in swing] or ["None are close; protect your leads."]))
    if any(w in low for w in ("breakout", "trending", "rising", "hot ")):
        r = execute(ctx, "breakout_candidates", {"limit": 5})
        return "Players trending up (last 5 vs previous 25 games):\n" + _fmt_list(
            [f"{p['name']} ({p['team']}): minutes {p['minutes'][0]} -> {p['minutes'][1]}, "
             f"value/game {p['value_per_game'][0]} -> {p['value_per_game'][1]}" for p in r["players"]])
    if any(w in low for w in ("start", "sit", "lineup", "bench")):
        if len(names) >= 2:
            return _route(ctx, low + " compare", names, cats)
        r = execute(ctx, "my_team", {"basis": "week"})
        if "error" in r:
            return r["error"]
        ranked = r["roster_ranked_by_weekly_value"]
        return ("Start your highest projected players this week (value includes games scheduled):\n"
                + _fmt_list([f"{p['name']}: {p['games']} games, weekly value {p['value']} ({p['status']})" for p in ranked[:8]])
                + "\nLowest projected: " + ", ".join(f"{p['name']} ({p['value']})" for p in ranked[-3:]) + ".")
    if any(w in low for w in ("top", "best", "rank", "leader")) or (cats and not names):
        cat = cats[0] if cats else None
        r = execute(ctx, "rankings", {"category": cat, "limit": 8})
        return (f"Top projected players for {r['week']}" + (f" in {CAT_LABEL[cat]}" if cat else " (fantasy value)") + ":\n"
                + _fmt_list([f"{p['rank']}. {p['name']} ({p['team']}, {p['games']}G): "
                             + (f"{CAT_LABEL[cat]} {p['sort_value']}" if cat else f"value {p['value']}") for p in r["players"]]))
    if names:
        r = execute(ctx, "player_report", {"name": names[0]})
        if "error" in r:
            return r["error"]
        proj = next((v for k, v in r.items() if k.startswith("projection_")), None) or {}
        last5 = r.get("last5") or {}
        return (f"{r['name']} ({r['team']}, {r['position']}): projected rank {proj.get('rank')} with "
                f"{proj.get('games')} games and weekly fantasy value {proj.get('weekly_9cat_value')}.\n"
                f"Last 5 games: {last5.get('pts')} pts, {last5.get('reb')} reb, {last5.get('ast')} ast in {last5.get('min')} min."
                + (f"\nInjury: {r['injury']['status']}" if r.get("injury") else ""))
    return ("I can answer questions about players, comparisons, rankings, your team, trades, matchups, pickups and "
            "breakouts. Try: “Who is better for steals and blocks, Dyson Daniels or Jalen Johnson?”, “Who should I pick up?”, "
            "or “How can I win 5-4 this week?”.")


def _safe_id(ctx: Ctx, name: str) -> int | None:
    try:
        return _resolve(ctx, name)
    except ToolError:
        return None


__all__ = ["ask", "execute", "TOOLS", "Ctx", "mentioned_players", "mentioned_categories"]
