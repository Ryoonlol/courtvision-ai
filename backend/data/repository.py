"""Read access to cached NBA data as pandas DataFrames (memoised per data version)."""
from __future__ import annotations

import threading
from datetime import date

import pandas as pd

from core.db import get_conn, get_meta

_cache: dict[str, object] = {}
_lock = threading.Lock()


def data_version() -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n, MAX(date) AS d FROM box_scores").fetchone()
    return f"{row['n']}:{row['d']}:{get_meta('last_refresh_utc', '')}:{get_meta('data_source', '')}"


def _memo(name: str, loader):
    version = data_version()
    key = f"{name}@{version}"
    with _lock:
        if key not in _cache:
            for k in [k for k in _cache if k.startswith(f"{name}@")]:
                del _cache[k]
            _cache[key] = loader()
        return _cache[key]


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def box_scores() -> pd.DataFrame:
    def load() -> pd.DataFrame:
        with get_conn() as conn:
            df = pd.read_sql_query("SELECT * FROM box_scores", conn)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)
    return _memo("box", load)


def players() -> pd.DataFrame:
    def load() -> pd.DataFrame:
        with get_conn() as conn:
            return pd.read_sql_query("SELECT * FROM players", conn).set_index("id", drop=False)
    return _memo("players", load)


def teams() -> pd.DataFrame:
    def load() -> pd.DataFrame:
        with get_conn() as conn:
            return pd.read_sql_query("SELECT * FROM teams", conn).set_index("id", drop=False)
    return _memo("teams", load)


def games() -> pd.DataFrame:
    def load() -> pd.DataFrame:
        with get_conn() as conn:
            df = pd.read_sql_query("SELECT * FROM games WHERE season_type=2", conn)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values(["date", "id"]).reset_index(drop=True)
    return _memo("games", load)


def injuries() -> pd.DataFrame:
    def load() -> pd.DataFrame:
        with get_conn() as conn:
            return pd.read_sql_query("SELECT * FROM injuries", conn).set_index("player_id", drop=False)
    return _memo("injuries", load)


def team_games_between(start: date, end: date) -> pd.DataFrame:
    """One row per (team, game) in [start, end] with opponent and home flag."""
    g = games()
    mask = (g["date"].dt.date >= start) & (g["date"].dt.date <= end)
    g = g.loc[mask]
    home = pd.DataFrame({"team_id": g["home_team_id"], "opp_team_id": g["away_team_id"],
                         "game_id": g["id"], "date": g["date"], "home": 1, "status": g["status"]})
    away = pd.DataFrame({"team_id": g["away_team_id"], "opp_team_id": g["home_team_id"],
                         "game_id": g["id"], "date": g["date"], "home": 0, "status": g["status"]})
    return pd.concat([home, away], ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)
