"""Gemini forecast model: validation, jobs, side-by-side view and like-for-like scoring (agy faked)."""
import json
import time
from datetime import timedelta

import pandas as pd
import pytest

from core.categories import RAW_STATS
from services.schedule import week_window

STATS = ["min", *RAW_STATS]


def _wait(kind, timeout=20):
    from services import gemini_forecast as gf
    t = time.time()
    while time.time() - t < timeout:
        st = gf.job_status(kind)
        if st and st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _fake_from(fn):
    """Fake agy.generate_json that answers each requested player via fn(context)."""
    calls = []

    def fake(prompt, schema, timeout=None, model=None):
        ctxs = json.loads(prompt.split("PLAYERS (JSON):\n", 1)[1])
        calls.append(len(ctxs))
        return {"players": [fn(c) for c in ctxs]}
    return fake, calls


def _simple(c, scale=1.0):
    return {"player_id": c["player_id"], "expected_games": len(c["scheduled_games"]), "confidence": "medium",
            "rationale": "test", "per_game": {k: 2.0 * scale for k in STATS} | {"fga": 10.0, "fgm": 4.0, "fta": 4.0, "ftm": 3.0}}


def test_sanitize_clamps_bad_values():
    from services.gemini_forecast import sanitize
    clean, fixes = sanitize({"per_game": {"min": 60, "pts": -3, "fgm": 12, "fga": 8, "ftm": 2, "fta": 1, "fg3m": 9,
                                          "reb": "x"}, "expected_games": 9, "confidence": "certain"}, max_games=3)
    pg = clean["per_game"]
    assert pg["min"] == 48 and pg["pts"] == 0 and pg["reb"] == 0
    assert pg["fgm"] <= pg["fga"] and pg["ftm"] <= pg["fta"] and pg["fg3m"] <= pg["fgm"]
    assert clean["expected_games"] == 3 and clean["confidence"] == "low"
    assert fixes


def test_forecast_batch_ignores_unknown_ids(monkeypatch):
    from services import gemini_forecast as gf
    ctxs = [{"player_id": 1, "scheduled_games": [{}, {}]}, {"player_id": 2, "scheduled_games": [{}]}]

    def fake(prompt, schema, timeout=None, model=None):
        return {"players": [_simple(ctxs[0]), _simple({"player_id": 999, "scheduled_games": []}),
                            {"player_id": "bad"}]}
    monkeypatch.setattr(gf.agy_client, "generate_json", fake)
    out = gf.forecast_batch(ctxs, "wk")
    assert set(out) == {1}
    assert out[1]["expected_games"] == 2


def test_live_job_view_and_projection_log(monkeypatch, demo_db):
    from core.db import get_conn
    from services import gemini_forecast as gf
    from services.projections import project
    proj = project(week_window("next"))
    fake, calls = _fake_from(_simple)
    monkeypatch.setattr(gf.agy_client, "generate_json", fake)
    gf.start_live(proj, top_n=30)
    st = _wait("live")
    assert st["status"] == "done" and st["done"] == st["total"] and sum(calls) >= 30
    v = gf.view(proj)
    assert v["players"] >= 30
    row = v["rows"][0]
    pid = row["player_id"]
    fc = gf.load("live", proj.window.start.isoformat())[pid]
    assert row["categories"]["pts"]["gemini"] == pytest.approx(fc["per_game"]["pts"] * fc["expected_games"])
    assert row["categories"]["pts"]["stat"] == pytest.approx(proj.players.at[pid, "pts"])
    assert row["categories"]["fg_pct"]["gemini"] == pytest.approx(0.4)
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM projection_log WHERE method='gemini' AND week_start=?",
                         (proj.window.week_start.isoformat(),)).fetchone()[0]
    assert n >= 30


def test_batch_failures_are_recorded_not_fatal(monkeypatch, demo_db):
    from services import agy_client
    from services import gemini_forecast as gf
    from services.projections import project
    proj = project(week_window("next"))
    state = {"n": 0}

    def flaky(prompt, schema, timeout=None, model=None):
        state["n"] += 1
        if state["n"] == 1:
            raise agy_client.AgyError("boom")
        return _fake_from(_simple)[0](prompt, schema)
    monkeypatch.setattr(gf.agy_client, "generate_json", flaky)
    gf.start_live(proj, top_n=45)
    st = _wait("live")
    assert st["status"] == "done" and any("boom" in e for e in st["errors"])


def test_saved_projections_scored_on_common_players(demo_db):
    from core.db import get_conn
    from services.accuracy import saved_projection_scores
    from services.history import available_weeks, weekly_totals
    ws = next(w for w in available_weeks() if not w["in_progress"])["week_start"]
    act = weekly_totals()
    act = act[act["week_start"] == pd.Timestamp(ws)].set_index("player_id")
    ids = list(act.index[:30])
    with get_conn() as conn:
        for i, pid in enumerate(ids):
            perfect = {s: float(act.at[pid, s]) for s in RAW_STATS} | {"value": float(act.at[pid, "pts"])}
            conn.execute("INSERT OR REPLACE INTO projection_log VALUES(?,?,?,?,?,?)",
                         (ws, int(pid), "gemini", "t", 1, json.dumps(perfect)))
            if i < 20:  # statistical log covers fewer players -> comparison restricted to 20
                off = {s: v + 2 for s, v in perfect.items()}
                conn.execute("INSERT OR REPLACE INTO projection_log VALUES(?,?,?,?,?,?)",
                             (ws, int(pid), "courtvision", "t", 1, json.dumps(off)))
    rec = next(r for r in saved_projection_scores() if r["week_start"] == ws)
    assert rec["status"] == "scored" and rec["common_players"] == 20
    assert rec["methods"]["gemini"]["mae"]["pts"] == pytest.approx(0)
    assert rec["methods"]["courtvision"]["mae"]["pts"] == pytest.approx(2)


def test_backtest_oracle_beats_statistical_model(monkeypatch, demo_db):
    """Feeding the backtest the true per-game results must score better than the statistical baseline."""
    from services import gemini_forecast as gf
    from services.history import available_weeks, weekly_totals
    weeks = [w["week_start"] for w in available_weeks() if not w["in_progress"]][5:7]
    wt = weekly_totals()

    def oracle(c):
        ws = None
        for w in weeks:
            start = pd.Timestamp(w)
            if c["scheduled_games"] and start <= pd.Timestamp(c["scheduled_games"][0]["date"]) <= start + timedelta(days=6):
                ws = start
        row = wt[(wt["week_start"] == ws) & (wt["player_id"] == c["player_id"])]
        if row.empty:
            return _simple(c)
        r = row.iloc[0]
        return {"player_id": c["player_id"], "expected_games": int(r["games"]), "confidence": "high", "rationale": "oracle",
                "per_game": {k: float(r[k]) / r["games"] for k in STATS}}
    fake, _ = _fake_from(oracle)
    monkeypatch.setattr(gf.agy_client, "generate_json", fake)
    gf.start_backtest(weeks, per_week=20)
    assert _wait("backtest")["status"] == "done"
    res = gf.backtest_scores()
    assert len(res["weeks"]) == 2 and "caveat" in res
    for w in res["weeks"]:
        assert w["gemini"]["pts"] < w["weighted"]["pts"]
        assert w["gemini"]["spearman"] > w["weighted"]["spearman"]


def test_forecast_api(monkeypatch, demo_db):
    from fastapi.testclient import TestClient
    from main import app
    from services import agy_client
    c = TestClient(app)
    assert c.get("/api/forecast?week=next").status_code == 200
    assert c.get("/api/forecast/status").json()["default_backtest_weeks"]
    assert c.get("/api/forecast/players?ids=1,x").status_code == 400
    monkeypatch.setattr(agy_client, "binary", lambda: None)
    r = c.post("/api/forecast/run", json={"week": "next"})
    assert r.status_code == 400 and "agy" in r.json()["detail"]
