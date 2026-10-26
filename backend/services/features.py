"""Leakage-free feature construction shared by the baseline projection, the ML model
training set and live projections.

Every feature for a player-game row is computed only from games strictly before
that row. Live projections reuse the exact same code by appending one
"placeholder" row per player dated at the start of the projection window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.categories import MODEL_STATS

# Baseline weighted-average blend (explainable model).
W_SEASON, W_L10, W_L5 = 0.5, 0.3, 0.2
K_PRIOR = 10.0     # games of prior-season "credibility" blended into the current-season average
K_TEAM = 10.0      # games of shrinkage toward league average for opponent factors
OPP_DAMPEN = 0.5   # only half of the (shrunk) opponent effect is applied
OPP_CLIP = (0.85, 1.15)

STATS = MODEL_STATS
KEY_COLS = ["player_id", "game_id", "date", "season", "team_id", "opp_team_id", "home"]


def player_features(box: pd.DataFrame, placeholders: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-row pre-game player state.

    ``placeholders`` (optional) has KEY_COLS without stats; each placeholder must be dated
    after all of that player's real games. Returned frame has a boolean ``placeholder`` column.
    """
    real = box[KEY_COLS + STATS].copy()
    real["placeholder"] = False
    frames = [real]
    if placeholders is not None and len(placeholders):
        ph = placeholders[KEY_COLS].copy()
        for s in STATS:
            ph[s] = np.nan
        ph["placeholder"] = True
        frames.append(ph)
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["player_id", "date", "placeholder", "game_id"], kind="mergesort").reset_index(drop=True)

    is_real = (~df["placeholder"]).astype(float)
    vals = df[STATS].fillna(0.0)

    # --- current-season average before this game
    keys = [df["player_id"], df["season"]]
    cum = vals.groupby(keys).cumsum() - vals
    cur_n = is_real.groupby(keys).cumsum() - is_real
    cur = cum.div(cur_n.replace(0, np.nan), axis=0)

    # --- prior average: games-weighted over the previous two seasons
    season_sum = box.groupby(["player_id", "season"])[STATS].sum()
    season_sum["n"] = box.groupby(["player_id", "season"]).size()
    lag1 = season_sum.reset_index().assign(season=lambda t: t["season"] + 1)
    lag2 = season_sum.reset_index().assign(season=lambda t: t["season"] + 2)
    prior = pd.concat([lag1, lag2]).groupby(["player_id", "season"])[[*STATS, "n"]].sum()
    prior[STATS] = prior[STATS].div(prior["n"], axis=0)
    prev = df[["player_id", "season"]].merge(prior.reset_index(), on=["player_id", "season"], how="left")
    prev_n = prev["n"].fillna(0.0).to_numpy()
    prev_vals = prev[STATS]

    # --- recent form: last 5 / last 10 games played (across seasons)
    shifted = df.groupby("player_id")[STATS].shift(1)  # placeholder stats are NaN, so they never leak
    roll = shifted.groupby(df["player_id"])
    l5 = roll.rolling(5, min_periods=1).mean().reset_index(level=0, drop=True).sort_index()
    l10 = roll.rolling(10, min_periods=1).mean().reset_index(level=0, drop=True).sort_index()

    out = df[KEY_COLS + ["placeholder"]].copy()
    out["cur_n"] = cur_n.to_numpy()
    out["prev_n"] = prev_n
    n = out["cur_n"].to_numpy()[:, None]
    k = K_PRIOR * np.minimum(1.0, prev_n / 20.0)[:, None]
    cur_a, prev_a = cur.to_numpy(), prev_vals.to_numpy()
    has_cur, has_prev = n > 0, ~np.isnan(prev_a) & (k > 0)
    blend = np.where(has_cur & has_prev, (n * np.nan_to_num(cur_a) + k * np.nan_to_num(prev_a)) / (n + k + 1e-12),
                     np.where(has_cur, cur_a, prev_a))
    l5a, l10a = l5.to_numpy(), l10.to_numpy()
    # Weighted average; missing components drop out and the remaining weights are renormalised.
    comps = [(blend, W_SEASON), (l10a, W_L10), (l5a, W_L5)]
    num = sum(np.nan_to_num(c) * w for c, w in comps)
    den = sum((~np.isnan(c)) * w for c, w in comps)
    base = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)

    cols = {}
    for i, s in enumerate(STATS):
        cols[f"cur_{s}"] = cur_a[:, i]
        cols[f"prev_{s}"] = prev_a[:, i]
        cols[f"blend_{s}"] = blend[:, i]
        cols[f"l5_{s}"] = l5a[:, i]
        cols[f"l10_{s}"] = l10a[:, i]
        cols[f"base_{s}"] = base[:, i]
        cols[f"actual_{s}"] = df[s].to_numpy()
    out = pd.concat([out, pd.DataFrame(cols, index=out.index)], axis=1)
    return out


def team_factors(box: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Opponent strength factors per stat.

    Returns (asof, current):
      asof    -- one row per (team_id, game_id): factor using only that team's earlier games
      current -- one row per team: factor using all games of its latest season
    A factor of 1.10 for "pts" means opponents score 10% more than league average against
    the team (after shrinkage and dampening).
    """
    stats = [s for s in STATS if s != "min"]
    allowed = (box.groupby(["opp_team_id", "game_id", "date", "season"])[stats].sum()
               .reset_index().rename(columns={"opp_team_id": "team_id"})
               .sort_values(["date", "game_id"]).reset_index(drop=True))

    # league average per team-game, using only earlier dates within the season
    daily = allowed.groupby(["season", "date"])[stats].agg(["sum", "count"])
    sums = daily.xs("sum", axis=1, level=1).groupby(level="season").cumsum()
    counts = daily.xs("count", axis=1, level=1).groupby(level="season").cumsum()
    league_cum = (sums / counts).groupby(level="season").shift(1)
    league_cum = league_cum.reset_index()
    asof = allowed[["team_id", "game_id", "date", "season"]].merge(league_cum, on=["season", "date"], how="left")

    grp = allowed.groupby(["team_id", "season"])
    team_n = grp.cumcount().to_numpy().astype(float)
    team_prev_avg = (grp[stats].cumsum() - allowed[stats]).div(np.where(team_n > 0, team_n, np.nan), axis=0)
    for s in stats:
        raw = team_prev_avg[s].to_numpy() / asof[s].to_numpy()
        asof[f"opp_{s}"] = _shrink(raw, team_n)
    asof = asof[["team_id", "game_id"] + [f"opp_{s}" for s in stats]]

    latest = allowed["season"].max() if len(allowed) else None
    cur = allowed[allowed["season"] == latest]
    league = cur[stats].mean()
    tgrp = cur.groupby("team_id")
    current = pd.DataFrame({"team_id": list(tgrp.groups.keys())})
    n = tgrp.size().to_numpy().astype(float)
    tmean = tgrp[stats].mean()
    for s in stats:
        current[f"opp_{s}"] = _shrink(tmean[s].to_numpy() / league[s], n)
    current["games"] = n
    return asof, current


def _shrink(raw: np.ndarray, n: np.ndarray) -> np.ndarray:
    raw = np.where(np.isfinite(raw), raw, 1.0)
    shrunk = (n * raw + K_TEAM * 1.0) / (n + K_TEAM)
    return np.clip(1.0 + OPP_DAMPEN * (shrunk - 1.0), *OPP_CLIP)


def team_rest(games: pd.DataFrame) -> pd.DataFrame:
    """Days since each team's previous game (capped at 4) for every scheduled/played game."""
    rows = pd.concat([
        pd.DataFrame({"team_id": games["home_team_id"], "game_id": games["id"], "date": games["date"]}),
        pd.DataFrame({"team_id": games["away_team_id"], "game_id": games["id"], "date": games["date"]}),
    ]).sort_values(["team_id", "date"])
    rows["rest"] = rows.groupby("team_id")["date"].diff().dt.days.clip(upper=4).fillna(4)
    return rows[["team_id", "game_id", "rest"]]


def baseline_prediction(feat: pd.DataFrame, stat: str) -> np.ndarray:
    """Explainable baseline: weighted season/L10/L5 average times the opponent factor."""
    base = feat[f"base_{stat}"].to_numpy(dtype=float)
    if stat == "min" or f"opp_{stat}" not in feat:
        return base
    return base * feat[f"opp_{stat}"].fillna(1.0).to_numpy(dtype=float)


def model_feature_columns(stat: str) -> list[str]:
    cols = [f"base_{stat}", f"blend_{stat}", f"cur_{stat}", f"prev_{stat}", f"l5_{stat}", f"l10_{stat}",
            "base_min", "l5_min", "cur_n", "prev_n", "home", "rest"]
    if stat != "min":
        cols += [f"opp_{stat}", "opp_pts"]
    return list(dict.fromkeys(cols))
