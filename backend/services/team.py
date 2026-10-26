"""Fantasy team analysis: category profile, needs and pickup recommendations.

Two bases:
  * "week"   -- projected totals for the selected week (games scheduled matter)
  * "season" -- per-game rates (rest-of-season talent, schedule-independent)

A team's strength in a category is the sum of its players' z-scores in that category.
Because z-scores are centred on the 156-player draftable pool, an average 12-team-league
roster sums to ~0, so the sum reads directly as "above/below an average team".
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from core.categories import CATEGORIES, RAW_STATS, with_percentages
from services.gemini_service import AIResponse, brief, gemini
from services.projections import Projection

Basis = Literal["week", "season"]
DEFAULT_ROSTERED = 156  # 12 teams x 13 players assumed rostered league-wide


def cols(basis: Basis) -> tuple[str, str]:
    """(z-score column prefix, raw stat prefix) for a basis."""
    return ("z_", "") if basis == "week" else ("pg_z_", "pg_")


def player_frame(proj: Projection, basis: Basis) -> pd.DataFrame:
    """Raw stats + category z-scores for every player under one basis (missing -> 0)."""
    zp, sp = cols(basis)
    df = pd.DataFrame(index=proj.players.index)
    for s in RAW_STATS:
        df[s] = proj.players[f"{sp}{s}"].fillna(0.0)
    for c in CATEGORIES:
        df[f"z_{c.key}"] = proj.players[f"{zp}{c.key}"].fillna(0.0)
    df["value"] = proj.players["value" if basis == "week" else "pg_value"].fillna(0.0)
    df["games"] = proj.players["games"]
    return df


def team_profile(proj: Projection, player_ids: list[int], basis: Basis = "week") -> dict:
    pf = player_frame(proj, basis)
    ids = [p for p in player_ids if p in pf.index]
    team = pf.loc[ids]
    n = len(team)
    params = proj.params if basis == "week" else proj.per_game_params
    totals = {s: float(team[s].sum()) for s in RAW_STATS}
    values = with_percentages(totals)
    threshold = 0.5 * math.sqrt(max(n, 1))
    cats = []
    for c in CATEGORIES:
        z = float(team[f"z_{c.key}"].sum())
        avg = params.pool_pct[c.key] if c.is_pct else params.means[c.key] * n
        cats.append({
            "key": c.key, "label": c.label, "name": c.name, "higher_is_better": c.higher_is_better,
            "value": values[c.key], "average_team": avg, "z": z,
            "status": "strong" if z >= threshold else "weak" if z <= -threshold else "average",
        })
    ranked = sorted(cats, key=lambda x: x["z"], reverse=True)
    return {
        "basis": basis,
        "players": int(n),
        "missing_player_ids": [p for p in player_ids if p not in pf.index],
        "totals": totals,
        "categories": cats,
        "strongest": [c["key"] for c in ranked[:3]],
        "weakest": [c["key"] for c in ranked[::-1][:3]],
        "total_value": float(team["value"].sum()),
        "games": int(team["games"].sum()),
        "status_threshold": threshold,
    }


def need_weights(profile: dict, punt: set[str] | None = None) -> dict[str, float]:
    """Category weights for roster decisions: weak categories count more, strong ones less,
    punted categories not at all (diminishing returns on categories you already win)."""
    punt = punt or set()
    scale = 1.5 * max(profile["status_threshold"], 1e-9)
    weights = {}
    for c in profile["categories"]:
        weights[c["key"]] = 0.0 if c["key"] in punt else float(np.clip(1.0 - c["z"] / scale, 0.25, 2.0))
    return weights


def weighted_scores(pf: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    return sum(pf[f"z_{k}"] * w for k, w in weights.items())


def free_agents(proj: Projection, basis: Basis, exclude: set[int], assume_rostered: int) -> pd.Index:
    """Players not on any saved roster and outside the top-N (assumed rostered league-wide)."""
    rank_col = "rank" if basis == "week" else "pg_rank"
    df = proj.players
    pool = df[(df[rank_col] > assume_rostered) & ~df.index.isin(list(exclude))]
    if basis == "week":
        pool = pool[pool["games"] > 0]
    return pool.index


def recommendations(proj: Projection, player_ids: list[int], basis: Basis, punt: set[str],
                    exclude: set[int], assume_rostered: int = DEFAULT_ROSTERED, limit: int = 10) -> list[dict]:
    profile = team_profile(proj, player_ids, basis)
    weights = need_weights(profile, punt)
    pf = player_frame(proj, basis)
    roster = [p for p in player_ids if p in pf.index]
    if not roster:
        return []
    scores = weighted_scores(pf, weights)
    drop = min(roster, key=lambda p: scores[p])
    fa = free_agents(proj, basis, exclude | set(player_ids), assume_rostered)
    best = scores.loc[fa].sort_values(ascending=False).head(limit)
    out = []
    for pid, score in best.items():
        deltas = {c.key: float(pf.at[pid, f"z_{c.key}"] - pf.at[drop, f"z_{c.key}"]) for c in CATEGORIES}
        helps = sorted((k for k in deltas if weights[k] > 0), key=lambda k: -deltas[k] * weights[k])[:3]
        r = proj.players.loc[pid]
        out.append({
            "player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"], "position": r["position"],
            "headshot": r["headshot"], "status": r["status"], "games": int(r["games"]),
            "fit_score": round(float(score), 3), "net_gain": round(float(score - scores[drop]), 3),
            "drop_player_id": int(drop), "drop_name": proj.players.at[drop, "name"],
            "helps": [k for k in helps if deltas[k] > 0], "category_deltas": {k: round(v, 2) for k, v in deltas.items()},
        })
    return out


def analyze(proj: Projection, player_ids: list[int], basis: Basis = "week", punt: set[str] | None = None,
            exclude: set[int] | None = None, assume_rostered: int = DEFAULT_ROSTERED) -> dict:
    punt = punt or set()
    profile = team_profile(proj, player_ids, basis)
    weights = need_weights(profile, punt)
    pf = player_frame(proj, basis)
    scores = weighted_scores(pf, weights)
    roster = []
    for pid in player_ids:
        if pid not in pf.index:
            continue
        r = proj.players.loc[pid]
        roster.append({
            "player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"], "position": r["position"],
            "headshot": r["headshot"], "status": r["status"], "games": int(r["games"]),
            "value": float(pf.at[pid, "value"]), "fit_score": float(scores[pid]),
            "z": {c.key: float(pf.at[pid, f"z_{c.key}"]) for c in CATEGORIES},
            "stats": {s: float(pf.at[pid, s]) for s in RAW_STATS},
        })
    return {
        "window": proj.window.as_dict(),
        "profile": profile,
        "weights": weights,
        "punt": sorted(punt),
        "roster": sorted(roster, key=lambda x: -x["value"]),
        "recommendations": recommendations(proj, player_ids, basis, punt, exclude or set(), assume_rostered),
        "assume_rostered": assume_rostered,
    }


# --------------------------------------------------------------------------- Gemini
class TeamMove(BaseModel):
    action: str = brief("Move, e.g. 'Add X, drop Y'", words=8)
    reason: str = brief("Why, with one number", words=12)


class TeamInsight(BaseModel):
    headline: str = brief("Roster verdict", words=10)
    assessment: str = brief("Category profile in one line", words=30)
    strengths: list[str] = brief("Strongest categories, e.g. 'BLK: far above average'", words=8, items=3)
    weaknesses: list[str] = brief("Weakest categories, e.g. 'FT%: 76.8% vs 80.1% avg'", words=8, items=3)
    moves: list[TeamMove] = brief("Recommended moves using ONLY the listed candidate players", items=3)
    strategy: str = brief("Category strategy, e.g. whether to punt", words=20)

TEAM_INSTRUCTIONS = """Analyze this fantasy basketball roster for a head-to-head 9-category league.
Explain its strongest and weakest categories, shooting efficiency and turnovers, and recommend
improvements. Only recommend pickups from 'candidate_pickups' and only drops from the roster.
Category z-sums near 0 mean average versus a typical 12-team-league roster; positive is better
(turnover z is already inverted, so positive TO z means FEWER turnovers)."""


def ai_payload(result: dict) -> dict:
    prof = result["profile"]
    return {
        "basis": "projected week " + result["window"]["label"] if prof["basis"] == "week" else "per-game rates (rest of season)",
        "roster_size": prof["players"],
        "punted_categories": result["punt"],
        "categories": [{"category": c["label"], "team_value": _r(c["value"], 3 if c["key"].endswith("pct") else 1),
                        "average_team_value": _r(c["average_team"], 3 if c["key"].endswith("pct") else 1),
                        "team_z_sum": _r(c["z"]), "status": c["status"]} for c in prof["categories"]],
        "roster": [{"name": p["name"], "team": p["team_abbr"], "status": p["status"], "games": p["games"],
                    "value": _r(p["value"]), "need_fit_score": _r(p["fit_score"])} for p in result["roster"]],
        "candidate_pickups": [{"name": r["name"], "team": r["team_abbr"], "games": r["games"],
                               "net_gain_vs_dropping": _r(r["net_gain"]), "suggested_drop": r["drop_name"],
                               "helps_categories": [_label(k) for k in r["helps"]]}
                              for r in result["recommendations"][:6]],
    }


def _r(v, nd: int = 2):
    return None if v is None else round(float(v), nd)


def _label(key: str) -> str:
    return next(c.label for c in CATEGORIES if c.key == key)


def fallback_insight(payload: dict) -> TeamInsight:
    cats = sorted(payload["categories"], key=lambda c: c["team_z_sum"] or 0, reverse=True)
    strong = [c for c in cats if c["status"] == "strong"] or cats[:2]
    weak = [c for c in cats[::-1] if c["status"] == "weak"] or cats[::-1][:2]
    fmt = lambda c: f"{c['category']}: {c['team_value']} vs {c['average_team_value']} avg"  # noqa: E731
    moves = [TeamMove(action=f"Add {p['name']}, drop {p['suggested_drop']}",
                      reason=f"Net need-weighted gain of {p['net_gain_vs_dropping']:+.2f}, mainly in "
                             f"{', '.join(p['helps_categories']) or 'overall value'}.")
             for p in payload["candidate_pickups"][:3] if (p["net_gain_vs_dropping"] or 0) > 0]
    if not moves:
        moves = [TeamMove(action="Hold", reason="No listed free agent improves the need-weighted score over your weakest-fit player.")]
    weak_labels = [c["category"] for c in weak[:2]]
    n_strong = sum(1 for c in cats if (c["team_z_sum"] or 0) > 0)
    worst = cats[-1]
    strategy = (f"Projected above average in {n_strong} of 9 categories; "
                + (f"{worst['category']} is far below average, so punting it and reinforcing the rest is viable."
                   if (worst["team_z_sum"] or 0) < -3 else
                   f"focus pickups on {' and '.join(weak_labels)} rather than punting."))
    return TeamInsight(
        headline=f"Strong in {strong[0]['category']}, needs help in {weak[0]['category']}",
        assessment=f"With {payload['roster_size']} players the roster beats an average team in {n_strong} of 9 categories. "
                   f"Biggest edge: {strong[0]['category']}; biggest hole: {weak[0]['category']}.",
        strengths=[fmt(c) for c in strong[:3]], weaknesses=[fmt(c) for c in weak[:3]], moves=moves, strategy=strategy,
    )


def ai_insight(result: dict) -> AIResponse:
    payload = ai_payload(result)
    return gemini.generate("team", TEAM_INSTRUCTIONS, payload, TeamInsight, lambda: fallback_insight(payload))
