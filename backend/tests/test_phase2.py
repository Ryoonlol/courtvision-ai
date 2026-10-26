from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from core.categories import CATEGORIES
from services.schedule import week_window


@pytest.fixture(scope="module")
def proj(demo_db):
    from services.projections import project
    return project(week_window("next"))


@pytest.fixture(scope="module")
def roster(proj):
    from services import rosters
    return rosters.sample_roster(proj, slot=5, teams=12, size=13)


# ----------------------------------------------------------------------------- rosters
def test_snake_draft_picks():
    from services.rosters import snake_draft_picks
    assert snake_draft_picks(5, 12, 4) == [5, 20, 29, 44]
    assert snake_draft_picks(1, 10, 3) == [1, 20, 21]
    with pytest.raises(ValueError):
        snake_draft_picks(13, 12, 2)


def test_sample_roster_size_and_uniqueness(roster):
    assert len(roster) == 13 and len(set(roster)) == 13


def test_roster_crud_and_validation(demo_db):
    from services import rosters
    r = rosters.create_roster("Test", "mine", [1, 2, 3])
    assert r["player_ids"] == [1, 2, 3]
    r = rosters.update_roster(r["id"], name="Renamed", player_ids=[3, 2])
    assert r["name"] == "Renamed" and r["player_ids"] == [3, 2]
    assert 3 in rosters.rostered_elsewhere(None) and 3 not in rosters.rostered_elsewhere(r["id"])
    with pytest.raises(rosters.RosterError):
        rosters.create_roster("Dupes", "mine", [1, 1])
    with pytest.raises(rosters.RosterError):
        rosters.create_roster("Too many", "mine", list(range(rosters.MAX_ROSTER + 1)))
    with pytest.raises(rosters.RosterError):
        rosters.create_roster("  ", "mine", [])
    rosters.delete_roster(r["id"])
    assert rosters.get_roster(r["id"]) is None
    with pytest.raises(KeyError):
        rosters.delete_roster(r["id"])


# ----------------------------------------------------------------------------- team analyzer
def test_team_profile_sums_player_values(proj, roster):
    from services.team import team_profile
    prof = team_profile(proj, roster, "week")
    players = proj.players.loc[roster]
    for c in prof["categories"]:
        assert c["z"] == pytest.approx(players[f"z_{c['key']}"].sum())
    fg = next(c for c in prof["categories"] if c["key"] == "fg_pct")
    assert fg["value"] == pytest.approx(players["fgm"].sum() / players["fga"].sum())
    assert fg["average_team"] == pytest.approx(proj.params.pool_pct["fg_pct"])
    assert prof["totals"]["pts"] == pytest.approx(players["pts"].sum())
    assert len(prof["strongest"]) == 3 and len(prof["weakest"]) == 3


def test_season_basis_uses_per_game_values(proj, roster):
    from services.team import team_profile
    prof = team_profile(proj, roster, "season")
    assert prof["totals"]["reb"] == pytest.approx(proj.players.loc[roster, "pg_reb"].sum())


def test_need_weights_favor_weak_and_zero_punts(proj, roster):
    from services.team import need_weights, team_profile
    prof = team_profile(proj, roster, "week")
    w = need_weights(prof, {"ft_pct"})
    assert w["ft_pct"] == 0
    weakest, strongest = prof["weakest"][0], prof["strongest"][0]
    if weakest != "ft_pct" and strongest != "ft_pct":
        assert w[weakest] >= w[strongest]
    assert all(0 <= v <= 2.0 for v in w.values())


def test_recommendations_only_free_agents(proj, roster):
    from services.team import recommendations
    other = {int(proj.players.index[-1])}
    recs = recommendations(proj, roster, "week", set(), exclude=other, assume_rostered=100)
    assert recs
    ids = {r["player_id"] for r in recs}
    assert not ids & set(roster) and not ids & other
    assert all(proj.players.at[r["player_id"], "rank"] > 100 for r in recs)
    assert all(r["drop_player_id"] in roster for r in recs)
    assert [r["fit_score"] for r in recs] == sorted([r["fit_score"] for r in recs], reverse=True)


# ----------------------------------------------------------------------------- trade analyzer
def _targets(proj, roster, n):
    return [int(p) for p in proj.players.sort_values("pg_value", ascending=False).index if p not in roster][:n]


def test_trade_validation(proj, roster):
    from services.trade import TradeError, evaluate
    t = _targets(proj, roster, 4)
    with pytest.raises(TradeError):
        evaluate(proj, roster, [t[0]], [roster[0]])            # giving someone you don't own
    with pytest.raises(TradeError):
        evaluate(proj, roster, roster[:4], t[:1])              # 4-for-1 not supported
    with pytest.raises(TradeError):
        evaluate(proj, roster, roster[:1], [roster[1]])        # receiving your own player
    with pytest.raises(TradeError):
        evaluate(proj, roster, [], t[:1])


@pytest.mark.parametrize("n_give,n_get", [(1, 1), (2, 1), (2, 2), (3, 2)])
def test_trade_formats_keep_roster_size(proj, roster, n_give, n_get):
    from services.trade import evaluate
    res = evaluate(proj, roster, roster[:n_give], _targets(proj, roster, n_get), "season")
    assert res["format"] == f"{n_give}-for-{n_get}"
    assert len(res["roster_after"]) == len(roster)
    adds = [a for a in res["adjustments"] if a["type"] == "add_replacement"]
    assert len(adds) == n_give - n_get
    for c in res["categories"]:
        assert c["z_delta"] == pytest.approx(c["z_after"] - c["z_before"])
    assert res["value_delta"] == pytest.approx(sum(c["z_delta"] for c in res["categories"]))


def test_uneven_trade_forces_drop(proj, roster):
    from services.trade import evaluate
    res = evaluate(proj, roster, roster[-1:], _targets(proj, roster, 2), "season")
    drops = [a for a in res["adjustments"] if a["type"] == "drop"]
    assert len(drops) == 1 and len(res["roster_after"]) == len(roster)


def test_trading_for_better_player_is_positive(proj, roster):
    from services.trade import evaluate
    worst = min(roster, key=lambda p: proj.players.at[p, "pg_value"])
    best = _targets(proj, roster, 1)
    res = evaluate(proj, roster, [worst], best, "season")
    assert res["value_delta"] > 0 and res["verdict"] in {"accept", "fair"}
    back = evaluate(proj, res["roster_after"], best, [worst], "season")
    assert back["value_delta"] == pytest.approx(-res["value_delta"])


def test_trade_fallback_insight_is_grounded(proj, roster):
    from services import trade
    from services.gemini_service import grounding_check
    res = trade.evaluate(proj, roster, roster[:2], _targets(proj, roster, 2), "season")
    payload = trade.ai_payload(res)
    insight = trade.fallback_insight(payload)
    assert insight.verdict == res["verdict"]
    assert grounding_check(insight.model_dump(), payload)["passed"]


# ----------------------------------------------------------------------------- history
def test_weekly_totals_match_box_scores(demo_db):
    from data import repository as repo
    from services import history
    wt = history.weekly_totals()
    box = repo.box_scores()
    assert wt["games"].sum() == len(box)
    assert wt["pts"].sum() == pytest.approx(box["pts"].sum())
    assert (pd.to_datetime(wt["week_start"]).dt.weekday == 0).all()


def test_week_rankings_and_trend(demo_db):
    from services import history
    weeks = history.available_weeks()
    past = next(w for w in weeks if not w["in_progress"])
    res = history.week_rankings(pd.Timestamp(past["week_start"]).date())
    ranks = [r["rank"] for r in res["rows"]]
    assert ranks == sorted(ranks)
    top = res["rows"][0]
    assert top["fg_pct"] == pytest.approx(top["fgm"] / top["fga"])
    assert sum(top[f"z_{c.key}"] for c in CATEGORIES) == pytest.approx(top["value"])
    trend = history.player_trend(top["player_id"])
    assert trend["weeks"] and all(w["rank"] >= 1 for w in trend["weeks"])


def test_backtest_uses_only_prior_games(demo_db):
    from data import repository as repo
    from services import history
    from services.features import player_features
    weeks = [w for w in history.available_weeks() if not w["in_progress"]]
    start = pd.Timestamp(weeks[5]["week_start"])
    bt = history.backtest(start.date())
    assert bt["players"] > 50 and -1 <= bt["value_rank_spearman"] <= 1
    # recompute one player's baseline from games strictly before the week
    box = repo.box_scores()
    wt = history.weekly_totals()
    row = wt[wt["week_start"] == start].iloc[0]
    before = box[(box["date"] < start) & (box["player_id"] == row["player_id"])]
    ph = pd.DataFrame([{"player_id": row["player_id"], "game_id": -1, "date": start, "season": row["season"],
                        "team_id": row["team_id"], "opp_team_id": -1, "home": 0}])
    state = player_features(before, ph).query("placeholder").iloc[0]
    assert not before.empty and (before["date"] < start).all()
    assert np.isfinite(state["base_pts"])
    end = start + timedelta(days=7)
    assert box[(box["date"] >= start) & (box["date"] < end)]["player_id"].nunique() >= bt["players"]


# ----------------------------------------------------------------------------- API
def test_phase2_api_endpoints(demo_db):
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)  # no context manager -> background bootstrap does not run
    r = client.post("/api/rosters/sample", json={"name": "API Team", "draft_slot": 3})
    assert r.status_code == 201
    roster = r.json()
    ids = roster["player_ids"]
    assert len(ids) == 13
    res = client.post("/api/team/analyze", json={"player_ids": ids, "roster_id": roster["id"], "punt": ["tov"]})
    assert res.status_code == 200 and res.json()["weights"]["tov"] == 0
    assert client.post("/api/team/analyze", json={"player_ids": ids, "punt": ["bogus"]}).status_code == 400
    ai = client.post("/api/ai/team", json={"player_ids": ids})
    assert ai.status_code == 200 and ai.json()["source"] == "fallback"
    bad = client.post("/api/trade/analyze", json={"roster_player_ids": ids, "give": [ids[0]], "get": [ids[1]]})
    assert bad.status_code == 400
    weeks = client.get("/api/history/weeks").json()
    assert client.get(f"/api/history/week?start={weeks[3]['week_start']}").status_code == 200
    assert client.get("/api/history/week?start=1990-01-01").status_code == 404
    assert client.delete(f"/api/rosters/{roster['id']}").status_code == 204
    assert client.get(f"/api/rosters/{roster['id']}").status_code == 404
