"""Historical weekly rankings from actual box scores, player trends and projection backtests.

Fantasy weeks run Monday-Sunday (US/Eastern). Each week's actual totals are valued with the same
9-category z-score method as the projections (pool = top 156 performers that week).

Backtest: for a past week, the explainable weighted baseline is recomputed using ONLY games
played before that Monday (no model fitted on future data, no look-ahead), multiplied by the
games each player actually played, and compared with what happened. Saved live projections
(``projection_log``) are compared too whenever they exist for that week.
"""
from __future__ import annotations

import json
import threading
from datetime import date, timedelta

import numpy as np
import pandas as pd

from core.categories import CATEGORIES, RAW_STATS
from core.db import get_conn
from data import repository as repo
from data.ingest import season_label
from services import valuation
from services.features import player_features
from services.schedule import today

_cache: dict[tuple, object] = {}
_lock = threading.Lock()


def _memo(key: tuple, fn):
    full = (*key, repo.data_version())
    with _lock:
        if full in _cache:
            return _cache[full]
    val = fn()
    with _lock:
        if len(_cache) > 64:
            _cache.clear()
        _cache[full] = val
    return val


def weekly_totals() -> pd.DataFrame:
    """One row per (week_start, player) with games played and summed raw stats."""
    def build():
        box = repo.box_scores()
        wk = box["date"] - pd.to_timedelta(box["date"].dt.weekday, unit="D")
        df = box.assign(week_start=wk.dt.normalize())
        agg = df.groupby(["week_start", "player_id"]).agg(
            season=("season", "max"), games=("game_id", "size"), team_id=("team_id", "last"),
            **{s: (s, "sum") for s in ["min", *RAW_STATS]})
        return agg.reset_index()
    return _memo(("weekly_totals",), build)


def available_weeks() -> list[dict]:
    wt = weekly_totals()
    cur_monday = today() - timedelta(days=today().weekday())
    g = wt.groupby("week_start").agg(season=("season", "max"), players=("player_id", "nunique"),
                                     player_games=("games", "sum")).reset_index()
    with get_conn() as conn:
        saved = {r["week_start"] for r in conn.execute("SELECT DISTINCT week_start FROM projection_log")}
    out = []
    for _, r in g.sort_values("week_start", ascending=False).iterrows():
        start = r["week_start"].date()
        out.append({
            "week_start": start.isoformat(), "week_end": (start + timedelta(days=6)).isoformat(),
            "season": season_label(int(r["season"])), "label": f"{start:%b %-d} – {start + timedelta(days=6):%b %-d, %Y}",
            "players": int(r["players"]), "in_progress": start >= cur_monday,
            "has_saved_projection": start.isoformat() in saved,
        })
    return out


def _rank_week(df: pd.DataFrame) -> tuple[pd.DataFrame, valuation.ValuationParams]:
    params = valuation.fit(df[RAW_STATS])
    z = valuation.score(df[RAW_STATS], params)
    out = pd.concat([df, z], axis=1)
    out["rank"] = out["value"].rank(ascending=False, method="first").astype(int)
    return out, params


def all_week_values() -> pd.DataFrame:
    """Actual 9-cat value and rank for every player in every week (for trends)."""
    def build():
        wt = weekly_totals()
        parts = [_rank_week(g.set_index("player_id"))[0].reset_index() for _, g in wt.groupby("week_start")]
        return pd.concat(parts, ignore_index=True)
    return _memo(("all_week_values",), build)


def _week(start: date) -> pd.DataFrame:
    wt = weekly_totals()
    return wt[wt["week_start"] == pd.Timestamp(start)].set_index("player_id")


def week_rankings(start: date, sort: str = "value", position: str | None = None, search: str | None = None,
                  limit: int = 150) -> dict:
    start = start - timedelta(days=start.weekday())
    df = _week(start)
    if df.empty:
        raise KeyError(start)
    ranked, params = _memo(("rank_week", start), lambda: _rank_week(df))
    players, teams = repo.players(), repo.teams()
    ranked = ranked.join(players[["name", "position", "headshot"]], how="left")
    ranked["team_abbr"] = ranked["team_id"].map(teams["abbr"])
    ranked["team_logo"] = ranked["team_id"].map(teams["logo"])
    for c in CATEGORIES:
        if c.is_pct:
            ranked[c.key] = np.where(ranked[c.attempts] > 0, ranked[c.makes] / ranked[c.attempts].replace(0, np.nan), np.nan)

    leaders = {}
    for c in CATEGORIES:
        sub = ranked[ranked[c.attempts] >= ranked[c.attempts].quantile(0.75)] if c.is_pct else ranked
        top = sub.sort_values(c.key, ascending=not c.higher_is_better).head(5)
        leaders[c.key] = [{"player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"], "headshot": r["headshot"],
                           "value": round(float(r[c.key]), 3 if c.is_pct else 1)} for pid, r in top.iterrows()]

    # trend vs previous week (rank change)
    prev = all_week_values()
    prev = prev[prev["week_start"] == pd.Timestamp(start - timedelta(days=7))].set_index("player_id")["rank"]
    ranked["prev_rank"] = prev.reindex(ranked.index)

    view = ranked
    if position:
        view = view[view["position"].fillna("").str.upper().str.contains(position.upper()[0])]
    if search:
        view = view[view["name"].fillna("").str.lower().str.contains(search.lower(), regex=False)]
    key = sort if sort in {"value", "games", "min", *[c.key for c in CATEGORIES]} else "value"
    view = view.sort_values(key, ascending=(key == "tov"), na_position="last").head(limit)

    rows = []
    for pid, r in view.iterrows():
        rec = {"player_id": int(pid), "rank": int(r["rank"]),
               "prev_rank": None if pd.isna(r["prev_rank"]) else int(r["prev_rank"]),
               "name": r["name"], "team_abbr": r["team_abbr"], "team_logo": r["team_logo"],
               "position": r["position"], "headshot": r["headshot"], "games": int(r["games"]),
               "min": float(r["min"]), "value": float(r["value"])}
        for c in CATEGORIES:
            v = r[c.key]
            rec[c.key] = None if pd.isna(v) else float(v)
            rec[f"z_{c.key}"] = float(r[f"z_{c.key}"])
        for s in ("fgm", "fga", "ftm", "fta"):
            rec[s] = float(r[s])
        rows.append(rec)
    end = start + timedelta(days=6)
    return {
        "week_start": start.isoformat(), "week_end": end.isoformat(),
        "label": f"{start:%b %-d} – {end:%b %-d, %Y}",
        "in_progress": start >= today() - timedelta(days=today().weekday()),
        "players": int(len(ranked)), "pool_fg_pct": params.pool_pct["fg_pct"], "pool_ft_pct": params.pool_pct["ft_pct"],
        "rows": rows, "leaders": leaders,
    }


def player_trend(player_id: int, season: int | None = None) -> dict:
    vals = all_week_values()
    pv = vals[vals["player_id"] == player_id]
    if pv.empty:
        raise KeyError(player_id)
    season = season or int(pv["season"].max())
    pv = pv[pv["season"] == season].sort_values("week_start")
    weeks = []
    for _, r in pv.iterrows():
        rec = {"week_start": r["week_start"].date().isoformat(), "games": int(r["games"]),
               "value": round(float(r["value"]), 3), "rank": int(r["rank"])}
        for c in CATEGORIES:
            if c.is_pct:
                rec[c.key] = float(r[c.makes] / r[c.attempts]) if r[c.attempts] > 0 else None
            else:
                rec[c.key] = float(r[c.key])
        weeks.append(rec)
    v = np.array([w["value"] for w in weeks])
    slope = float(np.polyfit(np.arange(len(v)), v, 1)[0]) if len(v) >= 3 else None
    seasons = sorted({season_label(int(s)) for s in vals.loc[vals["player_id"] == player_id, "season"]}, reverse=True)
    p = repo.players().loc[player_id] if player_id in repo.players().index else None
    return {"player_id": player_id, "name": p["name"] if p is not None else None, "season": season_label(season),
            "seasons_available": seasons, "weeks": weeks,
            "avg_value": float(v.mean()) if len(v) else None, "best_rank": int(min(w["rank"] for w in weeks)) if weeks else None,
            "trend_per_week": slope}


# --------------------------------------------------------------------------- backtest
def backtest(start: date) -> dict:
    start = start - timedelta(days=start.weekday())
    return _memo(("backtest", start), lambda: _backtest(start))


def _backtest(start: date) -> dict:
    actual = _week(start)
    if actual.empty:
        raise KeyError(start)
    box = repo.box_scores()
    before = box[box["date"] < pd.Timestamp(start)]
    ph = pd.DataFrame({"player_id": actual.index, "game_id": -1, "date": pd.Timestamp(start),
                       "season": actual["season"].to_numpy(), "team_id": actual["team_id"].to_numpy(),
                       "opp_team_id": -1, "home": 0})
    feat = player_features(before[before["player_id"].isin(actual.index)], ph)
    state = feat[feat["placeholder"]].set_index("player_id")
    covered = state.index[state["base_pts"].notna()]
    act = actual.loc[covered]
    games = act["games"]
    proj = pd.DataFrame({s: state.loc[covered, f"base_{s}"] * games for s in RAW_STATS})

    ranked_actual, params = _rank_week(act)
    proj_val = valuation.score(proj, params)["value"]
    metrics = {}
    for c in CATEGORIES:
        if c.is_pct:
            a_att = act[c.attempts]
            mask = a_att > 0
            p_pct = proj[c.makes] / proj[c.attempts].replace(0, np.nan)
            a_pct = act[c.makes] / a_att.replace(0, np.nan)
            err = (p_pct - a_pct).abs()[mask]
            metrics[c.key] = {"mae": float(np.average(err.fillna(0), weights=a_att[mask])), "unit": "pct (attempt-weighted)"}
        else:
            metrics[c.key] = {"mae": float((proj[c.key] - act[c.key]).abs().mean()),
                              "mean_actual": float(act[c.key].mean()), "unit": "weekly total"}
    spearman = float(pd.Series(proj_val).corr(ranked_actual["value"], method="spearman"))
    top_n = 50
    proj_top = set(proj_val.sort_values(ascending=False).index[:top_n])
    act_top = set(ranked_actual["value"].sort_values(ascending=False).index[:top_n])

    players = repo.players()
    diff = (ranked_actual["value"] - proj_val).sort_values()
    def row(pid):
        return {"player_id": int(pid), "name": players.at[pid, "name"] if pid in players.index else str(pid),
                "headshot": players.at[pid, "headshot"] if pid in players.index else None,
                "projected_value": round(float(proj_val[pid]), 2), "actual_value": round(float(ranked_actual.at[pid, "value"]), 2),
                "games": int(games[pid])}

    return {
        "week_start": start.isoformat(),
        "method": "Weighted baseline using only games before the week, x games actually played (no injury/opponent adjustment).",
        "players": int(len(covered)),
        "category_mae": metrics,
        "value_rank_spearman": spearman,
        "top50_overlap": len(proj_top & act_top) / top_n,
        "overperformers": [row(p) for p in diff.index[::-1][:5]],
        "underperformers": [row(p) for p in diff.index[:5]],
        "scatter": [{"player_id": int(p), "name": players.at[p, "name"] if p in players.index else str(p),
                     "projected": round(float(proj_val[p]), 2), "actual": round(float(ranked_actual.at[p, "value"]), 2)}
                    for p in ranked_actual["value"].sort_values(ascending=False).index[:120]],
        "saved_projection": saved_projection_accuracy(start, act),
    }


def saved_projection_accuracy(start: date, act: pd.DataFrame | None = None) -> dict | None:
    """Compare pre-week projections stored by the live app with actual results."""
    with get_conn() as conn:
        rows = conn.execute("SELECT player_id, payload, created_at FROM projection_log WHERE week_start=?",
                            (start.isoformat(),)).fetchall()
    if not rows:
        return None
    if act is None:
        act = _week(start)
    saved = pd.DataFrame([{**json.loads(r["payload"]), "player_id": r["player_id"]} for r in rows]).set_index("player_id")
    common = saved.index.intersection(act.index)
    if common.empty:
        return {"players": 0, "created_at": rows[0]["created_at"]}
    metrics = {s: float((saved.loc[common, s] - act.loc[common, s]).abs().mean())
               for s in ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]}
    return {"players": int(len(common)), "created_at": rows[0]["created_at"], "weekly_mae": metrics,
            "note": "Saved before the week started; includes availability and opponent adjustments."}
