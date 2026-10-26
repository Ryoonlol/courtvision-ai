"""Standard H2H 9-category definitions and category math.

Percentages are always computed as total makes / total attempts (never as an
average of per-game percentages), so high-volume shooters move the needle more.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    name: str
    higher_is_better: bool = True
    makes: str | None = None
    attempts: str | None = None

    @property
    def is_pct(self) -> bool:
        return self.makes is not None


CATEGORIES: tuple[Category, ...] = (
    Category("pts", "PTS", "Points"),
    Category("reb", "REB", "Rebounds"),
    Category("ast", "AST", "Assists"),
    Category("stl", "STL", "Steals"),
    Category("blk", "BLK", "Blocks"),
    Category("fg3m", "3PM", "Three-pointers made"),
    Category("fg_pct", "FG%", "Field goal percentage", makes="fgm", attempts="fga"),
    Category("ft_pct", "FT%", "Free throw percentage", makes="ftm", attempts="fta"),
    Category("tov", "TO", "Turnovers", higher_is_better=False),
)
CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}
COUNTING_KEYS = [c.key for c in CATEGORIES if not c.is_pct]
# Raw box-score stats needed to evaluate all nine categories.
RAW_STATS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fgm", "fga", "ftm", "fta"]
# Stats the projection engine models directly (minutes included for context).
MODEL_STATS = ["min", *RAW_STATS]


def pct(makes: float, attempts: float) -> float | None:
    """Makes / attempts, or None when there were no attempts."""
    if attempts is None or attempts <= 0:
        return None
    return float(makes) / float(attempts)


def with_percentages(totals: Mapping[str, float]) -> dict[str, float | None]:
    """Return the nine category values from raw totals (counting stats + makes/attempts)."""
    out: dict[str, float | None] = {}
    for c in CATEGORIES:
        if c.is_pct:
            out[c.key] = pct(totals.get(c.makes, 0.0), totals.get(c.attempts, 0.0))
        else:
            out[c.key] = float(totals.get(c.key, 0.0))
    return out


def aggregate(rows: list[Mapping[str, float]]) -> dict[str, float]:
    """Sum raw stats across players/games; percentages must be derived afterwards."""
    totals = {s: 0.0 for s in RAW_STATS}
    for r in rows:
        for s in RAW_STATS:
            totals[s] += float(r.get(s, 0.0) or 0.0)
    return totals


def category_winner(key: str, a: float | None, b: float | None, tol: float = 1e-9) -> str:
    """'a', 'b' or 'tie' for a single category, honouring turnovers being lower-is-better."""
    if a is None and b is None:
        return "tie"
    if a is None:
        return "b"
    if b is None:
        return "a"
    if abs(a - b) <= tol:
        return "tie"
    better_a = a > b if CATEGORY_BY_KEY[key].higher_is_better else a < b
    return "a" if better_a else "b"


def compare_totals(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, str]:
    """Head-to-head category result between two sets of raw totals."""
    ca, cb = with_percentages(a), with_percentages(b)
    return {c.key: category_winner(c.key, ca[c.key], cb[c.key]) for c in CATEGORIES}


def safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)
