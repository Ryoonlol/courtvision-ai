"""Fantasy-week windows (Monday-Sunday, US/Eastern) and schedule helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from data import repository as repo
from data.espn_client import EASTERN


@dataclass(frozen=True)
class Window:
    key: str
    start: date
    end: date
    label: str
    week_start: date  # the Monday of the fantasy week

    def as_dict(self) -> dict:
        return {"key": self.key, "start": self.start.isoformat(), "end": self.end.isoformat(),
                "label": self.label, "week_start": self.week_start.isoformat()}


def today() -> date:
    return datetime.now(EASTERN).date()


def week_window(which: str = "next", ref: date | None = None) -> Window:
    """'current' = remaining days of this week (from today), 'next' = next Mon-Sun,
    or an ISO date which selects the full week containing it."""
    ref = ref or today()
    monday = ref - timedelta(days=ref.weekday())
    if which == "current":
        return Window("current", ref, monday + timedelta(days=6),
                      f"This week (remaining) · {_fmt(ref)} – {_fmt(monday + timedelta(days=6))}", monday)
    if which == "next":
        start = monday + timedelta(days=7)
        return Window("next", start, start + timedelta(days=6),
                      f"Next week · {_fmt(start)} – {_fmt(start + timedelta(days=6))}", start)
    d = date.fromisoformat(which)
    start = d - timedelta(days=d.weekday())
    return Window(start.isoformat(), start, start + timedelta(days=6),
                  f"Week of {_fmt(start)}", start)


def _fmt(d: date) -> str:
    return d.strftime("%b %-d")


def upcoming_team_games(window: Window) -> pd.DataFrame:
    """Unplayed team-games inside the window (finished games are already in the box scores)."""
    tg = repo.team_games_between(window.start, window.end)
    return tg[tg["status"] != "STATUS_FINAL"].reset_index(drop=True)


def schedule_summary(window: Window) -> dict:
    tg = upcoming_team_games(window)
    teams = repo.teams()
    per_day = (tg.groupby(tg["date"].dt.date)["game_id"].nunique().reset_index()
               .rename(columns={"date": "date", "game_id": "games"}))
    per_team = tg.groupby("team_id").size().rename("games").reset_index()
    per_team["abbr"] = per_team["team_id"].map(teams["abbr"])
    per_team["logo"] = per_team["team_id"].map(teams["logo"])
    return {
        "window": window.as_dict(),
        "games_by_day": [{"date": d.isoformat(), "weekday": d.strftime("%a"), "games": int(g)}
                         for d, g in zip(per_day["date"], per_day["games"])],
        "games_by_team": per_team.sort_values(["games", "abbr"], ascending=[False, True])
                                 .drop(columns="team_id").to_dict("records"),
        "total_games": int(tg["game_id"].nunique()),
    }
