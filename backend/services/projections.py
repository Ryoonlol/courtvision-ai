"""League-wide weekly projections.

Pipeline for a window (e.g. next Mon-Sun):
 1. Pre-game state for every player (season blend, L10, L5, minutes...) from features.py.
 2. One row per (player, unplayed team game) with opponent factors and rest days.
 3. Per-game predictions per stat: the trained model where it beat the baseline on
    chronological validation, otherwise the explainable weighted-average baseline.
 4. Availability from the injury report scales each game (expected games played).
 5. Per-game SD = player-specific historical SD shrunk toward the model's residual SD;
    weekly variance includes availability uncertainty.
 6. 9-category z-score valuation of weekly totals + an 80% interval of that value.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from core.categories import CATEGORIES, MODEL_STATS, RAW_STATS
from core.db import get_conn
from data import repository as repo
from data.ingest import CURRENT_SEASON
from services import ml_model, valuation
from services.features import KEY_COLS, player_features, team_factors, team_rest
from services.schedule import Window, today, upcoming_team_games

Z80 = 1.2816
K_SD = 10.0          # games of shrinkage of a player's own SD toward the model residual SD
SD_HISTORY = 30      # games used for the player-specific SD

_cache: dict[tuple, "Projection"] = {}
MAX_CACHED = 6
_lock = threading.Lock()


@dataclass
class Projection:
    window: Window
    players: pd.DataFrame        # one row per player: weekly totals, SDs, z-scores, value...
    games: pd.DataFrame          # one row per (player, game) with per-game predictions
    params: valuation.ValuationParams
    per_game_params: valuation.ValuationParams
    methods: dict[str, str]


# ----------------------------------------------------------------------------- availability
def availability(inj: dict | None, game_date: date, last_played: date | None, ref: date) -> tuple[float, str]:
    """Probability a player suits up for a given game, from the injury report."""
    if not inj:
        return 1.0, "Active"
    reported = _parse_date(inj.get("reported_at"))
    if last_played and reported and last_played > reported:
        return 1.0, "Active (played since report)"
    status = (inj.get("status") or "").lower()
    fantasy = (inj.get("fantasy_status") or "").upper()
    ret = _parse_date(inj.get("return_date"))
    if "susp" in status:
        return 0.0, "Suspended"
    if status == "out" or fantasy in {"OUT", "O"}:
        if ret and game_date >= ret:
            return 0.6, f"Out · est. return {ret:%b %-d}"
        return 0.0, "Out" + (f" · est. return {ret:%b %-d}" if ret else "")
    if fantasy == "GTD" or "day-to-day" in status or "questionable" in status:
        days_out = (game_date - ref).days
        return (0.6 if days_out <= 2 else 0.85), "Day-to-day"
    return 0.9, inj.get("status") or "Listed"


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


# ----------------------------------------------------------------------------- pool
def player_pool(box: pd.DataFrame) -> pd.Index:
    """Players who have played this season, plus injured regulars from last season."""
    cur = box.loc[box["season"] == CURRENT_SEASON, "player_id"].unique()
    prev = box[box["season"] == CURRENT_SEASON - 1].groupby("player_id").size()
    injured = repo.injuries().index
    regulars = prev[prev >= 20].index.intersection(injured)
    return pd.Index(np.union1d(cur, regulars))


# ----------------------------------------------------------------------------- core
def project(window: Window) -> Projection:
    key = (window.start, window.end, repo.data_version(), (ml_model.summary() or {}).get("trained_at"))
    with _lock:
        if key in _cache:
            return _cache[key]
    proj = _project(window)
    with _lock:
        _cache[key] = proj
        while len(_cache) > MAX_CACHED:  # keep the most recent windows (today, tomorrow, weeks)
            _cache.pop(next(iter(_cache)))
    _log_projection(proj)
    return proj


def _project(window: Window) -> Projection:
    box, games, players = repo.box_scores(), repo.games(), repo.players()
    pool = player_pool(box)
    pool = pool[pool.isin(players.index)]
    pinfo = players.loc[pool]

    # 1. pre-game state: one placeholder per player dated at the window start
    last_date = box.groupby("player_id")["date"].max()
    ph_date = pd.Timestamp(window.start)
    ph = pd.DataFrame({
        "player_id": pool, "game_id": -1, "season": CURRENT_SEASON,
        "team_id": pinfo["team_id"].to_numpy(), "opp_team_id": -1, "home": 0,
        "date": [max(ph_date, last_date.get(p, ph_date)) for p in pool],
    })
    state = player_features(box[box["player_id"].isin(pool)], ph)
    state = state[state["placeholder"]].drop(columns=["game_id", "opp_team_id", "home", "date", "season"])

    # 2. expand to scheduled games
    sched = upcoming_team_games(window)
    rows = state.merge(sched[["team_id", "opp_team_id", "game_id", "date", "home"]], on="team_id", how="inner")
    _, current = team_factors(box)
    rows = rows.merge(current.drop(columns="games").rename(columns={"team_id": "opp_team_id"}),
                      on="opp_team_id", how="left")
    rows = rows.merge(team_rest(games), on=["team_id", "game_id"], how="left")
    rows["rest"] = rows["rest"].fillna(2)
    opp_cols = [c for c in rows.columns if c.startswith("opp_") and c != "opp_team_id"]
    rows[opp_cols] = rows[opp_cols].fillna(1.0)
    rows = rows[rows["base_min"].notna()].reset_index(drop=True)

    # 3. per-game predictions
    preds, methods = ml_model.predict_all(rows)
    rows = pd.concat([rows, pd.DataFrame({f"p_{s}": v for s, v in preds.items()}, index=rows.index)], axis=1)

    # 4. availability
    inj = repo.injuries()
    ref = today()
    avail, notes = [], []
    for pid, gdate in zip(rows["player_id"], rows["date"]):
        info = inj.loc[pid].to_dict() if pid in inj.index else None
        lp = last_date.get(pid)
        a, note = availability(info, gdate.date(), lp.date() if lp is not None else None, ref)
        avail.append(a)
        notes.append(note)
    rows = rows.assign(avail=avail, avail_note=notes)

    # 5. per-game SD
    hist = box[box["player_id"].isin(pool)].groupby("player_id").tail(SD_HISTORY)
    p_sd = hist.groupby("player_id")[MODEL_STATS].std()
    p_n = hist.groupby("player_id").size()
    n = rows["player_id"].map(p_n).fillna(0).to_numpy()
    sd_cols = {}
    for stat in MODEL_STATS:
        model_sd = ml_model.residual_sd(stat, rows[f"p_{stat}"].to_numpy())
        own = rows["player_id"].map(p_sd[stat]).to_numpy(dtype=float)
        own = np.where(np.isnan(own), model_sd, own)
        sd_cols[f"sd_{stat}"] = np.sqrt((n * own ** 2 + K_SD * model_sd ** 2) / (n + K_SD))
    rows = pd.concat([rows, pd.DataFrame(sd_cols, index=rows.index)], axis=1)

    # 6. weekly aggregation
    a = rows["avail"].to_numpy()
    agg = {"games": ("game_id", "size"), "exp_games": ("avail", "sum")}
    weekly = rows.assign(**{f"w_{s}": rows[f"p_{s}"] * a for s in MODEL_STATS},
                         **{f"v_{s}": a * rows[f"sd_{s}"] ** 2 + a * (1 - a) * rows[f"p_{s}"] ** 2
                            for s in MODEL_STATS})
    for s in MODEL_STATS:
        agg[s] = (f"w_{s}", "sum")
        agg[f"var_{s}"] = (f"v_{s}", "sum")
    wk = weekly.groupby("player_id").agg(**agg)
    for s in MODEL_STATS:
        wk[f"sd_{s}"] = np.sqrt(wk.pop(f"var_{s}"))
    # players with no remaining games still appear (0 games) so they are searchable
    wk = wk.reindex(pool, fill_value=0.0)
    wk["games"] = wk["games"].astype(int)

    params = valuation.fit(wk[RAW_STATS])
    z = valuation.score(wk[RAW_STATS], params)
    lo, hi = valuation.value_interval(wk[RAW_STATS], wk[[f"sd_{s}" for s in RAW_STATS]]
                                      .rename(columns=lambda c: c[3:]), params)
    out = pd.concat([wk, z], axis=1)
    out["value_lo"], out["value_hi"] = lo, hi

    # per-game (rate) valuation, used for comparing players independent of schedule
    state_idx = state.set_index("player_id")
    per_game = pd.DataFrame({s: state_idx[f"base_{s}"] for s in RAW_STATS}).reindex(pool).fillna(0.0)
    pg_params = valuation.fit(per_game)
    pg_z = valuation.score(per_game, pg_params).add_prefix("pg_")
    out = out.join(pg_z)
    for s in MODEL_STATS:
        out[f"pg_{s}"] = state_idx[f"base_{s}"].reindex(pool)

    for c in CATEGORIES:
        if c.is_pct:
            out[c.key] = np.where(out[c.attempts] > 0, out[c.makes] / out[c.attempts].replace(0, np.nan), np.nan)
            p = np.clip(out[c.key].fillna(0).to_numpy(), 0, 1)
            out[f"sd_{c.key}"] = np.sqrt(p * (1 - p) / np.maximum(out[c.attempts].to_numpy(), 1))
    teams = repo.teams()
    out["name"] = pinfo["name"]
    out["team_abbr"] = pinfo["team_abbr"]
    out["team_logo"] = pinfo["team_id"].map(teams["logo"])
    out["position"] = pinfo["position"]
    out["headshot"] = pinfo["headshot"]
    note_by_player = rows.groupby("player_id")["avail_note"].first()
    out["status"] = note_by_player.reindex(pool).fillna(
        pd.Series({p: ("Out" if p in inj.index else "Active") for p in pool}))
    out["rank"] = out["value"].rank(ascending=False, method="first").astype(int)
    out["pg_rank"] = out["pg_value"].rank(ascending=False, method="first").astype(int)
    out.index.name = "player_id"
    return Projection(window, out.sort_values("rank"), rows, params, pg_params, methods)


# ----------------------------------------------------------------------------- logging
def _log_projection(proj: Projection) -> None:
    """Persist pre-week projections so they can be scored against actual results later."""
    if today() >= proj.window.week_start or proj.window.key != "next":
        return
    now = datetime.now(timezone.utc).isoformat()
    cols = ["games", "exp_games", *MODEL_STATS, *[f"sd_{s}" for s in MODEL_STATS], "value"]
    with get_conn() as conn:
        for pid, r in proj.players.iterrows():
            if r["games"] <= 0:
                continue
            payload = {c: float(r[c]) for c in cols}
            payload["methods"] = proj.methods
            conn.execute(
                "INSERT OR REPLACE INTO projection_log(week_start, player_id, method, created_at, games, payload)"
                " VALUES(?,?,?,?,?,?)",
                (proj.window.week_start.isoformat(), int(pid), "courtvision", now, int(r["games"]),
                 json.dumps(payload)),
            )


# ----------------------------------------------------------------------------- helpers
def explain_player(proj: Projection, player_id: int) -> dict:
    """Transparent breakdown of how one player's projection was built."""
    rows = proj.games[proj.games["player_id"] == player_id]
    if rows.empty:
        return {"games": []}
    first = rows.iloc[0]
    components = {}
    for s in MODEL_STATS:
        components[s] = {
            "season_blend": _f(first[f"blend_{s}"]), "current_season_avg": _f(first[f"cur_{s}"]),
            "prior_two_season_avg": _f(first[f"prev_{s}"]), "last10": _f(first[f"l10_{s}"]),
            "last5": _f(first[f"l5_{s}"]), "weighted_baseline": _f(first[f"base_{s}"]),
            "method": proj.methods[s],
        }
    teams = repo.teams()
    games = []
    for _, r in rows.sort_values("date").iterrows():
        games.append({
            "date": r["date"].date().isoformat(), "weekday": r["date"].strftime("%a"),
            "opponent": teams.loc[r["opp_team_id"], "abbr"] if r["opp_team_id"] in teams.index else "?",
            "opponent_logo": teams.loc[r["opp_team_id"], "logo"] if r["opp_team_id"] in teams.index else None,
            "home": bool(r["home"]), "rest_days": int(r["rest"]),
            "availability": float(r["avail"]), "availability_note": r["avail_note"],
            "opp_pts_factor": round(float(r["opp_pts"]), 3),
            "projection": {s: round(float(r[f"p_{s}"]), 2) for s in MODEL_STATS},
        })
    return {"games_this_season": int(first["cur_n"]), "prior_season_games": int(first["prev_n"]),
            "components": components, "games": games}


def _f(v) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else round(v, 3)


def player_row(proj: Projection, player_id: int) -> dict | None:
    if player_id not in proj.players.index:
        return None
    return clean_record(proj.players.loc[player_id].to_dict() | {"player_id": player_id})


def clean_record(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if isinstance(v, (np.floating, float)):
            out[k] = None if np.isnan(v) else round(float(v), 4)
        elif isinstance(v, np.integer):
            out[k] = int(v)
        else:
            out[k] = v
    return out


__all__ = ["Projection", "project", "explain_player", "player_row", "clean_record", "availability",
           "KEY_COLS", "Z80"]
