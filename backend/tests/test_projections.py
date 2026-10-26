from datetime import date, timedelta

import numpy as np
import pytest

from core.categories import MODEL_STATS
from services.projections import availability
from services.schedule import week_window


def test_week_windows():
    sat = date(2026, 10, 24)
    nxt = week_window("next", sat)
    assert nxt.start == date(2026, 10, 26) and nxt.end == date(2026, 11, 1)
    cur = week_window("current", sat)
    assert cur.start == sat and cur.end == date(2026, 10, 25)
    explicit = week_window("2026-11-04")
    assert explicit.start == date(2026, 11, 2)


def test_availability_rules():
    ref = date(2026, 10, 24)
    g = date(2026, 10, 28)
    assert availability(None, g, None, ref) == (1.0, "Active")
    out = {"status": "Out", "fantasy_status": "OUT", "return_date": "2026-11-20", "reported_at": "2026-10-19T10:00Z"}
    assert availability(out, g, None, ref)[0] == 0.0
    assert availability(out, date(2026, 11, 21), None, ref)[0] == pytest.approx(0.6)
    dtd = {"status": "Day-To-Day", "fantasy_status": "GTD", "return_date": None, "reported_at": "2026-10-23T10:00Z"}
    assert availability(dtd, ref + timedelta(days=1), None, ref)[0] == pytest.approx(0.6)
    assert availability(dtd, ref + timedelta(days=5), None, ref)[0] == pytest.approx(0.85)
    # played after the report -> report is stale
    assert availability(out, g, date(2026, 10, 22), ref)[0] == 1.0


def test_weekly_projection_aggregates_correctly(demo_db):
    from services.projections import project
    proj = project(week_window("next"))
    players, games = proj.players, proj.games
    assert len(players) > 100
    assert proj.methods["pts"] == "baseline"  # no trained model in the test DB
    pid = players[players["games"] >= 2].index[0]
    rows = games[games["player_id"] == pid]
    for s in MODEL_STATS:
        assert players.loc[pid, s] == pytest.approx((rows[f"p_{s}"] * rows["avail"]).sum())
    # percentages are total makes / total attempts
    assert players.loc[pid, "fg_pct"] == pytest.approx(players.loc[pid, "fgm"] / players.loc[pid, "fga"])
    # games column counts scheduled games in the window
    assert players.loc[pid, "games"] == len(rows)
    # ranks are 1..N by value
    ranked = players.sort_values("rank")
    assert ranked["rank"].iloc[0] == 1
    assert np.all(np.diff(ranked["value"].to_numpy()) <= 1e-9)
    # uncertainty: SDs positive, intervals ordered
    assert (players.loc[players["games"] > 0, "sd_pts"] > 0).all()
    assert (players["value_lo"] <= players["value_hi"]).all()


def test_players_without_games_project_zero_volume(demo_db):
    from services.projections import project
    proj = project(week_window("next"))
    df = proj.players
    idle = df[df["games"] == 0]
    if len(idle):
        assert (idle[["pts", "reb", "fga"]] == 0).all().all()
    active = df[df["games"] > 0]
    assert active["fg_pct"].between(0, 1).all()
    assert active["ft_pct"].dropna().between(0, 1).all()
