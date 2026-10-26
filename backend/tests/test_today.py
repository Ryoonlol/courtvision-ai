from datetime import timedelta

import pytest


def test_resolve_day(demo_db):
    from services.schedule import today
    from services.today import resolve_day
    t = today()
    assert resolve_day("today") == ("today", t)
    assert resolve_day("tomorrow") == ("tomorrow", t + timedelta(days=1))
    assert resolve_day((t + timedelta(days=1)).isoformat())[0] == "tomorrow"
    assert resolve_day("auto")[0] in {"today", "tomorrow"}
    with pytest.raises(ValueError):
        resolve_day("someday")


def test_today_view_splits_my_players(demo_db):
    from services import rosters, today
    from services.projections import project
    from services.schedule import week_window
    proj = project(week_window("next"))
    roster = rosters.create_roster("today-test", "mine", rosters.sample_roster(proj, 4, 12, 13))
    try:
        v = today.build("tomorrow", roster["id"])
        assert v["day"] == "tomorrow" and v["label"].startswith("Tomorrow")
        teams_playing = {g["away"] for g in v["games"]} | {g["home"] for g in v["games"]}
        m = v["my_team"]
        assert len(m["playing"]) + len(m["already_played"]) + len(m["not_playing"]) == m["size"] == 13
        for p in m["playing"]:
            assert p["team"] in teams_playing and p["opponent"] in teams_playing
            assert {"pts", "reb", "ast", "play_chance"} <= set(p)
        assert [p["value"] for p in m["playing"]] == sorted((p["value"] for p in m["playing"]), reverse=True)
        # pickups: playing, not rostered anywhere, outside the top-156 talent
        taken = {p for r in rosters.list_rosters() for p in r["player_ids"]}
        for p in v["pickups"]:
            assert p["player_id"] not in taken and p["team"] in teams_playing
            assert proj.players.at[p["player_id"], "pg_rank"] > 156
        assert all(i["team"] in teams_playing for i in v["injuries"])
        assert len(v["top"]) <= 10
    finally:
        rosters.delete_roster(roster["id"])


def test_today_api(demo_db):
    from fastapi.testclient import TestClient
    from main import app
    c = TestClient(app)
    r = c.get("/api/today?day=tomorrow")
    assert r.status_code == 200 and r.json()["my_team"] is None
    assert c.get("/api/today?day=nope").status_code == 400
