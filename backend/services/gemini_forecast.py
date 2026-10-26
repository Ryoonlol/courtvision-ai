"""Gemini forecast: an independent projection model produced by Gemini (through the agy CLI).

For each player Gemini receives only real data computed from the cached box scores:
  * the last 10 games (minutes and every 9-cat input stat),
  * current- and prior-season per-game averages,
  * the scheduled games in the window (opponent, home/away, rest days),
  * the injury-report status (live forecasts only).
It returns per-game forecasts (minutes + the 11 raw stats) and the number of games it expects the player to
play. Python validates and sanitises every number, turns them into weekly totals, and values them with the
same 9-category z-score method and pool as the statistical model, so the two are directly comparable.

Two jobs run in the background:
  live      -- forecasts the selected window for the top statistical players + rostered players;
               pre-week forecasts are also written to ``projection_log`` (method 'gemini') for forward scoring.
  backtest  -- forecasts past weeks using only games before each week; scored in the accuracy tracker.
               Caveat: Gemini may have seen those seasons during training, so backtest scores can be optimistic.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core.categories import CATEGORIES, MODEL_STATS, RAW_STATS
from core.config import settings
from core.db import get_conn
from data import repository as repo
from data.ingest import season_label
from services import agy_client, valuation
from services.projections import Projection
from services.schedule import today

log = logging.getLogger("courtvision.forecast")

LOG_GAMES = 10
STAT_KEYS = MODEL_STATS  # min + pts reb ast stl blk fg3m tov fgm fga ftm fta
MAX_PER_GAME = {"min": 48, "pts": 70, "reb": 30, "ast": 25, "stl": 8, "blk": 10, "fg3m": 14, "tov": 12,
                "fgm": 28, "fga": 45, "ftm": 25, "fta": 30}
CALL_TIMEOUT = 300

FORECAST_SCHEMA = {
    "type": "object",
    "properties": {
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "player_id": {"type": "integer"},
                    "expected_games": {"type": "number", "description": "Games the player is expected to play in the window"},
                    "per_game": {"type": "object", "properties": {k: {"type": "number"} for k in STAT_KEYS},
                                 "required": list(STAT_KEYS)},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "rationale": {"type": "string", "description": "One sentence citing the data behind the forecast"},
                },
                "required": ["player_id", "expected_games", "per_game", "confidence", "rationale"],
            },
        },
    },
    "required": ["players"],
}

INSTRUCTIONS = """You are an NBA statistical forecaster for fantasy basketball. For EVERY player listed, forecast
per-game averages for the scheduled games in the window: min, pts, reb, ast, stl, blk, fg3m, tov, fgm, fga, ftm, fta.
Use ONLY the data provided: recent game logs, season averages, schedule and injury status. Apply basketball
judgment to it (minutes and role trends, sample size, regression to the mean, opponent, rest), but do not use
outside news or knowledge of results after the data. Keep values internally consistent (fgm <= fga, ftm <= fta,
fg3m <= fgm, pts ~= 2*fgm + fg3m + ftm). expected_games = how many of the listed scheduled games the player
will play (0 to the number listed; account for the injury status). Return one entry per player_id, using the
exact ids given. Do not use any tools, files or commands."""


# --------------------------------------------------------------------------- context
def player_context(box: pd.DataFrame, pid: int, name: str, team: str | None, schedule: list[dict],
                   status: str | None, current_season: int) -> dict:
    """Compact, real-data context for one player (``box`` must only contain games before the window)."""
    logs = box[box["player_id"] == pid].sort_values("date")
    recent = logs.tail(LOG_GAMES)
    cols = ["min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fgm", "fga", "ftm", "fta"]

    def avg(df):
        return {"games": int(len(df)), **{c: round(float(df[c].mean()), 1) for c in cols}} if len(df) else None
    return {
        "player_id": int(pid), "name": name, "team": team, "status": status or "Active",
        "season_avg": avg(logs[logs["season"] == current_season]),
        "prior_season_avg": avg(logs[logs["season"] == current_season - 1]),
        "last_games": [[r["date"].date().isoformat(), *[int(r[c]) for c in cols]] for _, r in recent.iterrows()],
        "last_games_columns": ["date", *cols],
        "scheduled_games": schedule,
    }


def sanitize(item: dict, max_games: int) -> tuple[dict, list[str]]:
    """Clamp a Gemini forecast to valid ranges; returns (clean forecast, list of fixes applied)."""
    fixes = []
    pg = {}
    raw = item.get("per_game") or {}
    for k in STAT_KEYS:
        try:
            v = float(raw.get(k, 0.0))
        except (TypeError, ValueError):
            v, _ = 0.0, fixes.append(f"{k} not numeric")
        if not np.isfinite(v) or v < 0:
            fixes.append(f"{k} negative/invalid")
            v = 0.0
        if v > MAX_PER_GAME[k]:
            fixes.append(f"{k} capped")
            v = float(MAX_PER_GAME[k])
        pg[k] = v
    for makes, att in (("fgm", "fga"), ("ftm", "fta"), ("fg3m", "fgm")):
        if pg[makes] > pg[att]:
            fixes.append(f"{makes} > {att}")
            pg[makes] = pg[att]
    try:
        exp = float(item.get("expected_games", max_games))
    except (TypeError, ValueError):
        exp = float(max_games)
    if not 0 <= exp <= max_games:
        fixes.append("expected_games clamped")
        exp = float(np.clip(exp, 0, max_games))
    conf = item.get("confidence") if item.get("confidence") in {"low", "medium", "high"} else "low"
    return {"per_game": pg, "expected_games": exp, "confidence": conf,
            "rationale": str(item.get("rationale") or "")[:400]}, fixes


def forecast_batch(contexts: list[dict], window_label: str) -> dict[int, dict]:
    """One agy call for a batch of players. Returns {player_id: sanitized forecast}."""
    prompt = (f"{INSTRUCTIONS}\n\nWINDOW: {window_label}\nPLAYERS (JSON):\n"
              + json.dumps(contexts, separators=(",", ":")))
    out = agy_client.generate_json(prompt, FORECAST_SCHEMA, timeout=CALL_TIMEOUT, model=settings.forecast_model)
    by_id = {}
    wanted = {c["player_id"]: len(c["scheduled_games"]) for c in contexts}
    for item in out.get("players", []):
        try:
            pid = int(item.get("player_id"))
        except (TypeError, ValueError):
            continue
        if pid not in wanted:
            continue
        clean, fixes = sanitize(item, wanted[pid])
        clean["fixes"] = fixes
        by_id[pid] = clean
    return by_id


# --------------------------------------------------------------------------- jobs
JOBS: dict[str, dict] = {}
_job_lock = threading.Lock()


def job_status(kind: str) -> dict | None:
    with _job_lock:
        return dict(JOBS[kind]) if kind in JOBS else None


def _start(kind: str, target, total: int, meta: dict) -> dict:
    with _job_lock:
        cur = JOBS.get(kind)
        if cur and cur["status"] == "running":
            return dict(cur)
        JOBS[kind] = {"kind": kind, "status": "running", "done": 0, "total": total, "errors": [],
                      "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
                      "model": settings.forecast_model, **meta}
    threading.Thread(target=_run_safe, args=(kind, target), daemon=True, name=f"forecast-{kind}").start()
    return job_status(kind)


def _run_safe(kind: str, target) -> None:
    try:
        target()
        status = "done"
    except Exception as exc:  # noqa: BLE001
        log.exception("forecast job %s failed", kind)
        JOBS[kind]["errors"].append(str(exc)[:300])
        status = "error"
    with _job_lock:
        # a job with some failed batches still counts as done if any batch succeeded (errors stay listed)
        JOBS[kind]["status"] = status
        JOBS[kind]["finished_at"] = datetime.now(timezone.utc).isoformat()


def _run_batches(kind: str, batches: list[tuple[str, str, list[dict]]]) -> dict[str, dict[int, dict]]:
    """Run (week_key, label, contexts) batches with up to 3 concurrent agy calls.

    Results are keyed by week first: the same player can appear in several backtest weeks.
    Partial failures are recorded on the job, not fatal.
    """
    results: dict[str, dict[int, dict]] = {}

    def one(arg):
        key, label, ctxs = arg
        try:
            return key, forecast_batch(ctxs, label)
        except Exception as exc:  # noqa: BLE001
            with _job_lock:
                JOBS[kind]["errors"].append(f"{label}: {str(exc)[:200]}")
            return key, {}
        finally:
            with _job_lock:
                JOBS[kind]["done"] += 1

    with ThreadPoolExecutor(3) as pool:
        for key, part in pool.map(one, batches):
            results.setdefault(key, {}).update(part)
    return results


def _chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def _store(kind: str, week_start: str, results: dict[int, dict], extra: dict[int, dict] | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        for pid, fc in results.items():
            payload = fc | (extra or {}).get(pid, {})
            conn.execute("INSERT OR REPLACE INTO gemini_forecasts(kind, week_start, player_id, model, created_at, payload)"
                         " VALUES(?,?,?,?,?,?)", (kind, week_start, int(pid), settings.forecast_model, now, json.dumps(payload)))


# --------------------------------------------------------------------------- live forecast
def live_candidates(proj: Projection, top_n: int, extra_ids: set[int]) -> list[int]:
    active = proj.players[proj.players["games"] > 0]
    ids = list(active.sort_values("rank").index[:top_n])
    ids += [p for p in extra_ids if p in active.index and p not in ids]
    return [int(p) for p in ids]


def start_live(proj: Projection, top_n: int = 120, extra_ids: set[int] | None = None) -> dict:
    ids = live_candidates(proj, top_n, extra_ids or set())
    box = repo.box_scores()
    box = box[box["date"] < pd.Timestamp(proj.window.start)]
    teams = repo.teams()
    from data.ingest import CURRENT_SEASON
    ctxs = []
    for pid in ids:
        r = proj.players.loc[pid]
        games = proj.games[proj.games["player_id"] == pid].sort_values("date")
        sched = [{"date": g["date"].date().isoformat(),
                  "opponent": teams.at[g["opp_team_id"], "abbr"] if g["opp_team_id"] in teams.index else "?",
                  "home": bool(g["home"]), "rest_days": int(g["rest"])} for _, g in games.iterrows()]
        ctxs.append(player_context(box, pid, r["name"], r["team_abbr"], sched, r["status"], CURRENT_SEASON))
    week_key = proj.window.start.isoformat()
    batches = [(week_key, proj.window.label, chunk) for chunk in _chunks(ctxs, settings.forecast_batch)]

    def work():
        results = _run_batches("live", batches).get(week_key, {})
        _store("live", week_key, results)
        if proj.window.key == "next" and today() < proj.window.week_start:
            _log_to_projection_log(proj, results)
    return _start("live", work, len(batches), {"window": proj.window.as_dict(), "players": len(ids)})


def weekly_totals(fc: dict) -> dict:
    g = fc["expected_games"]
    return {k: fc["per_game"][k] * g for k in STAT_KEYS}


def _log_to_projection_log(proj: Projection, results: dict[int, dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    df = pd.DataFrame({pid: weekly_totals(fc) for pid, fc in results.items()}).T
    if df.empty:
        return
    values = valuation.score(df[RAW_STATS], proj.params)["value"]
    with get_conn() as conn:
        for pid, fc in results.items():
            payload = weekly_totals(fc) | {"games": int(proj.players.at[pid, "games"]), "exp_games": fc["expected_games"],
                                           "value": float(values[pid])}
            conn.execute("INSERT OR REPLACE INTO projection_log(week_start, player_id, method, created_at, games, payload)"
                         " VALUES(?,?,?,?,?,?)", (proj.window.week_start.isoformat(), int(pid), "gemini", now,
                                                  payload["games"], json.dumps(payload)))


def load(kind: str, week_start: str) -> dict[int, dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT player_id, payload, model, created_at FROM gemini_forecasts WHERE kind=? AND week_start=?",
                            (kind, week_start)).fetchall()
    return {r["player_id"]: json.loads(r["payload"]) | {"model": r["model"], "created_at": r["created_at"]} for r in rows}


def view(proj: Projection) -> dict:
    """Side-by-side statistical vs Gemini weekly projections for players with a Gemini forecast."""
    fcs = load("live", proj.window.start.isoformat())
    out = {"window": proj.window.as_dict(), "job": job_status("live"), "players": 0, "rows": []}
    ids = [p for p in fcs if p in proj.players.index]
    if not ids:
        return out
    stat = proj.players.loc[ids]
    gem = pd.DataFrame({p: weekly_totals(fcs[p]) for p in ids}).T
    gz = valuation.score(gem[RAW_STATS], proj.params)
    gem = pd.concat([gem, gz], axis=1)
    stat_rank = stat["value"].rank(ascending=False, method="first")
    gem_rank = gem["value"].rank(ascending=False, method="first")
    rows = []
    for pid in ids:
        s, g, fc = stat.loc[pid], gem.loc[pid], fcs[pid]
        cats = {}
        for c in CATEGORIES:
            if c.is_pct:
                sv = s[c.makes] / s[c.attempts] if s[c.attempts] > 0 else None
                gv = g[c.makes] / g[c.attempts] if g[c.attempts] > 0 else None
            else:
                sv, gv = float(s[c.key]), float(g[c.key])
            cats[c.key] = {"stat": None if sv is None else float(sv), "gemini": None if gv is None else float(gv)}
        rows.append({
            "player_id": int(pid), "name": s["name"], "team_abbr": s["team_abbr"], "headshot": s["headshot"],
            "position": s["position"], "status": s["status"], "games": int(s["games"]),
            "stat_expected_games": float(s["exp_games"]), "gemini_expected_games": fc["expected_games"],
            "stat_value": float(s["value"]), "gemini_value": float(g["value"]),
            "stat_rank": int(stat_rank[pid]), "gemini_rank": int(gem_rank[pid]),
            "stat_min": float(s["pg_min"]) if pd.notna(s["pg_min"]) else None, "gemini_min": fc["per_game"]["min"],
            "categories": cats, "confidence": fc["confidence"], "rationale": fc["rationale"], "fixes": fc.get("fixes", []),
        })
    rows.sort(key=lambda r: r["stat_rank"])
    first = next(iter(fcs.values()))
    out.update({
        "players": len(rows), "rows": rows, "model": first.get("model"), "created_at": first.get("created_at"),
        "agreement_spearman": float(stat["value"].corr(gem["value"], method="spearman")) if len(ids) > 2 else None,
        "mean_abs_value_gap": float((stat["value"] - gem["value"]).abs().mean()),
    })
    return out


def players_view(proj: Projection, ids: list[int]) -> dict:
    v = view(proj)
    return {"window": v["window"], "rows": [r for r in v["rows"] if r["player_id"] in ids]}


# --------------------------------------------------------------------------- backtest
DEFAULT_BACKTEST_WEEKS = ["2025-11-17", "2026-01-05", "2026-02-09", "2026-03-16"]


def start_backtest(weeks: list[str] | None = None, per_week: int = 40) -> dict:
    from services.accuracy import _state_at_week_start
    from services.history import weekly_totals as history_totals
    weeks = weeks or DEFAULT_BACKTEST_WEEKS
    state = _state_at_week_start()
    wt = history_totals()
    box = repo.box_scores()
    games = repo.games()
    teams, players = repo.teams(), repo.players()
    batches = []
    selections = {}
    for ws in weeks:
        start = pd.Timestamp(ws) - pd.Timedelta(days=pd.Timestamp(ws).weekday())
        if start not in state.index.get_level_values(0):
            continue
        st = state.loc[start]
        st = st[st["base_pts"].notna()]
        # pick players by the statistical model's pre-week per-game value (no peeking at the week)
        rates = pd.DataFrame({s: st[f"base_{s}"] for s in RAW_STATS})
        pick = valuation.score(rates, valuation.fit(rates))["value"].sort_values(ascending=False).index[:per_week]
        before = box[box["date"] < start]
        end = start + pd.Timedelta(days=6)
        wk_games = games[(games["date"] >= start) & (games["date"] <= end)]
        season = int(st.loc[pick[0], "season"]) if len(pick) else None
        ctxs = []
        for pid in pick:
            team_id = int(st.at[pid, "team_id"])
            tg = wk_games[(wk_games["home_team_id"] == team_id) | (wk_games["away_team_id"] == team_id)]
            sched = [{"date": g["date"].date().isoformat(),
                      "opponent": g["away_abbr"] if g["home_team_id"] == team_id else g["home_abbr"],
                      "home": bool(g["home_team_id"] == team_id)} for _, g in tg.iterrows()]
            ctxs.append(player_context(before, int(pid), players.at[pid, "name"] if pid in players.index else str(pid),
                                       teams.at[team_id, "abbr"] if team_id in teams.index else None, sched,
                                       "Injury report not available for historical weeks", season))
        key = start.date().isoformat()
        selections[key] = [int(p) for p in pick]
        label = f"Week of {start:%b %-d, %Y} ({season_label(season)} season)"
        batches += [(key, label, chunk) for chunk in _chunks(ctxs, settings.forecast_batch)]

    def work():
        results = _run_batches("backtest", batches)
        for ws in selections:
            _store("backtest", ws, results.get(ws, {}))
    return _start("backtest", work, len(batches), {"weeks": list(selections), "per_week": per_week})


def backtest_scores() -> dict:
    """Score stored Gemini backtests against actual weeks, next to the statistical and naive baselines."""
    from services.accuracy import METHODS, _rate, _state_at_week_start, _week_metrics
    from services.history import weekly_totals as history_totals
    with get_conn() as conn:
        weeks = [r["week_start"] for r in conn.execute(
            "SELECT DISTINCT week_start FROM gemini_forecasts WHERE kind='backtest' ORDER BY week_start")]
    if not weeks:
        return {"weeks": [], "overall": None}
    state = _state_at_week_start()
    wt = history_totals().set_index(["week_start", "player_id"])
    rows = []
    for ws in weeks:
        fcs = load("backtest", ws)
        start = pd.Timestamp(ws)
        if start not in wt.index.get_level_values(0):
            continue
        act = wt.loc[start]
        st = state.loc[start]
        ids = act.index.intersection(list(fcs)).intersection(st.index)
        if len(ids) < 5:
            continue
        act = act.loc[ids]
        g = act["games"]
        rec = {"week_start": ws, "players": int(len(ids)), "model": next(iter(fcs.values())).get("model")}
        rec["gemini"] = _week_metrics(act, pd.DataFrame({s: pd.Series({p: fcs[p]["per_game"][s] for p in ids}) * g
                                                         for s in RAW_STATS}))
        for m in METHODS:
            rec[m] = _week_metrics(act, pd.DataFrame({s: _rate(st.loc[ids], s, m) * g for s in RAW_STATS}))
        rows.append(rec)
    keys = ["spearman", "top50_overlap", *[c.key for c in CATEGORIES]]
    overall = {m: {k: float(np.nanmean([r[m][k] for r in rows if r[m][k] is not None])) for k in keys}
               for m in ("gemini", *METHODS)} if rows else None
    return {"weeks": rows, "overall": overall,
            "caveat": ("Backtest weeks are from seasons Gemini may have seen during training, so its scores here may be "
                       "optimistic. Forward-scored live weeks (saved before the week starts) are the clean comparison.")}


def default_backtest_weeks() -> list[str]:
    return list(DEFAULT_BACKTEST_WEEKS)

