"""Offline DEMONSTRATION dataset (used only when live ESPN data cannot be fetched).

All teams and players are fictional and clearly labelled "DEMO". Stats are simulated from
simple per-minute rate distributions so every feature can be exercised offline. Nothing
here represents real NBA statistics.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np

from core.db import get_conn, init_db, set_meta
from data.ingest import CURRENT_SEASON, SEASON_WINDOWS, today_eastern

log = logging.getLogger("courtvision.demo")

FIRST = ["Avery", "Blake", "Cam", "Dante", "Eli", "Felix", "Gabe", "Hugo", "Isaiah", "Jalen", "Kai", "Luca",
         "Marcus", "Nico", "Omar", "Pierce", "Quinn", "Rafael", "Silas", "Theo", "Uriah", "Vince", "Wes", "Xavier",
         "Yusuf", "Zion"]
LAST = ["Archer", "Bishop", "Cross", "Drake", "Ellis", "Ford", "Graves", "Hale", "Irving", "Jett", "Knox", "Lane",
        "Mercer", "North", "Okafor", "Price", "Quarles", "Reyes", "Stone", "Tate", "Underwood", "Vance", "Webb",
        "Young", "Zeller", "Monroe", "Banks", "Carver", "Dunn", "Easton"]
CITIES = ["Harbor", "Summit", "Canyon", "Prairie", "Bayou", "Granite", "Coastal", "Maple", "Desert", "Aurora",
          "Ironwood", "Lakeside", "Redwood", "Skyline", "Riverbend", "Frontier", "Highland", "Metro", "Pinecrest",
          "Sunset", "Tidewater", "Valley", "Westgate", "Northstar", "Ember", "Crescent", "Glacier", "Magnolia",
          "Thunder", "Union"]
POSITIONS = ["G", "G", "G", "F", "F", "F", "F", "C", "C", "G"]


def generate(seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    init_db()
    with get_conn() as conn:
        for t in ("box_scores", "games", "players", "teams", "injuries", "scoreboard_fetch", "projection_log",
                  "ai_cache"):
            conn.execute(f"DELETE FROM {t}")
        teams = []
        for i, city in enumerate(CITIES):
            tid = 9000 + i
            teams.append(tid)
            conn.execute("INSERT INTO teams(id, abbr, name, logo) VALUES(?,?,?,?)",
                         (tid, f"D{i + 1:02d}", f"{city} Demo Club", None))
        players = []
        pid = 990000
        for tid in teams:
            for slot in range(11):
                pid += 1
                pos = POSITIONS[slot % len(POSITIONS)]
                minutes = float(np.clip(rng.normal(34 - slot * 2.4, 3), 6, 38))
                talent = rng.lognormal(0, 0.25)
                rates = {  # per-minute rates by position archetype
                    "pts": 0.45 * talent, "reb": (0.28 if pos == "C" else 0.18 if pos == "F" else 0.11) * talent,
                    "ast": (0.22 if pos == "G" else 0.09) * talent, "stl": 0.032 * talent,
                    "blk": (0.06 if pos == "C" else 0.02) * talent,
                    "fg3a": (0.17 if pos != "C" else 0.04) * talent, "tov": 0.055 * talent,
                    "fg_pct": float(np.clip(rng.normal(0.56 if pos == "C" else 0.46, 0.03), 0.38, 0.68)),
                    "ft_pct": float(np.clip(rng.normal(0.66 if pos == "C" else 0.8, 0.06), 0.5, 0.93)),
                    "fg3_pct": float(np.clip(rng.normal(0.36, 0.03), 0.28, 0.43)),
                }
                name = f"{FIRST[rng.integers(len(FIRST))]} {LAST[rng.integers(len(LAST))]} (Demo)"
                players.append((pid, tid, pos, minutes, rates))
                conn.execute("INSERT INTO players(id, name, position, team_id, team_abbr, headshot) VALUES(?,?,?,?,?,?)",
                             (pid, name, pos, tid, f"D{teams.index(tid) + 1:02d}", None))
        by_team = {t: [p for p in players if p[1] == t] for t in teams}

        today = today_eastern()
        gid = 7_000_000
        for season in (CURRENT_SEASON - 2, CURRENT_SEASON - 1, CURRENT_SEASON):
            start, end = SEASON_WINDOWS[season]
            end = min(end, today + timedelta(days=21))
            d = start
            week_games: dict[int, int] = {}
            week_target: dict[int, int] = {}
            while d <= end:
                if d.weekday() == 0 or not week_target:
                    week_games = {t: 0 for t in teams}
                    week_target = {t: int(rng.choice([3, 4, 4])) for t in teams}  # NBA-like 3-4 games/week
                n_games = int(rng.integers(3, 12))
                eligible = [t for t in rng.permutation(teams) if week_games[t] < week_target[t]]
                order = eligible[: min(n_games * 2, len(eligible) // 2 * 2)]
                for t in order:
                    week_games[t] += 1
                for h, a in zip(order[::2], order[1::2]):
                    gid += 1
                    final = d < today
                    _insert_game(conn, rng, gid, season, d, int(h), int(a), final, by_team)
                d += timedelta(days=1)
    set_meta("data_source", "demo")
    set_meta("last_refresh_utc", date.today().isoformat())
    log.warning("Generated OFFLINE DEMO dataset (fictional players).")


def _insert_game(conn, rng, gid, season, d: date, home: int, away: int, final: bool, by_team) -> None:
    hs = as_ = None
    if final:
        totals = {}
        for team, opp, is_home in ((home, away, 1), (away, home, 0)):
            pts_total = 0
            for pid, tid, pos, minutes, r in by_team[team]:
                if rng.random() < 0.06:
                    continue  # rest / injury
                mins = float(np.clip(rng.normal(minutes, 4), 2, 44))
                fg3a = rng.poisson(r["fg3a"] * mins)
                fga = max(fg3a, rng.poisson(r["pts"] * mins / 1.15 / 1.0 * 0.85))
                fg3m = rng.binomial(fg3a, r["fg3_pct"])
                fgm = max(fg3m, rng.binomial(fga, r["fg_pct"]))
                fta = rng.poisson(r["pts"] * mins * 0.12)
                ftm = rng.binomial(fta, r["ft_pct"])
                pts = 2 * fgm + fg3m + ftm
                reb = rng.poisson(r["reb"] * mins)
                row = (gid, pid, tid, opp, d.isoformat(), season, is_home, 1, round(mins), pts, reb,
                       rng.poisson(r["ast"] * mins), rng.poisson(r["stl"] * mins), rng.poisson(r["blk"] * mins),
                       rng.poisson(r["tov"] * mins), fgm, fga, fg3m, fg3a, ftm, fta, reb // 4, reb - reb // 4, 2)
                conn.execute("INSERT INTO box_scores VALUES(" + ",".join("?" * len(row)) + ")",
                             tuple(float(x) if isinstance(x, (np.integer, np.floating)) else x for x in row))
                conn.execute("UPDATE players SET last_game_date=? WHERE id=?", (d.isoformat(), pid))
                pts_total += pts
            totals[team] = pts_total
        hs, as_ = totals[home], totals[away]
    conn.execute(
        "INSERT INTO games(id, season, season_type, date, start_utc, home_team_id, away_team_id, home_abbr, away_abbr,"
        " status, home_score, away_score, box_ingested) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (gid, season, 2, d.isoformat(), None, home, away, f"D{home - 8999:02d}", f"D{away - 8999:02d}",
         "STATUS_FINAL" if final else "STATUS_SCHEDULED", hs, as_, int(final)))
