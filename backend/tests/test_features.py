import numpy as np
import pandas as pd
import pytest

from core.categories import MODEL_STATS
from services.features import K_PRIOR, W_L5, W_L10, W_SEASON, player_features, team_factors


def _box(points_by_game, season=2027, player_id=1, start="2026-10-20", prior=None):
    rows = []
    dates = pd.date_range(start, periods=len(points_by_game), freq="2D")
    for i, (d, p) in enumerate(zip(dates, points_by_game)):
        rows.append({"player_id": player_id, "game_id": 1000 + i, "date": d, "season": season,
                     "team_id": 10, "opp_team_id": 20 + (i % 2), "home": i % 2,
                     **{s: float(p) for s in MODEL_STATS}})
    df = pd.DataFrame(rows)
    if prior is not None:
        df = pd.concat([prior, df], ignore_index=True)
    return df


def test_features_use_only_prior_games():
    box = _box([10, 20, 30, 40])
    feat = player_features(box).sort_values("date").reset_index(drop=True)
    # first game has no current-season history
    assert np.isnan(feat.loc[0, "cur_pts"])
    # third game sees only games 1-2
    assert feat.loc[2, "cur_pts"] == pytest.approx(15)
    assert feat.loc[2, "l5_pts"] == pytest.approx(15)
    assert feat.loc[3, "cur_n"] == 3
    assert feat.loc[3, "actual_pts"] == 40


def test_placeholder_state_matches_all_history():
    box = _box([10, 20, 30, 40, 50, 60])
    ph = pd.DataFrame([{"player_id": 1, "game_id": -1, "date": pd.Timestamp("2026-12-01"), "season": 2027,
                        "team_id": 10, "opp_team_id": -1, "home": 0}])
    feat = player_features(box, ph)
    state = feat[feat["placeholder"]].iloc[0]
    assert state["cur_n"] == 6
    assert state["cur_pts"] == pytest.approx(35)
    assert state["l5_pts"] == pytest.approx(np.mean([20, 30, 40, 50, 60]))
    # no prior seasons -> blend == current-season average; weights renormalise to the baseline
    expected = W_SEASON * 35 + W_L10 * 35 + W_L5 * 40
    assert state["base_pts"] == pytest.approx(expected / (W_SEASON + W_L10 + W_L5))


def test_prior_season_shrinkage():
    prior = _box([20] * 30, season=2026, start="2025-11-01")
    box = _box([40, 40], season=2027, prior=prior)
    ph = pd.DataFrame([{"player_id": 1, "game_id": -1, "date": pd.Timestamp("2026-12-01"), "season": 2027,
                        "team_id": 10, "opp_team_id": -1, "home": 0}])
    state = player_features(box, ph).query("placeholder").iloc[0]
    assert state["prev_pts"] == pytest.approx(20)
    # two hot games are shrunk toward the 30-game prior
    assert state["blend_pts"] == pytest.approx((2 * 40 + K_PRIOR * 20) / (2 + K_PRIOR))
    assert 20 < state["base_pts"] < 40


def test_prior_uses_two_seasons_games_weighted():
    s1 = _box([10] * 10, season=2025, start="2024-11-01")
    s2 = _box([30] * 30, season=2026, start="2025-11-01", prior=s1)
    box = _box([25], season=2027, prior=s2)
    feat = player_features(box)
    row = feat[feat["season"] == 2027].iloc[0]
    assert row["prev_n"] == 40
    assert row["prev_pts"] == pytest.approx((10 * 10 + 30 * 30) / 40)


def test_team_factors_are_bounded_and_leak_free():
    rows = []
    for g in range(30):
        for team, opp in ((1, 2), (2, 1)):
            pts = 120 if opp == 1 else 100  # team 1's opponents score more
            rows.append({"player_id": team * 100, "game_id": g, "date": pd.Timestamp("2026-10-20") + pd.Timedelta(days=g),
                         "season": 2027, "team_id": team, "opp_team_id": opp, "home": 0,
                         **{s: 10.0 for s in MODEL_STATS}, "pts": float(pts)})
    asof, current = team_factors(pd.DataFrame(rows))
    first = asof[asof["game_id"] == 0]
    assert (first["opp_pts"] == 1.0).all()  # nothing known before the first game
    cur = current.set_index("team_id")
    assert cur.loc[1, "opp_pts"] > 1.0 > cur.loc[2, "opp_pts"]
    assert current["opp_pts"].between(0.85, 1.15).all()
