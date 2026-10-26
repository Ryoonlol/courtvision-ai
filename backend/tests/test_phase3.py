from datetime import date

import numpy as np
import pandas as pd
import pytest

from services.schedule import week_window


@pytest.fixture(scope="module")
def proj(demo_db):
    from services.projections import project
    return project(week_window("next"))


@pytest.fixture(scope="module")
def teams(proj):
    from services import rosters
    return rosters.sample_roster(proj, 3, 12, 13), rosters.sample_roster(proj, 10, 12, 13)


# ----------------------------------------------------------------------------- matchup
def test_simulated_percentages_aggregate_makes_over_attempts(proj, teams):
    from services.matchup import simulate_team, team_rows
    rows, _ = team_rows(proj, teams[0])
    t = simulate_team(rows, 2000, np.random.default_rng(1))
    assert (t["fgm"] <= t["fga"]).all() and (t["ftm"] <= t["fta"]).all()
    pct = t["fgm"] / t["fga"]
    expected = (rows["p_fgm"] * rows["avail"]).sum() / (rows["p_fga"] * rows["avail"]).sum()
    assert pct.mean() == pytest.approx(expected, abs=0.02)
    for s in ("pts", "reb", "stl"):
        assert (t[s] == np.round(t[s])).all() and (t[s] >= 0).all()


def test_turnovers_lower_is_better_in_comparison():
    from services.matchup import compare
    n = 100
    base = {k: np.full(n, 10.0) for k in ["pts", "reb", "ast", "stl", "blk", "fg3m", "fgm", "fga", "ftm", "fta"]}
    a = base | {"tov": np.full(n, 5.0)}
    b = base | {"tov": np.full(n, 9.0)}
    res = compare(a, b, n)
    tov = next(c for c in res["categories"] if c["key"] == "tov")
    assert tov["p_win"] == 1.0
    pts = next(c for c in res["categories"] if c["key"] == "pts")
    assert pts["p_tie"] == 1.0
    assert res["p_win"] == 1.0  # 1 win, 8 ties


def test_matchup_symmetry_and_distribution(proj, teams):
    from services.matchup import simulate
    res = simulate(proj, teams[0], teams[0], n=6000, seed=3)
    assert abs(res["p_win"] - res["p_loss"]) < 0.04
    assert sum(res["cats_won_distribution"]) == pytest.approx(1.0)
    assert res["expected_cats_won"] == pytest.approx(sum(k * p for k, p in enumerate(res["cats_won_distribution"])), abs=1e-6)
    assert res["p_win"] + res["p_tie"] + res["p_loss"] == pytest.approx(1.0)


def test_much_stronger_team_is_favored(proj):
    from services.matchup import simulate
    active = proj.players[proj.players["games"] >= 3]
    strong = active.index[:13].tolist()
    weak = active.index[-13:].tolist()
    res = simulate(proj, strong, weak, n=3000)
    assert res["p_win"] > 0.9 and res["expected_cats_won"] > 6


def test_everyone_out_scores_nothing(proj, teams):
    from services.matchup import simulate
    res = simulate(proj, teams[0], teams[1], n=1000, a_out=set(teams[0]))
    assert res["team_a"]["expected_games"] == 0
    for c in res["categories"]:
        if c["key"] in ("pts", "reb", "ast"):
            assert c["p_win"] == 0.0


def test_current_week_includes_banked_stats(demo_db, teams):
    from data import repository as repo
    from services.matchup import banked_totals, simulate
    from services.projections import project
    cur = project(week_window("current"))
    mine = teams[0]
    bank = banked_totals(cur, mine)
    box = repo.box_scores()
    ws, end = pd.Timestamp(cur.window.week_start), pd.Timestamp(cur.window.end)
    expected = box[box["player_id"].isin(mine) & (box["date"] >= ws) & (box["date"] <= end)]["pts"].sum()
    assert bank["pts"] == pytest.approx(expected)
    res = simulate(cur, mine, teams[1], n=500, a_out=set(mine))  # nobody plays the rest of the week
    pts = next(c for c in res["categories"] if c["key"] == "pts")
    assert pts["mean_a"] == pytest.approx(bank["pts"])


# ----------------------------------------------------------------------------- what-if
def test_whatif_apply_validation():
    from services.whatif import ScenarioError, apply
    assert apply([1, 2, 3], add=[4], drop=[1]) == [2, 3, 4]
    with pytest.raises(ScenarioError):
        apply([1, 2], add=[], drop=[9])
    with pytest.raises(ScenarioError):
        apply([1, 2], add=[2], drop=[])


def test_whatif_injury_lowers_win_probability(proj, teams):
    from services.whatif import run
    mine, opp = teams
    best = max(mine, key=lambda p: proj.players.at[p, "value"])
    res = run(proj, mine, opp, out=[best], n=4000)
    assert res["delta_p_win"] == pytest.approx(res["after"]["p_win"] - res["before"]["p_win"])
    assert res["after"]["expected_games"] < res["before"]["expected_games"]
    assert res["delta_expected_cats"] < 0


def test_priority_suggestions_respect_rosters(proj, teams):
    from services.whatif import suggest_moves
    mine, opp = teams
    res = suggest_moves(proj, mine, opp, ["stl"], candidates=4, n=1000)
    assert len(res["moves"]) == 4
    ids = {m["player_id"] for m in res["moves"]}
    assert not ids & set(mine) and not ids & set(opp)
    gains = [m["priority_gain"] for m in res["moves"]]
    assert gains == sorted(gains, reverse=True)


# ----------------------------------------------------------------------------- streaming
def test_daily_usage_and_usable_games(proj, teams):
    from services.streaming import daily_usage, optimize
    mine = teams[0]
    usage = daily_usage(proj, mine, 10)
    assert len(usage) == 7
    assert (usage["open_slots"] == np.clip(10 - usage["my_players"], 0, None)).all()
    wide = optimize(proj, mine, slots=15)
    tight = optimize(proj, mine, slots=1)
    assert wide["candidates"] and all(c["usable_games"] <= c["games"] + 1e-9 for c in wide["candidates"])
    assert wide["candidates"][0]["stream_value"] >= tight["candidates"][0]["stream_value"]
    vals = [c["stream_value"] for c in wide["candidates"]]
    assert vals == sorted(vals, reverse=True)


def test_custom_waiver_list(proj, teams):
    from services.streaming import optimize
    avail = [int(p) for p in proj.players.index if p not in teams[0]][100:106]
    res = optimize(proj, teams[0], available=avail)
    assert res["mode"] == "custom"
    assert {c["player_id"] for c in res["candidates"]} <= set(avail)


# ----------------------------------------------------------------------------- breakouts
def test_breakout_scores_and_windows(demo_db):
    from services import breakouts
    res = breakouts.detect(limit=10)
    assert res["candidates"]
    scores = [c["score"] for c in res["candidates"]]
    assert scores == sorted(scores, reverse=True)
    for c in res["candidates"]:
        assert sum(c["components"].values()) == pytest.approx(c["score"], abs=1e-9)
        assert c["deltas"]["minutes"] == pytest.approx(c["recent"]["min"] - c["baseline"]["min"], abs=0.02)
    assert breakouts.fallback_insight(breakouts.ai_payload(res)).players


def test_breakouts_as_of_ignores_future_games(demo_db):
    from data import repository as repo
    from services import breakouts
    cut = repo.box_scores()["date"].quantile(0.5).date()
    res = breakouts.detect(as_of=cut, limit=5)
    assert pd.Timestamp(res["as_of"]).date() <= cut
    assert all(pd.Timestamp(c["last_game"]).date() <= cut for c in res["candidates"])


# ----------------------------------------------------------------------------- accuracy
def test_accuracy_matches_single_week_backtest(demo_db):
    from services import accuracy, history
    res = accuracy.compute()
    assert res["weeks"] and set(res["overall"]) == {"weighted", "naive"}
    wk = res["weeks"][len(res["weeks"]) // 2]
    bt = history.backtest(date.fromisoformat(wk["week_start"]))
    assert wk["weighted"]["spearman"] == pytest.approx(bt["value_rank_spearman"], abs=1e-9)
    assert wk["weighted"]["pts"] == pytest.approx(bt["category_mae"]["pts"]["mae"], abs=1e-9)
    assert -1 <= res["overall"]["weighted"]["spearman"] <= 1


# ----------------------------------------------------------------------------- assistant
def test_category_and_player_extraction(proj):
    from services.assistant import Ctx, mentioned_categories, mentioned_players
    assert mentioned_categories("best for steals and blocks?") == ["stl", "blk"]
    assert mentioned_categories("top rebounders") == ["reb"]
    assert mentioned_categories("he has three games") == []
    a, b = proj.players["name"].iloc[0], proj.players["name"].iloc[5]
    assert mentioned_players(Ctx(proj), f"Is {a} better than {b}?")[:2] == [a, b]


def test_fallback_routes_to_tools(proj, teams):
    from services import rosters
    from services.assistant import ask
    mine = rosters.create_roster("chat-mine", "mine", teams[0])
    opp = rosters.create_roster("chat-opp", "opponent", teams[1])
    try:
        a, b = proj.players["name"].iloc[0], proj.players["name"].iloc[3]
        cases = {
            f"Who is better for steals, {a} or {b}?": "compare_players",
            "Which player should I pick up?": "streaming_pickups",
            "How can I win 5-4 this week?": "simulate_matchup",
            "Who should I start this week?": "my_team",
            "Who are the top rebounders?": "rankings",
            "Any breakout players?": "breakout_candidates",
        }
        for q, tool in cases.items():
            r = ask(proj, q, [], mine["id"], opp["id"])
            assert r["source"] == "fallback" and r["tool_calls"][0]["tool"] == tool, q
            assert r["answer"]
        give = proj.players.at[teams[0][0], "name"]
        get = proj.players.at[teams[1][0], "name"]
        r = ask(proj, f"Should I trade {give} for {get}?", [], mine["id"], opp["id"])
        assert r["tool_calls"][0]["tool"] == "evaluate_trade"
    finally:
        rosters.delete_roster(mine["id"])
        rosters.delete_roster(opp["id"])


def test_tool_errors_are_returned_not_raised(proj):
    from services.assistant import Ctx, execute
    ctx = Ctx(proj)
    assert "error" in execute(ctx, "nope", {})
    assert "No roster selected" in execute(ctx, "my_team", {})["error"]
    assert "error" in execute(ctx, "player_report", {"name": "zzzz qqqq"})
    assert "error" in execute(ctx, "rankings", {"bogus": 1})


def test_gemini_tool_loop(proj, monkeypatch):
    from google.genai import types as T
    from services import assistant
    from services.gemini_service import gemini

    call = T.GenerateContentResponse(candidates=[T.Candidate(content=T.Content(role="model", parts=[
        T.Part(function_call=T.FunctionCall(name="rankings", args={"limit": 3}))]))])
    top = proj.players.iloc[0]
    final_text = f"{top['name']} leads with a value of {round(float(top['value']), 2)}."
    final = T.GenerateContentResponse(candidates=[T.Candidate(content=T.Content(role="model", parts=[T.Part(text=final_text)]))])
    responses = [call, final]
    seen = []

    class Models:
        def generate_content(self, model, contents, config):
            seen.append(len(contents))
            return responses.pop(0)

    monkeypatch.setattr(gemini, "_client", type("C", (), {"models": Models()})())
    res = assistant.ask(proj, "Who is the top player?", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], None, None)
    assert res["source"] == "gemini" and res["answer"] == final_text
    assert [t["tool"] for t in res["tool_calls"]] == ["rankings"]
    assert res["grounding"]["passed"]
    assert seen == [3, 5]  # history(2)+question, then + model call + tool response


# ----------------------------------------------------------------------------- API
def test_phase3_api(demo_db, teams):
    from fastapi.testclient import TestClient
    from main import app
    c = TestClient(app)
    mine, opp = teams
    r = c.post("/api/matchup/simulate", json={"roster_player_ids": mine, "opponent_player_ids": opp, "sims": 1000})
    assert r.status_code == 200 and 0 <= r.json()["p_win"] <= 1
    assert c.post("/api/ai/matchup", json={"roster_player_ids": mine, "opponent_player_ids": opp, "sims": 1000}).json()["source"] == "fallback"
    r = c.post("/api/whatif", json={"roster_player_ids": mine, "opponent_player_ids": opp, "drop": [opp[0]], "sims": 1000})
    assert r.status_code == 400
    r = c.post("/api/whatif/suggest", json={"roster_player_ids": mine, "opponent_player_ids": opp, "priority": ["bad"]})
    assert r.status_code == 400
    assert c.post("/api/streaming", json={"roster_player_ids": mine, "week": "next"}).status_code == 200
    assert c.get("/api/breakouts?limit=5").status_code == 200
    assert c.get("/api/accuracy").status_code == 200
    r = c.post("/api/assistant", json={"message": "Any breakout players?"})
    assert r.status_code == 200 and r.json()["source"] == "fallback"
