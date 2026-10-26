"""9-category z-score valuation (the standard method for H2H category leagues).

* Counting stats: z = (x - mean_pool) / sd_pool; turnovers are negated (fewer is better).
* FG% / FT%: volume-aware "impact" = makes - pool_pct * attempts, then z-scored.
  A 60% shooter on 20 attempts helps far more than a 60% shooter on 2 attempts.
* The pool is the top ``pool_size`` players (12 teams x 13 roster spots by default),
  found iteratively so that replacement-level players define the scale.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.categories import CATEGORIES

DEFAULT_POOL = 156


@dataclass
class ValuationParams:
    means: dict[str, float]
    sds: dict[str, float]
    pool_pct: dict[str, float]  # pool fg_pct / ft_pct used for impact
    pool_size: int


def _cat_raw(df: pd.DataFrame, params_pct: dict[str, float]) -> dict[str, np.ndarray]:
    out = {}
    for c in CATEGORIES:
        if c.is_pct:
            out[c.key] = df[c.makes].to_numpy(float) - params_pct[c.key] * df[c.attempts].to_numpy(float)
        else:
            out[c.key] = df[c.key].to_numpy(float)
    return out


def fit(df: pd.DataFrame, pool_size: int = DEFAULT_POOL, iterations: int = 3) -> ValuationParams:
    """Fit z-score parameters on a frame of raw totals (pts, reb, ..., fgm, fga, ftm, fta)."""
    pool = df
    params = None
    for _ in range(iterations):
        pct = {c.key: float(pool[c.makes].sum() / max(pool[c.attempts].sum(), 1e-9))
               for c in CATEGORIES if c.is_pct}
        raw = _cat_raw(pool, pct)
        means = {k: float(np.mean(v)) for k, v in raw.items()}
        sds = {k: float(np.std(v)) or 1.0 for k, v in raw.items()}
        params = ValuationParams(means, sds, pct, pool_size)
        values = score(df, params)["value"]
        pool = df.loc[values.sort_values(ascending=False).index[:pool_size]]
    return params


def score(df: pd.DataFrame, params: ValuationParams) -> pd.DataFrame:
    """Per-category z-scores plus total 9-cat value for each row."""
    raw = _cat_raw(df, params.pool_pct)
    out = pd.DataFrame(index=df.index)
    for c in CATEGORIES:
        z = (raw[c.key] - params.means[c.key]) / params.sds[c.key]
        out[f"z_{c.key}"] = -z if not c.higher_is_better else z
    out["value"] = out[[f"z_{c.key}" for c in CATEGORIES]].sum(axis=1)
    return out


def value_interval(means: pd.DataFrame, sds: pd.DataFrame, params: ValuationParams, sims: int = 300,
                   seed: int = 11, q: tuple[float, float] = (0.1, 0.9)) -> tuple[np.ndarray, np.ndarray]:
    """Monte Carlo 80% interval of total 9-cat value from per-stat weekly means/SDs."""
    rng = np.random.default_rng(seed)
    n = len(means)
    totals = np.zeros((sims, n))
    for c in CATEGORIES:
        if c.is_pct:
            att_mu = means[c.attempts].to_numpy(float)
            att = np.clip(rng.normal(att_mu, sds[c.attempts].to_numpy(float), (sims, n)), 0, None)
            p = np.clip(np.where(att_mu > 0, means[c.makes].to_numpy(float) / np.maximum(att_mu, 1e-9), 0), 0, 1)
            p_draw = np.clip(rng.normal(p, np.sqrt(p * (1 - p) / np.maximum(att_mu, 1)), (sims, n)), 0, 1)
            raw = p_draw * att - params.pool_pct[c.key] * att
        else:
            raw = np.clip(rng.normal(means[c.key].to_numpy(float), sds[c.key].to_numpy(float), (sims, n)), 0, None)
        z = (raw - params.means[c.key]) / params.sds[c.key]
        totals += -z if not c.higher_is_better else z
    lo, hi = np.quantile(totals, q, axis=0)
    return lo, hi
