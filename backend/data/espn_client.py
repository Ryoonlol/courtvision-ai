"""Thin client for ESPN's public NBA JSON endpoints.

stats.nba.com / cdn.nba.com are frequently blocked for non-browser clients, so
CourtVision uses ESPN's public site API, which exposes real box scores,
schedules and injury reports. Every response is parsed into plain dicts and
cached in SQLite by the ingestion layer.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
EASTERN = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "CourtVisionAI/1.0 (local hackathon app)"}

STAT_FIELDS = {
    "MIN": "min", "PTS": "pts", "REB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk",
    "TO": "tov", "OREB": "oreb", "DREB": "dreb", "PF": "pf",
}
SPLIT_FIELDS = {"FG": ("fgm", "fga"), "3PT": ("fg3m", "fg3a"), "FT": ("ftm", "fta")}


class EspnClient:
    def __init__(self, timeout: float = 20.0, retries: int = 3):
        self._client = httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True)
        self._retries = retries

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = self._client.get(f"{BASE}/{path}", params=params)
                if resp.status_code == 200:
                    return resp.json()
                last = RuntimeError(f"ESPN {path} -> HTTP {resp.status_code}")
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
            time.sleep(0.6 * (attempt + 1))
        raise last or RuntimeError("ESPN request failed")

    # ------------------------------------------------------------------ schedule
    def scoreboard(self, date_str: str) -> list[dict]:
        """Games for one US/Eastern date (YYYY-MM-DD)."""
        data = self._get("scoreboard", {"dates": date_str.replace("-", ""), "limit": 100})
        games = []
        for ev in data.get("events", []):
            comp = ev["competitions"][0]
            teams = {c["homeAway"]: c for c in comp["competitors"]}
            home, away = teams.get("home"), teams.get("away")
            if not home or not away:
                continue
            season = ev.get("season", {})
            start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            games.append({
                "id": int(ev["id"]),
                "season": int(season.get("year", 0)),
                "season_type": int(season.get("type", 0)),
                "date": start.astimezone(EASTERN).date().isoformat(),
                "start_utc": start.isoformat(),
                "status": ev["status"]["type"]["name"],
                "home": _team(home), "away": _team(away),
                "home_score": _int(home.get("score")), "away_score": _int(away.get("score")),
            })
        return games

    # ----------------------------------------------------------------- box score
    def box_score(self, game_id: int) -> dict:
        data = self._get("summary", {"event": game_id})
        header = data["header"]["competitions"][0]
        side = {c["team"]["id"]: c["homeAway"] for c in header["competitors"]}
        team_ids = [int(t) for t in side]
        rows, players = [], []
        for team_block in data.get("boxscore", {}).get("players", []):
            team_id = int(team_block["team"]["id"])
            opp_id = next(t for t in team_ids if t != team_id)
            home = side.get(str(team_id)) == "home"
            for stat_block in team_block.get("statistics", []):
                labels = stat_block.get("labels") or stat_block.get("names") or []
                for ath in stat_block.get("athletes", []):
                    a = ath.get("athlete") or {}
                    pid = _athlete_id(a)
                    if pid is None:
                        continue
                    players.append({
                        "id": pid,
                        "name": a.get("displayName"),
                        "position": (a.get("position") or {}).get("abbreviation"),
                        "headshot": (a.get("headshot") or {}).get("href"),
                        "team_id": team_id,
                    })
                    if ath.get("didNotPlay") or not ath.get("stats"):
                        continue
                    parsed = _parse_stats(labels, ath["stats"])
                    if parsed is None or parsed["min"] <= 0:
                        continue
                    parsed.update({"player_id": pid, "team_id": team_id, "opp_team_id": opp_id,
                                   "home": int(home), "starter": int(bool(ath.get("starter")))})
                    rows.append(parsed)
        return {"rows": rows, "players": players}

    # ------------------------------------------------------------------ injuries
    def injuries(self) -> list[dict]:
        data = self._get("injuries")
        out = []
        for team in data.get("injuries", []):
            for inj in team.get("injuries", []):
                ath = inj.get("athlete") or {}
                pid = _athlete_id(ath)
                if pid is None:
                    continue
                details = inj.get("details") or {}
                out.append({
                    "player_id": pid,
                    "name": ath.get("displayName"),
                    "team_abbr": ((ath.get("team") or {}).get("abbreviation")),
                    "status": inj.get("status"),
                    "fantasy_status": ((details.get("fantasyStatus") or {}).get("abbreviation")),
                    "return_date": details.get("returnDate"),
                    "short_comment": inj.get("shortComment"),
                    "reported_at": inj.get("date"),
                })
        return out


def _team(comp: dict) -> dict:
    t = comp["team"]
    return {"id": int(t["id"]), "abbr": t.get("abbreviation"), "name": t.get("displayName"),
            "logo": t.get("logo")}


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _athlete_id(ath: dict) -> int | None:
    if ath.get("id"):
        return int(ath["id"])
    for link in ath.get("links", []):
        m = re.search(r"/id/(\d+)", link.get("href", ""))
        if m:
            return int(m.group(1))
    return None


def _parse_stats(labels: list[str], values: list[str]) -> dict | None:
    out: dict[str, float] = {}
    for label, raw in zip(labels, values):
        if label in STAT_FIELDS:
            try:
                out[STAT_FIELDS[label]] = float(raw)
            except ValueError:
                out[STAT_FIELDS[label]] = 0.0
        elif label in SPLIT_FIELDS:
            made, att = SPLIT_FIELDS[label]
            try:
                m, a = raw.split("-")
                out[made], out[att] = float(m), float(a)
            except ValueError:
                out[made], out[att] = 0.0, 0.0
    required = {"min", "pts", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "fg3m", "ftm", "fta"}
    if not required.issubset(out):
        return None
    for k in ("oreb", "dreb", "pf", "fg3a"):
        out.setdefault(k, 0.0)
    return out
