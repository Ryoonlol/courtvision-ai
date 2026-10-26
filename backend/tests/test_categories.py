import pandas as pd
import pytest

from core.categories import aggregate, category_winner, compare_totals, pct, with_percentages
from services import valuation


def test_pct_is_makes_over_attempts_and_handles_zero():
    assert pct(5, 10) == 0.5
    assert pct(0, 0) is None


def test_team_percentage_is_volume_weighted_not_average_of_percentages():
    # 10/20 (50%) and 1/1 (100%): average of percentages would be 75%, correct value is 11/21.
    totals = aggregate([{"fgm": 10, "fga": 20}, {"fgm": 1, "fga": 1}])
    cats = with_percentages(totals)
    assert cats["fg_pct"] == pytest.approx(11 / 21)


def test_turnovers_lower_is_better():
    assert category_winner("tov", 10, 14) == "a"
    assert category_winner("pts", 10, 14) == "b"
    assert category_winner("reb", 7, 7) == "tie"
    assert category_winner("fg_pct", None, 0.5) == "b"


def test_compare_totals_nine_categories():
    a = {"pts": 100, "reb": 40, "ast": 20, "stl": 8, "blk": 2, "fg3m": 10, "tov": 12,
         "fgm": 40, "fga": 80, "ftm": 10, "fta": 12}
    b = {"pts": 90, "reb": 50, "ast": 20, "stl": 5, "blk": 6, "fg3m": 12, "tov": 9,
         "fgm": 35, "fga": 60, "ftm": 18, "fta": 20}
    res = compare_totals(a, b)
    assert len(res) == 9
    assert res["pts"] == "a" and res["reb"] == "b" and res["ast"] == "tie"
    assert res["tov"] == "b"                      # fewer turnovers wins
    assert res["fg_pct"] == "b"                   # 58.3% beats 50%
    assert res["ft_pct"] == "b"                   # 90.0% beats 83.3%


def _pool():
    rows = []
    for i in range(40):
        rows.append({"pts": 10 + i, "reb": 5 + (i % 7), "ast": 3 + (i % 5), "stl": 1 + (i % 3) * 0.5,
                     "blk": 0.5 + (i % 4) * 0.3, "fg3m": 1 + (i % 6) * 0.4, "tov": 1 + (i % 5) * 0.4,
                     "fgm": 4 + i * 0.2, "fga": 9 + i * 0.4, "ftm": 2 + (i % 4), "fta": 3 + (i % 4)})
    return pd.DataFrame(rows)


def test_valuation_turnover_z_is_negated():
    df = _pool()
    params = valuation.fit(df, pool_size=30)
    base = df.iloc[[0]].copy()
    more_to = base.copy()
    more_to["tov"] += 3
    assert valuation.score(more_to, params)["z_tov"].iloc[0] < valuation.score(base, params)["z_tov"].iloc[0]


def test_valuation_fg_impact_scales_with_volume():
    df = _pool()
    params = valuation.fit(df, pool_size=30)
    low_vol = df.iloc[[0]].copy()
    high_vol = df.iloc[[0]].copy()
    low_vol[["fgm", "fga"]] = [1.2, 2]      # 60% on 2 attempts
    high_vol[["fgm", "fga"]] = [12, 20]     # 60% on 20 attempts
    z_low = valuation.score(low_vol, params)["z_fg_pct"].iloc[0]
    z_high = valuation.score(high_vol, params)["z_fg_pct"].iloc[0]
    assert z_high > z_low


def test_valuation_value_is_sum_of_category_z():
    df = _pool()
    params = valuation.fit(df, pool_size=30)
    scored = valuation.score(df, params)
    zcols = [c for c in scored.columns if c.startswith("z_")]
    assert len(zcols) == 9
    assert (scored[zcols].sum(axis=1) - scored["value"]).abs().max() < 1e-9


def test_value_interval_brackets_point_value():
    df = _pool()
    params = valuation.fit(df, pool_size=30)
    sds = df * 0.15
    lo, hi = valuation.value_interval(df, sds, params, sims=500)
    val = valuation.score(df, params)["value"].to_numpy()
    assert (lo <= hi).all()
    assert ((val >= lo - 0.5) & (val <= hi + 0.5)).mean() > 0.9
