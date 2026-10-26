"""Ingest real NBA schedules, box scores and injuries from ESPN into SQLite.

Usage (from backend/):
    python -m data.ingest                 # 3 seasons of history + current schedule
    python -m data.ingest --refresh       # only refresh recent days, schedule, injuries
"""
from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

from core.db import get_conn, init_db, set_meta
from data.espn_client import EASTERN, EspnClient

log = logging.getLogger("courtvision.ingest")

# ESPN season year -> regular-season date window (inclusive, generous edges;
# games are additionally filtered on season_type == 2).
SEASON_WINDOWS = {
    2025: (date(2024, 10, 20), date(2025, 4, 14)),
    2026: (date(2025, 10, 19), date(2026, 4, 13)),
    2027: (date(2026, 10, 18), date(2027, 4, 12)),
}
CURRENT_SEASON = 2027
SCHEDULE_LOOKAHEAD_DAYS = 21
WORKERS = 8


def today_eastern() -> date:
    return datetime.now(EASTERN).date()


def season_label(season: int) -> str:
    return f"{season - 1}-{str(season)[-2:]}"


def _upsert_games(conn, games: list[dict]) -> None:
    for g in games:
        for side in ("home", "away"):
            t = g[side]
            conn.execute("INSERT OR REPLACE INTO teams(id, abbr, name, logo) VALUES(?,?,?,?)",
                         (t["id"], t["abbr"], t["name"], t["logo"]))
        conn.execute(
            """INSERT INTO games(id, season, season_type, date, start_utc, home_team_id, away_team_id,
                                 home_abbr, away_abbr, status, home_score, away_score)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET date=excluded.date, start_utc=excluded.start_utc,
                 status=excluded.status, home_score=excluded.home_score, away_score=excluded.away_score""",
            (g["id"], g["season"], g["season_type"], g["date"], g["start_utc"], g["home"]["id"],
             g["away"]["id"], g["home"]["abbr"], g["away"]["abbr"], g["status"], g["home_score"],
             g["away_score"]),
        )


def fetch_scoreboards(client: EspnClient, dates: list[date], force: bool = False) -> int:
    with get_conn() as conn:
        done = {r["date"] for r in conn.execute("SELECT date FROM scoreboard_fetch")}
    todo = [d.isoformat() for d in dates if force or d.isoformat() not in done]
    if not todo:
        return 0
    fetched = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(client.scoreboard, d): d for d in todo}
        for fut in as_completed(futures):
            d = futures[fut]
            try:
                games = [g for g in fut.result() if g["season_type"] == 2]
            except Exception as exc:  # noqa: BLE001 - keep ingesting other dates
                log.warning("scoreboard %s failed: %s", d, exc)
                continue
            with get_conn() as conn:
                _upsert_games(conn, games)
                # Only mark past dates as permanently fetched.
                if date.fromisoformat(d) < today_eastern() - timedelta(days=1):
                    conn.execute("INSERT OR REPLACE INTO scoreboard_fetch(date, fetched_at) VALUES(?,?)",
                                 (d, datetime.now(timezone.utc).isoformat()))
            fetched += 1
    return fetched


def fetch_box_scores(client: EspnClient) -> int:
    with get_conn() as conn:
        pending = [(r["id"], r["date"], r["season"]) for r in conn.execute(
            "SELECT id, date, season FROM games WHERE status='STATUS_FINAL' AND box_ingested=0")]
    if not pending:
        return 0
    log.info("fetching %d box scores", len(pending))
    count = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(client.box_score, gid): (gid, gdate, season) for gid, gdate, season in pending}
        for fut in as_completed(futures):
            gid, gdate, season = futures[fut]
            try:
                box = fut.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("box score %s failed: %s", gid, exc)
                continue
            with get_conn() as conn:
                _store_box(conn, gid, gdate, season, box)
            count += 1
            if count % 100 == 0:
                log.info("  %d/%d box scores", count, len(pending))
    return count


def _store_box(conn, gid: int, gdate: str, season: int, box: dict) -> None:
    team_abbr = {r["id"]: r["abbr"] for r in conn.execute("SELECT id, abbr FROM teams")}
    for p in box["players"]:
        conn.execute(
            """INSERT INTO players(id, name, position, team_id, team_abbr, headshot, last_game_date)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,
                 position=COALESCE(excluded.position, players.position),
                 headshot=COALESCE(excluded.headshot, players.headshot),
                 team_id=CASE WHEN excluded.last_game_date >= COALESCE(players.last_game_date,'')
                              THEN excluded.team_id ELSE players.team_id END,
                 team_abbr=CASE WHEN excluded.last_game_date >= COALESCE(players.last_game_date,'')
                              THEN excluded.team_abbr ELSE players.team_abbr END,
                 last_game_date=MAX(COALESCE(players.last_game_date,''), excluded.last_game_date)""",
            (p["id"], p["name"], p["position"], p["team_id"], team_abbr.get(p["team_id"]),
             p["headshot"], gdate),
        )
    cols = ["min", "pts", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "fg3m", "fg3a",
            "ftm", "fta", "oreb", "dreb", "pf"]
    for r in box["rows"]:
        conn.execute(
            f"""INSERT OR REPLACE INTO box_scores(game_id, player_id, team_id, opp_team_id, date, season,
                    home, starter, {', '.join(cols)})
                VALUES(?,?,?,?,?,?,?,?,{', '.join('?' * len(cols))})""",
            (gid, r["player_id"], r["team_id"], r["opp_team_id"], gdate, season, r["home"],
             r["starter"], *[r[c] for c in cols]),
        )
    conn.execute("UPDATE games SET box_ingested=1 WHERE id=?", (gid,))


def fetch_injuries(client: EspnClient) -> int:
    rows = client.injuries()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM injuries")
        for r in rows:
            conn.execute(
                """INSERT OR REPLACE INTO injuries(player_id, name, team_abbr, status, fantasy_status,
                       return_date, short_comment, reported_at, fetched_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (r["player_id"], r["name"], r["team_abbr"], r["status"], r["fantasy_status"],
                 r["return_date"], r["short_comment"], r["reported_at"], now),
            )
    return len(rows)


def _dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def run_full(seasons: list[int]) -> dict:
    init_db()
    client = EspnClient()
    today = today_eastern()
    try:
        for season in seasons:
            start, end = SEASON_WINDOWS[season]
            end = min(end, today + timedelta(days=SCHEDULE_LOOKAHEAD_DAYS))
            n = fetch_scoreboards(client, _dates(start, end))
            log.info("season %s: %d scoreboard dates fetched", season_label(season), n)
        summary = run_refresh(client)
    finally:
        client.close()
    return summary


def run_refresh(client: EspnClient | None = None) -> dict:
    """Refresh recent results, the upcoming schedule and the injury report."""
    init_db()
    own = client is None
    client = client or EspnClient()
    today = today_eastern()
    try:
        recent = _dates(today - timedelta(days=3), today + timedelta(days=SCHEDULE_LOOKAHEAD_DAYS))
        fetch_scoreboards(client, recent, force=True)
        boxes = fetch_box_scores(client)
        try:
            injuries = fetch_injuries(client)
        except Exception as exc:  # noqa: BLE001
            log.warning("injury fetch failed: %s", exc)
            injuries = -1
    finally:
        if own:
            client.close()
    now = datetime.now(timezone.utc).isoformat()
    set_meta("data_source", "espn")
    set_meta("last_refresh_utc", now)
    return {"box_scores": boxes, "injuries": injuries, "refreshed_at": now}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="only refresh recent data")
    parser.add_argument("--seasons", type=int, nargs="*", default=sorted(SEASON_WINDOWS))
    args = parser.parse_args()
    summary = run_refresh() if args.refresh else run_full(args.seasons)
    log.info("done: %s", summary)


if __name__ == "__main__":
    main()
