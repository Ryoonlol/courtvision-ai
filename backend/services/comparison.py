"""Head-to-head player comparison plus the Gemini recommendation built on top of it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.categories import CATEGORIES, category_winner
from services import players as player_svc
from services.gemini_service import AIResponse, brief, gemini
from services.projections import Projection, explain_player, player_row

ROSTER_NEEDS = {
    "Big-man stats (REB, BLK, FG%)": ["reb", "blk", "fg_pct"],
    "Playmaking & guard stats (AST, STL, 3PM)": ["ast", "stl", "fg3m"],
    "Scoring (PTS, 3PM, FT%)": ["pts", "fg3m", "ft_pct"],
    "Ball security (fewer TO)": ["tov"],
}


def build(proj: Projection, a: int, b: int) -> dict:
    pa, pb = player_svc.player_profile(a), player_svc.player_profile(b)
    if pa is None or pb is None:
        raise KeyError("player not found")
    ra, rb = player_row(proj, a), player_row(proj, b)
    categories = []
    for c in CATEGORIES:
        wa = ra.get(c.key) if ra else None
        wb = rb.get(c.key) if rb else None
        za = ra.get(f"pg_z_{c.key}") if ra else None
        zb = rb.get(f"pg_z_{c.key}") if rb else None
        categories.append({
            "key": c.key, "label": c.label, "name": c.name, "higher_is_better": c.higher_is_better,
            "weekly_a": wa, "weekly_b": wb, "weekly_winner": category_winner(c.key, wa, wb),
            "z_a": za, "z_b": zb,
            "per_game_winner": _z_winner(za, zb),
            "weekly_z_a": ra.get(f"z_{c.key}") if ra else None,
            "weekly_z_b": rb.get(f"z_{c.key}") if rb else None,
        })
    return {
        "window": proj.window.as_dict(),
        "methods": proj.methods,
        "players": [
            _player_block(pa, ra, explain_player(proj, a)),
            _player_block(pb, rb, explain_player(proj, b)),
        ],
        "categories": categories,
        "summary": {
            "weekly_wins_a": sum(c["weekly_winner"] == "a" for c in categories),
            "weekly_wins_b": sum(c["weekly_winner"] == "b" for c in categories),
            "per_game_wins_a": sum(c["per_game_winner"] == "a" for c in categories),
            "per_game_wins_b": sum(c["per_game_winner"] == "b" for c in categories),
        },
    }


def _z_winner(za, zb) -> str:
    if za is None or zb is None or abs(za - zb) < 0.05:
        return "tie"
    return "a" if za > zb else "b"


def _player_block(profile: dict, row: dict | None, explain: dict) -> dict:
    return {"profile": profile, "projection": row, "explain": explain}


# --------------------------------------------------------------------------- Gemini
class RosterFit(BaseModel):
    need: str = brief("Roster need, e.g. 'Blocks & boards' or 'Punt FT%'", words=4)
    pick: str = Field(description="Exact name of the better player for this need")
    reason: str = brief("Why, with one number", words=12)


class ComparisonInsight(BaseModel):
    headline: str = brief("Verdict", words=10)
    overall_pick: str = Field(description="Exact name of the better player this week, or 'Toss-up'")
    summary: str = brief("Why, citing the weekly 9-cat values", words=30)
    roster_fits: list[RosterFit] = brief("Roster needs and which player fits each", items=3)
    key_edges: list[str] = brief("Decisive category edges, e.g. 'BLK: Wemby 10.6 vs 2.5'", words=10, items=3)
    risks: list[str] = brief("Risks: injury, schedule, small samples", words=12, items=2)
    confidence: Literal["low", "medium", "high"]

COMPARE_INSTRUCTIONS = """Compare these two players for a fantasy manager deciding between them for the
projected week. Explain which player is better overall AND which is better for different roster needs
(e.g. a team needing big-man stats vs. guard stats, punt builds). Use the weekly projection (which
includes the number of scheduled games) for the overall verdict and per-game z-scores to describe
skill profiles. Mention injury status or uncertainty only if present in the data."""


def ai_payload(comp: dict) -> dict:
    """Compact, model-ready view of the comparison (numbers only from CourtVision)."""
    players = []
    for blk in comp["players"]:
        prof, row = blk["profile"], blk["projection"] or {}
        cur = prof["seasons"].get(prof["current_season"]) or {}
        prev_label = next((k for k in prof["seasons"] if k != prof["current_season"]), None)
        prev = prof["seasons"].get(prev_label) if prev_label else None
        players.append({
            "name": prof["name"], "team": prof["team_abbr"], "position": prof["position"],
            "injury_status": row.get("status") or "Active",
            "injury_note": (prof["injury"] or {}).get("short_comment"),
            "games_scheduled": row.get("games"), "expected_games_played": _r(row.get("exp_games")),
            "weekly_projection": {c.label: _r(row.get(c.key), 3 if c.is_pct else 1) for c in CATEGORIES},
            "weekly_9cat_value": _r(row.get("value")),
            "weekly_value_80pct_range": [_r(row.get("value_lo")), _r(row.get("value_hi"))],
            "per_game_z_scores": {c.label: _r(row.get(f"pg_z_{c.key}")) for c in CATEGORIES},
            "per_game_value": _r(row.get("pg_value")),
            "projected_minutes": _r(row.get("pg_min")),
            "current_season_avg": _season_brief(cur),
            "prior_season_avg": ({"season": prev_label, **_season_brief(prev)} if prev else None),
            "last5_avg": _season_brief(prof.get("last5") or {}),
        })
    return {
        "week": comp["window"]["label"],
        "players": players,
        "category_results_weekly": {c["label"]: _winner_name(c["weekly_winner"], players) for c in comp["categories"]},
        "weekly_category_wins": {players[0]["name"]: comp["summary"]["weekly_wins_a"],
                                 players[1]["name"]: comp["summary"]["weekly_wins_b"]},
    }


def _season_brief(s: dict) -> dict:
    if not s:
        return {}
    keys = ["games", "min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fg_pct", "ft_pct"]
    return {k: _r(s.get(k), 3 if k.endswith("pct") else 1) for k in keys}


def _winner_name(w: str, players: list[dict]) -> str:
    return {"a": players[0]["name"], "b": players[1]["name"]}.get(w, "Tie")


def _r(v, nd: int = 2):
    return None if v is None else round(float(v), nd)


def fallback_insight(payload: dict) -> ComparisonInsight:
    """Deterministic explanation derived purely from the computed numbers."""
    pa, pb = payload["players"]
    va, vb = pa["weekly_9cat_value"] or 0.0, pb["weekly_9cat_value"] or 0.0
    gap = abs(va - vb)
    pick = "Toss-up" if gap < 0.5 else (pa["name"] if va > vb else pb["name"])
    wins = payload["weekly_category_wins"]
    fits = []
    for need, keys in ROSTER_NEEDS.items():
        labels = [next(c.label for c in CATEGORIES if c.key == k) for k in keys]
        za = sum((pa["per_game_z_scores"].get(lb) or 0) for lb in labels)
        zb = sum((pb["per_game_z_scores"].get(lb) or 0) for lb in labels)
        better, other = (pa, pb) if za >= zb else (pb, pa)
        fits.append(RosterFit(
            need=need, pick=better["name"],
            reason=f"{better['name']} rates higher than {other['name']} across {', '.join(labels)}.",
        ))
    edges = []
    diffs = []
    for lb in pa["per_game_z_scores"]:
        za, zb = pa["per_game_z_scores"][lb] or 0, pb["per_game_z_scores"][lb] or 0
        diffs.append((abs(za - zb), lb, za, zb))
    for _, lb, za, zb in sorted(diffs, reverse=True)[:3]:
        lead = pa["name"] if za > zb else pb["name"]
        wa, wb = pa["weekly_projection"][lb], pb["weekly_projection"][lb]
        edges.append(f"{lb}: {lead} ({wa if lead == pa['name'] else wb} vs {wb if lead == pa['name'] else wa})")
    risks = []
    for p in (pa, pb):
        if p["injury_status"] and not p["injury_status"].startswith("Active"):
            risks.append(f"{p['name']} is listed as {p['injury_status']}.")
        rng = p["weekly_value_80pct_range"]
        if rng[0] is not None and rng[1] is not None and rng[1] - rng[0] > 9:
            risks.append(f"{p['name']} has a wide weekly value range ({rng[0]:.1f} to {rng[1]:.1f}).")
    if pa["games_scheduled"] != pb["games_scheduled"]:
        risks.append(f"Schedule: {pa['name']} has {pa['games_scheduled']} games vs {pb['games_scheduled']} for {pb['name']}.")
    if not risks:
        risks.append("No injury flags; both projections carry normal weekly variance.")
    summary = (f"{pa['name']} projects for a weekly fantasy value of {va:.1f} and {pb['name']} for {vb:.1f}. "
               f"Head-to-head they split the categories {wins[pa['name']]}-{wins[pb['name']]}.")
    return ComparisonInsight(
        headline=(f"{pick} is the stronger play this week" if pick != "Toss-up" else "Too close to call this week"),
        overall_pick=pick, summary=summary, roster_fits=fits[:4], key_edges=edges, risks=risks[:3],
        confidence="high" if gap > 3 else "medium" if gap > 1 else "low",
    )


def ai_recommendation(comp: dict) -> AIResponse:
    payload = ai_payload(comp)
    return gemini.generate("compare", COMPARE_INSTRUCTIONS, payload, ComparisonInsight,
                           lambda: fallback_insight(payload))
