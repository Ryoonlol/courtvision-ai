"""Weekly streaming optimizer.

A streamer only helps on days you have an open active-lineup slot. For every day in the window we
count how many of your rostered players are expected to play (sum of availability) versus the number
of active slots; a candidate's game on a day with an open slot is "usable". (Positional eligibility
is not modelled -- slots are treated as generic.)

Stream value = need-weighted team z-sum gained from the candidate's usable games:
  counting stats  ->  added total / pool SD of weekly totals (turnovers subtract),
  FG% / FT%       ->  (makes - pool% x attempts) / pool SD of impact,
using the same scale as the team analyzer, so values are comparable with its category z-sums.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.categories import CATEGORIES
from services.projections import Projection
from services.team import DEFAULT_ROSTERED, free_agents, need_weights, player_frame, team_profile, weighted_scores

DEFAULT_SLOTS = 10


def daily_usage(proj: Projection, roster: list[int], slots: int) -> pd.DataFrame:
    days = pd.date_range(proj.window.start, proj.window.end, freq="D")
    g = proj.games
    mine = g[g["player_id"].isin(roster)].groupby("date")["avail"].sum()
    league = g.drop_duplicates("game_id").groupby("date").size()
    out = pd.DataFrame(index=days)
    out["my_players"] = mine.reindex(days).fillna(0.0)
    out["league_games"] = league.reindex(days).fillna(0).astype(int)
    out["open_slots"] = np.clip(slots - out["my_players"], 0, None)
    # fraction of a streamer's game that lands in the lineup (partial when < 1 slot is open)
    out["usable"] = np.clip(out["open_slots"], 0, 1)
    return out


def _gain_vector(proj: Projection, rows: pd.DataFrame, weight: pd.Series, weights: dict[str, float]) -> dict:
    """Need-weighted z gain of adding these player-games (each row weighted by usability x availability)."""
    w = (weight * rows["avail"]).to_numpy()
    tot = {s: float((rows[f"p_{s}"].to_numpy() * w).sum()) for s in
           ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fgm", "fga", "ftm", "fta"]}
    p = proj.params
    per_cat = {}
    for c in CATEGORIES:
        if c.is_pct:
            impact = tot[c.makes] - p.pool_pct[c.key] * tot[c.attempts]
            per_cat[c.key] = impact / p.sds[c.key]
        else:
            per_cat[c.key] = (tot[c.key] / p.sds[c.key]) * (1 if c.higher_is_better else -1)
    value = sum(per_cat[k] * weights[k] for k in per_cat)
    return {"value": value, "per_cat": per_cat, "totals": tot}


def optimize(proj: Projection, roster: list[int], slots: int = DEFAULT_SLOTS, available: list[int] | None = None,
             exclude: set[int] | None = None, punt: list[str] | None = None,
             assume_rostered: int = DEFAULT_ROSTERED, limit: int = 15) -> dict:
    usage = daily_usage(proj, roster, slots)
    profile = team_profile(proj, roster, "week")
    weights = need_weights(profile, set(punt or []))
    if available:
        pool = pd.Index([p for p in available if p in proj.players.index and p not in roster])
        mode = "custom"
    else:
        pool = free_agents(proj, "week", (exclude or set()) | set(roster), assume_rostered)
        mode = "auto"
    g = proj.games[proj.games["player_id"].isin(pool)]
    usable = g["date"].map(usage["usable"]).fillna(0.0)
    results = []
    for pid, rows in g.groupby("player_id"):
        gain = _gain_vector(proj, rows, usable.loc[rows.index], weights)
        r = proj.players.loc[pid]
        days = [{"date": d.date().isoformat(), "weekday": d.strftime("%a"),
                 "usable": float(usage.at[d, "usable"]), "availability": float(a)}
                for d, a in zip(rows["date"], rows["avail"])]
        helps = sorted((k for k in gain["per_cat"] if weights[k] > 0), key=lambda k: -gain["per_cat"][k] * weights[k])[:3]
        results.append({
            "player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"], "position": r["position"],
            "headshot": r["headshot"], "status": r["status"],
            "games": int(len(rows)), "usable_games": float((usable.loc[rows.index] * rows["avail"]).sum()),
            "proj_min": float(rows["p_min"].mean()), "stream_value": float(gain["value"]),
            "per_game_value": float(proj.players.at[pid, "pg_value"]),
            "helps": [k for k in helps if gain["per_cat"][k] > 0],
            "category_gain": {k: round(v, 3) for k, v in gain["per_cat"].items()},
            "projected_totals": {k: round(v, 1) for k, v in gain["totals"].items()},
            "days": days,
        })
    results.sort(key=lambda x: x["stream_value"], reverse=True)

    pf = player_frame(proj, "week")
    scores = weighted_scores(pf, weights)
    in_roster = [p for p in roster if p in pf.index]
    drop = min(in_roster, key=lambda p: scores[p]) if in_roster else None
    return {
        "window": proj.window.as_dict(),
        "slots": slots, "mode": mode, "pool_size": int(len(pool)),
        "weights": weights,
        "days": [{"date": d.date().isoformat(), "weekday": d.strftime("%a"), "league_games": int(r["league_games"]),
                  "my_players": round(float(r["my_players"]), 2), "open_slots": round(float(r["open_slots"]), 2),
                  "usable": float(r["usable"])} for d, r in usage.iterrows()],
        "drop_candidate": None if drop is None else {"player_id": int(drop), "name": proj.players.at[drop, "name"],
                                                     "games": int(proj.players.at[drop, "games"])},
        "candidates": results[:limit],
    }
