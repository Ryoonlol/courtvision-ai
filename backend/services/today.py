"""Today / Tomorrow: everything a fantasy manager checks before tip-off, in one fast call.

No Gemini here on purpose: this page must load instantly. It reuses the statistical projection engine
on a single-day window and returns the slate, your players, the best pickups and injury flags.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from core.categories import CATEGORIES
from data import repository as repo
from data.espn_client import EASTERN
from services import rosters
from services.projections import Projection, project
from services.schedule import Window, today

STAT_KEYS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
ASSUME_ROSTERED = 156


def resolve_day(day: str | None) -> tuple[str, date]:
    """'today' | 'tomorrow' | ISO date | None/'auto' (today if games are still to be played, else tomorrow)."""
    t = today()
    if day in (None, "", "auto"):
        g = repo.games()
        left = g[(g["date"].dt.date == t) & (g["status"] != "STATUS_FINAL")]
        return ("today", t) if len(left) else ("tomorrow", t + timedelta(days=1))
    if day == "today":
        return "today", t
    if day == "tomorrow":
        return "tomorrow", t + timedelta(days=1)
    d = date.fromisoformat(day)
    return ("today" if d == t else "tomorrow" if d == t + timedelta(days=1) else "date"), d


def day_window(d: date, key: str) -> Window:
    name = {"today": "Today", "tomorrow": "Tomorrow"}.get(key, f"{d:%a %b %-d}")
    return Window(f"day:{d.isoformat()}", d, d, f"{name} · {d:%a %b %-d}", d - timedelta(days=d.weekday()))


def _tip(start_utc: str | None) -> str | None:
    if not start_utc:
        return None
    return datetime.fromisoformat(start_utc).astimezone(EASTERN).strftime("%-I:%M %p")


def _games(d: date) -> list[dict]:
    g = repo.games()
    g = g[g["date"].dt.date == d].sort_values(["start_utc", "id"])
    teams = repo.teams()
    logo = lambda tid: teams.at[tid, "logo"] if tid in teams.index else None  # noqa: E731
    return [{"game_id": int(r["id"]), "tip": _tip(r["start_utc"]), "status": _status(r["status"]),
             "away": r["away_abbr"], "home": r["home_abbr"],
             "away_logo": logo(r["away_team_id"]), "home_logo": logo(r["home_team_id"]),
             "away_score": _int(r["away_score"]), "home_score": _int(r["home_score"])} for _, r in g.iterrows()]


def _status(raw: str) -> str:
    return {"STATUS_FINAL": "final", "STATUS_SCHEDULED": "scheduled"}.get(raw, "live")


def _int(v):
    return None if pd.isna(v) else int(v)


def _line(proj: Projection, pid: int, game_row: pd.Series | None) -> dict:
    """One player's projected line for the day (per-game projection; value = fantasy value)."""
    r = proj.players.loc[pid]
    teams = repo.teams()
    out = {"player_id": int(pid), "name": r["name"], "team": r["team_abbr"], "position": r["position"],
           "headshot": r["headshot"], "status": r["status"], "value": round(float(r["value"]), 2)}
    if game_row is not None:
        a = float(game_row["avail"])
        out.update({
            "opponent": teams.at[game_row["opp_team_id"], "abbr"] if game_row["opp_team_id"] in teams.index else "?",
            "home": bool(game_row["home"]), "play_chance": round(a, 2),
            "min": round(float(game_row["p_min"]), 1),
            **{s: round(float(game_row[f"p_{s}"]), 1) for s in STAT_KEYS},
            "fg_pct": _pct(game_row["p_fgm"], game_row["p_fga"]), "ft_pct": _pct(game_row["p_ftm"], game_row["p_fta"]),
        })
    return out


def _pct(m, a) -> float | None:
    return round(float(m) / float(a), 3) if a and a > 0 else None


def build(day: str | None = None, roster_id: int | None = None) -> dict:
    key, d = resolve_day(day)
    window = day_window(d, key)
    proj = project(window)
    rows = proj.games.set_index("player_id")
    games = _games(d)

    # top projected players for the day (by fantasy value of the single game)
    playing = proj.players[proj.players["games"] > 0].sort_values("value", ascending=False)
    top = [_line(proj, pid, rows.loc[pid] if pid in rows.index else None) for pid in playing.index[:10]]

    # my players
    mine = None
    roster = rosters.get_roster(roster_id) if roster_id else None
    if roster:
        box = repo.box_scores()
        done = box[box["date"].dt.date == d].set_index("player_id")
        players_info = repo.players()
        plays, played, off = [], [], []
        for pid in roster["player_ids"]:
            if pid in rows.index and pid in proj.players.index:
                plays.append(_line(proj, pid, rows.loc[pid]))
            elif pid in done.index:
                b = done.loc[pid]
                played.append({"player_id": int(pid), "name": players_info.at[pid, "name"] if pid in players_info.index else str(pid),
                               "headshot": players_info.at[pid, "headshot"] if pid in players_info.index else None,
                               **{s: int(b[s]) for s in ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "min"]}})
            else:
                off.append({"player_id": int(pid), "name": players_info.at[pid, "name"] if pid in players_info.index else str(pid),
                            "headshot": players_info.at[pid, "headshot"] if pid in players_info.index else None})
        plays.sort(key=lambda x: -x["value"])
        mine = {"roster_id": roster["id"], "name": roster["name"], "size": len(roster["player_ids"]),
                "playing": plays, "already_played": played, "not_playing": off}

    # best pickups: playing today, likely to play, not on any saved roster, outside the top-156 talent
    taken = {p for r in rosters.list_rosters() for p in r["player_ids"]}
    fa = playing[(playing["pg_rank"] > ASSUME_ROSTERED) & ~playing.index.isin(list(taken))]
    fa = fa[fa.index.map(lambda p: float(rows.loc[p]["avail"]) if p in rows.index else 0.0) >= 0.6]
    pickups = [_line(proj, pid, rows.loc[pid]) | {"helps": _helps(proj, pid)} for pid in fa.index[:6]]

    # injury watch: players on teams playing that day (your players first, then notable ones)
    inj = repo.injuries()
    teams_playing = {g["away"] for g in games} | {g["home"] for g in games}
    mine_ids = set(roster["player_ids"]) if roster else set()
    watch = []
    pinfo = repo.players()
    for pid, r in inj.iterrows():
        team = pinfo.at[pid, "team_abbr"] if pid in pinfo.index else r["team_abbr"]
        if team not in teams_playing:
            continue
        notable = pid in mine_ids or (pid in proj.players.index and proj.players.at[pid, "pg_rank"] <= 150)
        if not notable:
            continue
        watch.append({"player_id": int(pid), "name": r["name"], "team": team, "mine": pid in mine_ids,
                      "status": r["status"], "return_date": r["return_date"],
                      "note": (r["short_comment"] or "")[:140]})
    watch.sort(key=lambda w: (not w["mine"], w["status"] != "Out", w["name"]))

    return {
        "day": key, "date": d.isoformat(), "label": window.label,
        "games": games, "games_left": sum(g["status"] != "final" for g in games),
        "my_team": mine, "top": top, "pickups": pickups, "injuries": watch[:12],
        "tomorrow": (d + timedelta(days=1)).isoformat(),
    }


def _helps(proj: Projection, pid: int) -> list[str]:
    r = proj.players.loc[pid]
    zs = sorted(((c.label, float(r[f"pg_z_{c.key}"])) for c in CATEGORIES), key=lambda x: -x[1])
    return ["low TO" if lb == "TO" else lb for lb, z in zs[:2] if z > 0.3]
