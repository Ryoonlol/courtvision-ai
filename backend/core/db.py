"""SQLite storage: cached NBA data, AI response cache and saved projections."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    abbr TEXT NOT NULL,
    name TEXT NOT NULL,
    logo TEXT
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    position TEXT,
    team_id INTEGER,
    team_abbr TEXT,
    headshot TEXT,
    last_game_date TEXT
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,          -- ESPN season year, e.g. 2027 == 2026-27
    season_type INTEGER NOT NULL,     -- 2 == regular season
    date TEXT NOT NULL,               -- US/Eastern calendar date YYYY-MM-DD
    start_utc TEXT,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_abbr TEXT,
    away_abbr TEXT,
    status TEXT,
    home_score INTEGER,
    away_score INTEGER,
    box_ingested INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_games_date ON games(date);
CREATE TABLE IF NOT EXISTS box_scores (
    game_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    opp_team_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    season INTEGER NOT NULL,
    home INTEGER NOT NULL,
    starter INTEGER,
    min REAL, pts REAL, reb REAL, ast REAL, stl REAL, blk REAL, tov REAL,
    fgm REAL, fga REAL, fg3m REAL, fg3a REAL, ftm REAL, fta REAL,
    oreb REAL, dreb REAL, pf REAL,
    PRIMARY KEY (game_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_box_player ON box_scores(player_id, date);
CREATE TABLE IF NOT EXISTS scoreboard_fetch (
    date TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS injuries (
    player_id INTEGER PRIMARY KEY,
    name TEXT,
    team_abbr TEXT,
    status TEXT,
    fantasy_status TEXT,
    return_date TEXT,
    short_comment TEXT,
    reported_at TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS ai_cache (
    key TEXT PRIMARY KEY,
    task TEXT,
    model TEXT,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rosters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'mine',   -- 'mine' | 'opponent' | 'other'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster_players (
    roster_id INTEGER NOT NULL REFERENCES rosters(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    PRIMARY KEY (roster_id, player_id)
);
CREATE TABLE IF NOT EXISTS gemini_forecasts (
    kind TEXT NOT NULL,              -- 'live' | 'backtest'
    week_start TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (kind, week_start, player_id)
);
CREATE TABLE IF NOT EXISTS projection_log (
    week_start TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    games INTEGER,
    payload TEXT NOT NULL,
    PRIMARY KEY (week_start, player_id, method)
);
"""

_lock = threading.Lock()


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with _lock, get_conn(path) as conn:
        conn.executescript(SCHEMA)


def get_meta(key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))
