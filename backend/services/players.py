"""Player look-ups: search, season averages, recent form and game logs (actual stats)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.categories import RAW_STATS
from data import repository as repo
from data.ingest import CURRENT_SEASON, season_label

AVG_STATS = ["min", *RAW_STATS, "fg3a"]


def summarize(games: pd.DataFrame) -> dict | None:
    """Per-game averages with volume-weighted percentages for a set of games."""
    if games.empty:
        return None
    out = {s: round(float(games[s].mean()), 2) for s in AVG_STATS}
    out["games"] = int(len(games))
    out["fg_pct"] = _pct(games["fgm"].sum(), games["fga"].sum())
    out["ft_pct"] = _pct(games["ftm"].sum(), games["fta"].sum())
    out["fg3_pct"] = _pct(games["fg3m"].sum(), games["fg3a"].sum())
    out["first_date"] = games["date"].min().date().isoformat()
    out["last_date"] = games["date"].max().date().isoformat()
    return out


def _pct(m: float, a: float) -> float | None:
    return round(float(m) / float(a), 4) if a > 0 else None


def player_profile(player_id: int) -> dict | None:
    players = repo.players()
    if player_id not in players.index:
        return None
    p = players.loc[player_id]
    teams = repo.teams()
    inj = repo.injuries()
    box = repo.box_scores()
    log = box[box["player_id"] == player_id].sort_values("date")
    seasons = {}
    for season in sorted(log["season"].unique(), reverse=True):
        seasons[season_label(int(season))] = summarize(log[log["season"] == season])
    recent = log.tail(10)
    game_log = []
    for _, r in log.tail(15).iloc[::-1].iterrows():
        opp = teams.loc[r["opp_team_id"]] if r["opp_team_id"] in teams.index else None
        game_log.append({
            "date": r["date"].date().isoformat(), "season": season_label(int(r["season"])),
            "opponent": opp["abbr"] if opp is not None else "?", "home": bool(r["home"]),
            **{s: float(r[s]) for s in AVG_STATS},
        })
    injury = inj.loc[player_id].to_dict() if player_id in inj.index else None
    return {
        "id": int(player_id), "name": p["name"], "position": p["position"], "team_abbr": p["team_abbr"],
        "team_name": teams.loc[p["team_id"], "name"] if p["team_id"] in teams.index else None,
        "team_logo": teams.loc[p["team_id"], "logo"] if p["team_id"] in teams.index else None,
        "headshot": p["headshot"],
        "injury": {k: injury[k] for k in ("status", "fantasy_status", "return_date", "short_comment")} if injury else None,
        "current_season": season_label(CURRENT_SEASON),
        "seasons": seasons,
        "last5": summarize(recent.tail(5)),
        "last10": summarize(recent),
        "game_log": game_log,
    }


def search(query: str, limit: int = 15, ranking: pd.DataFrame | None = None) -> list[dict]:
    """Name search over players seen in the last two seasons, best projected first."""
    players = repo.players()
    box = repo.box_scores()
    recent_ids = box.loc[box["season"] >= CURRENT_SEASON - 1, "player_id"].unique()
    df = players.loc[players.index.intersection(recent_ids)]
    q = _norm(query)
    if q:
        names = df["name"].map(_norm)
        mask = names.str.contains(q, regex=False)
        df = df[mask]
    df = df.copy()
    if ranking is not None:
        df["value"] = df.index.map(ranking["value"]).astype(float)
        df["rank"] = df.index.map(ranking["rank"])
    else:
        df["value"] = np.nan
        df["rank"] = np.nan
    df = df.sort_values("value", ascending=False, na_position="last").head(limit)
    return [{"id": int(i), "name": r["name"], "team_abbr": r["team_abbr"], "position": r["position"],
             "headshot": r["headshot"], "rank": None if pd.isna(r["rank"]) else int(r["rank"])}
            for i, r in df.iterrows()]


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower().strip()


def find_by_name(name: str) -> int | None:
    hits = search(name, limit=1)
    return hits[0]["id"] if hits else None
