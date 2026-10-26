"""Projection accuracy tracker across every completed fantasy week.

For each completed Monday-Sunday week and each player who played in it, two leakage-free weekly
projections are built from the player's state *before his first game that week* (which, by
construction, only uses games from earlier weeks):

  weighted  -- CourtVision's explainable baseline (season blend + L10 + L5), x games played
  naive     -- season-average-to-date (prior season if no games yet), x games played

Both are scored against actual weekly totals: MAE per category (FG%/FT% attempt-weighted) and the
Spearman rank correlation of 9-category value. Pre-week projections saved by the live app
(``projection_log``; including the ML model, opponent and injury adjustments) are scored once their
week is complete.
"""
from __future__ import annotations

import json
import threading
from datetime import timedelta

import numpy as np
import pandas as pd

from core.categories import CATEGORIES, RAW_STATS
from core.db import get_conn
from data import repository as repo
from data.ingest import season_label
from services import ml_model, valuation
from services.features import player_features
from services.history import weekly_totals
from services.schedule import today

_cache: dict[str, dict] = {}
_lock = threading.Lock()
METHODS = ("weighted", "naive")


def _state_at_week_start() -> pd.DataFrame:
    box = repo.box_scores()
    feat = player_features(box)
    feat["week_start"] = (feat["date"] - pd.to_timedelta(feat["date"].dt.weekday, unit="D")).dt.normalize()
    first = feat.sort_values(["player_id", "date", "game_id"]).groupby(["player_id", "week_start"]).head(1)
    return first.set_index(["week_start", "player_id"])


def _week_metrics(act: pd.DataFrame, proj: pd.DataFrame) -> dict:
    params = valuation.fit(act[RAW_STATS])
    a_val = valuation.score(act[RAW_STATS], params)["value"]
    p_val = valuation.score(proj[RAW_STATS], params)["value"]
    out = {"spearman": float(p_val.corr(a_val, method="spearman")),
           "top50_overlap": len(set(p_val.nlargest(50).index) & set(a_val.nlargest(50).index)) / 50}
    for c in CATEGORIES:
        if c.is_pct:
            att = act[c.attempts]
            m = att > 0
            pp = (proj[c.makes] / proj[c.attempts].replace(0, np.nan)).fillna(0)
            ap = act[c.makes] / att.replace(0, np.nan)
            out[c.key] = float(np.average((pp - ap).abs()[m], weights=att[m])) if m.any() else None
        else:
            out[c.key] = float((proj[c.key] - act[c.key]).abs().mean())
    return out


def compute() -> dict:
    key = repo.data_version()
    with _lock:
        core = _cache.get(key)
    if core is None:
        core = _compute()
        with _lock:
            _cache.clear()
            _cache[key] = core
    # saved projections and Gemini backtests change independently of the box-score data, so never cache them
    return {**core, "saved_projections": saved_projection_scores(), "gemini_backtest": _gemini_backtest()}


def _compute() -> dict:
    state = _state_at_week_start()
    wt = weekly_totals().set_index(["week_start", "player_id"])
    cur_monday = pd.Timestamp(today() - timedelta(days=today().weekday()))
    weeks = []
    for ws in sorted(wt.index.get_level_values(0).unique()):
        if ws >= cur_monday:
            continue  # incomplete week
        act = wt.loc[ws]
        st = state.loc[ws] if ws in state.index.get_level_values(0) else None
        if st is None:
            continue
        ids = act.index.intersection(st.index[st["base_pts"].notna()])
        if len(ids) < 60:
            continue  # first week of history: no prior games to project from
        act = act.loc[ids]
        g = act["games"]
        row = {"week_start": ws.date().isoformat(), "season": season_label(int(act["season"].max())), "players": int(len(ids))}
        for method in METHODS:
            proj = pd.DataFrame({s: _rate(st.loc[ids], s, method) * g for s in RAW_STATS})
            row[method] = _week_metrics(act, proj)
        weeks.append(row)

    def summarize(rows):
        if not rows:
            return {}
        out = {}
        for method in METHODS:
            out[method] = {k: float(np.nanmean([r[method][k] for r in rows if r[method][k] is not None]))
                           for k in ["spearman", "top50_overlap", *[c.key for c in CATEGORIES]]}
        return out

    seasons = sorted({w["season"] for w in weeks})
    return {
        "method_notes": {
            "weighted": "CourtVision weighted baseline (season blend + last-10 + last-5), using only earlier games",
            "naive": "Season average to date (prior season when no games yet)",
            "scope": "Projected per-game rate x games actually played; injuries/opponents not applied in backtests",
        },
        "weeks": weeks,
        "overall": summarize(weeks),
        "by_season": {s: summarize([w for w in weeks if w["season"] == s]) | {"weeks": sum(w["season"] == s for w in weeks)}
                      for s in seasons},

        "model_validation": {k: v for k, v in ml_model.summary().items() if k in {"trained", "metrics", "split_date", "rows"}},
    }


def _rate(st: pd.DataFrame, stat: str, method: str) -> pd.Series:
    if method == "weighted":
        return st[f"base_{stat}"]
    cur = st[f"cur_{stat}"]
    return cur.where(cur.notna(), st[f"prev_{stat}"]).fillna(0.0)


def saved_projection_scores() -> list[dict]:
    """Score each week's saved pre-week projections (one entry per method) once that week is complete.

    When several methods (e.g. 'courtvision' and 'gemini') exist for a week, all are scored on the players
    common to every method so the comparison is like-for-like.
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT week_start, player_id, method, payload, created_at FROM projection_log").fetchall()
    if not rows:
        return []
    wt = weekly_totals()
    cur_monday = today() - timedelta(days=today().weekday())
    df = pd.DataFrame([{"week_start": r["week_start"], "player_id": r["player_id"], "method": r["method"],
                        "created_at": r["created_at"], **json.loads(r["payload"])} for r in rows])
    out = []
    for ws, grp in df.groupby("week_start"):
        complete = pd.Timestamp(ws).date() < cur_monday
        methods = sorted(grp["method"].unique())
        rec = {"week_start": ws, "status": "scored" if complete else "pending (week not finished)",
               "methods": {m: {"players_projected": int((grp["method"] == m).sum()),
                               "saved_at": grp.loc[grp["method"] == m, "created_at"].max()} for m in methods}}
        if complete:
            act = wt[wt["week_start"] == pd.Timestamp(ws)].set_index("player_id")
            common = act.index
            for m in methods:
                common = common.intersection(grp.loc[grp["method"] == m, "player_id"])
            rec["common_players"] = int(len(common))
            if len(common):
                a = act.loc[common]
                a_val = valuation.score(a[RAW_STATS], valuation.fit(a[RAW_STATS]))["value"]
                for m in methods:
                    g = grp[grp["method"] == m].set_index("player_id").loc[common]
                    rec["methods"][m]["mae"] = {s: float((g[s] - a[s]).abs().mean())
                                                for s in ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]}
                    if len(common) > 10:
                        rec["methods"][m]["spearman_value"] = float(g["value"].corr(a_val, method="spearman"))
        out.append(rec)
    return out


def _gemini_backtest() -> dict:
    from services.gemini_forecast import backtest_scores
    return backtest_scores()
