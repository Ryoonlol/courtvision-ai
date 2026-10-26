"""Explainable breakout detector.

For each player, compare the most recent ``RECENT`` games with the ``BASELINE`` games before them:

  minutes        Δ minutes per game
  shot volume    Δ field-goal attempts per game
  usage          Δ usage proxy per 36 min: (FGA + 0.44·FTA + TOV) / MIN · 36
  production     Δ per-game 9-category value (z-scores vs. the league's recent per-game pool)
  defense        Δ (STL + BLK) per 36 min

Each delta is standardised across eligible players, then combined with fixed, published weights:
  score = 0.30·minutes + 0.20·usage + 0.15·shots + 0.25·production + 0.10·defense
The score is relative: it ranks who is trending up most, it is not a probability.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from core.categories import RAW_STATS
from data import repository as repo
from data.ingest import season_label
from services import valuation
from services.gemini_service import AIResponse, brief, gemini

RECENT = 5
BASELINE = 25
MIN_BASELINE = 10
MIN_RECENT_MIN = 12.0
WEIGHTS = {"minutes": 0.30, "usage": 0.20, "shots": 0.15, "production": 0.25, "defense": 0.10}
STATS = ["min", *RAW_STATS]


def _windows(box: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    box = box.sort_values(["player_id", "date"])
    pos_from_end = box.groupby("player_id").cumcount(ascending=False)
    recent = box[pos_from_end < RECENT]
    base = box[(pos_from_end >= RECENT) & (pos_from_end < RECENT + BASELINE)]
    meta = recent.groupby("player_id").agg(last_date=("date", "max"), recent_season=("season", "max"),
                                           first_recent=("date", "min"), recent_games=("game_id", "size"))
    meta["base_season"] = base.groupby("player_id")["season"].max()
    meta["base_games"] = base.groupby("player_id").size()
    return recent, base, meta


def _usage36(df: pd.DataFrame) -> pd.Series:
    return (df["fga"] + 0.44 * df["fta"] + df["tov"]) / df["min"].clip(lower=1) * 36


def detect(as_of: date | None = None, limit: int = 25, min_recent_min: float = MIN_RECENT_MIN,
           active_days: int = 45) -> dict:
    box = repo.box_scores()
    if as_of:
        box = box[box["date"] <= pd.Timestamp(as_of)]
    ref = box["date"].max()
    recent, base, meta = _windows(box)
    meta = meta[(meta["base_games"] >= MIN_BASELINE) & (meta["recent_games"] == RECENT)
                & (meta["last_date"] >= ref - pd.Timedelta(days=active_days))]
    ids = meta.index
    r_avg = recent[recent["player_id"].isin(ids)].groupby("player_id")[STATS].mean()
    b_avg = base[base["player_id"].isin(ids)].groupby("player_id")[STATS].mean()
    r_avg, b_avg = r_avg.loc[ids], b_avg.loc[ids]
    keep = r_avg["min"] >= min_recent_min
    r_avg, b_avg, meta = r_avg[keep], b_avg[keep], meta[keep]
    if r_avg.empty:
        return {"as_of": ref.date().isoformat(), "candidates": [], "eligible": 0, "weights": WEIGHTS}

    params = valuation.fit(pd.concat([r_avg, b_avg])[RAW_STATS])
    r_val = valuation.score(r_avg[RAW_STATS], params)["value"]
    b_val = valuation.score(b_avg[RAW_STATS], params)["value"]
    deltas = pd.DataFrame({
        "minutes": r_avg["min"] - b_avg["min"],
        "shots": r_avg["fga"] - b_avg["fga"],
        "usage": _usage36(r_avg) - _usage36(b_avg),
        "production": r_val - b_val,
        "defense": (r_avg["stl"] + r_avg["blk"]) / r_avg["min"] * 36 - (b_avg["stl"] + b_avg["blk"]) / b_avg["min"].clip(lower=1) * 36,
    })
    z = (deltas - deltas.mean()) / deltas.std(ddof=0).replace(0, 1)
    score = sum(z[k] * w for k, w in WEIGHTS.items())
    order = score.sort_values(ascending=False).index[:limit]
    players, teams = repo.players(), repo.teams()
    out = []
    for pid in order:
        p = players.loc[pid] if pid in players.index else None
        signals = []
        if deltas.at[pid, "minutes"] >= 4:
            signals.append(f"+{deltas.at[pid, 'minutes']:.1f} min/game")
        if deltas.at[pid, "usage"] >= 3:
            signals.append(f"usage +{deltas.at[pid, 'usage']:.1f} per 36")
        if deltas.at[pid, "shots"] >= 3:
            signals.append(f"+{deltas.at[pid, 'shots']:.1f} FGA/game")
        if deltas.at[pid, "production"] >= 1:
            signals.append(f"fantasy value +{deltas.at[pid, 'production']:.1f}")
        if deltas.at[pid, "defense"] >= 0.8:
            signals.append(f"stocks +{deltas.at[pid, 'defense']:.1f} per 36")
        m = meta.loc[pid]
        out.append({
            "player_id": int(pid), "name": p["name"] if p is not None else str(pid),
            "team_abbr": p["team_abbr"] if p is not None else None,
            "team_logo": teams.at[p["team_id"], "logo"] if p is not None and p["team_id"] in teams.index else None,
            "position": p["position"] if p is not None else None, "headshot": p["headshot"] if p is not None else None,
            "score": float(score[pid]),
            "components": {k: float(z.at[pid, k] * WEIGHTS[k]) for k in WEIGHTS},
            "deltas": {k: float(v) for k, v in deltas.loc[pid].items()},
            "recent": {s: round(float(r_avg.at[pid, s]), 2) for s in STATS} | {"value": round(float(r_val[pid]), 2)},
            "baseline": {s: round(float(b_avg.at[pid, s]), 2) for s in STATS} | {"value": round(float(b_val[pid]), 2)},
            "signals": signals,
            "last_game": m["last_date"].date().isoformat(),
            "spans_seasons": bool(m["recent_season"] != m["base_season"]),
            "recent_window": f"{m['first_recent']:%b %-d} – {m['last_date']:%b %-d}",
            "baseline_season": season_label(int(m["base_season"])),
        })
    return {"as_of": ref.date().isoformat(), "eligible": int(len(score)), "weights": WEIGHTS,
            "recent_games": RECENT, "baseline_games": BASELINE, "candidates": out}


# --------------------------------------------------------------------------- Gemini
class BreakoutNote(BaseModel):
    player: str
    why: str = brief("The measured change, e.g. 'Minutes 10 -> 27, FGA 3 -> 12'", words=16)
    sustainability: str = brief("Sustainable? e.g. 'Minutes-driven: likely sticks'", words=10)


class BreakoutInsight(BaseModel):
    headline: str = brief("Headline", words=10)
    overview: str = brief("Common pattern among the risers", words=25)
    players: list[BreakoutNote] = brief("One note per listed player", items=6)
    caution: str = brief("Sample-size caveat", words=15)

BREAKOUT_INSTRUCTIONS = """Explain why these NBA players may be breaking out for fantasy basketball, using ONLY the
measured changes between their recent games and their baseline games (minutes, shot attempts, usage per 36,
9-category value, steals+blocks per 36). You have no news, injury or role information beyond these numbers:
do not speculate about specific causes such as trades or teammate injuries; describe the measured changes."""


def ai_payload(res: dict, top: int = 6) -> dict:
    return {
        "as_of": res["as_of"], "recent_games": res["recent_games"], "baseline_games": res["baseline_games"],
        "players": [{
            "name": c["name"], "team": c["team_abbr"], "breakout_score": round(c["score"], 2),
            "recent_window": c["recent_window"], "spans_offseason": c["spans_seasons"],
            "minutes": [c["baseline"]["min"], c["recent"]["min"]],
            "fga": [c["baseline"]["fga"], c["recent"]["fga"]],
            "usage_per36_change": round(c["deltas"]["usage"], 1),
            "value_per_game": [c["baseline"]["value"], c["recent"]["value"]],
            "pts": [c["baseline"]["pts"], c["recent"]["pts"]],
            "stocks_per36_change": round(c["deltas"]["defense"], 1),
        } for c in res["candidates"][:top]],
        "note": "pairs are [baseline, recent]",
    }


def fallback_insight(payload: dict) -> BreakoutInsight:
    notes = []
    for p in payload["players"]:
        mins, val = p["minutes"], p["value_per_game"]
        driver = "minutes" if mins[1] - mins[0] >= 4 else "usage" if p["usage_per36_change"] >= 3 else "efficiency"
        notes.append(BreakoutNote(
            player=p["name"],
            why=(f"Minutes {mins[0]} -> {mins[1]}, FGA {p['fga'][0]} -> {p['fga'][1]}, "
                 f"per-game fantasy value {val[0]} -> {val[1]}."),
            sustainability=("Driven by more playing time, which tends to be stickier than shooting variance."
                            if driver == "minutes" else
                            "Driven by a bigger offensive role (usage)." if driver == "usage" else
                            "Mostly per-minute production; watch whether efficiency holds."),
        ))
    spans = sum(1 for p in payload["players"] if p["spans_offseason"])
    return BreakoutInsight(
        headline="Players trending up over their last 5 games",
        overview=f"{len(notes)} risers ranked by a weighted mix of minutes, usage, shot volume, production and defense changes.",
        players=notes,
        caution=(f"Five-game windows are noisy; {spans} of these windows span the offseason." if spans
                 else "Five-game windows are noisy; confirm with the next few games."),
    )


def ai_insight(res: dict) -> AIResponse:
    payload = ai_payload(res)
    return gemini.generate("breakouts", BREAKOUT_INSTRUCTIONS, payload, BreakoutInsight, lambda: fallback_insight(payload))
