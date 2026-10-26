"""Monte Carlo head-to-head 9-category matchup simulator.

Every simulation draws each scheduled player-game independently:
  * the player suits up with probability = availability (injury report),
  * counting stats ~ Normal(projected mean, per-game SD), rounded to whole numbers and floored at 0,
    with a shared per-game "performance factor" (correlation RHO) so a big night lifts every stat,
  * shot attempts are drawn the same way and makes ~ Binomial(attempts, projected %),
    so FG% / FT% are aggregated correctly as total makes / total attempts for the week.
Category results honour turnovers being lower-is-better; equal totals are ties.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from core.categories import CATEGORIES
from data import repository as repo
from services.gemini_service import AIResponse, brief, gemini
from services.projections import Projection

COUNT_STATS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
RHO = 0.35
DEFAULT_SIMS = 10_000
MAX_SIMS = 50_000


@dataclass
class TeamSim:
    totals: dict[str, np.ndarray]   # per-sim weekly totals: counting stats + fgm/fga/ftm/fta
    rows: int
    missing: list[int]


def team_rows(proj: Projection, player_ids: list[int], out: set[int] | None = None,
              availability: dict[int, float] | None = None) -> tuple[pd.DataFrame, list[int]]:
    """Scheduled player-games for a roster, with optional injury / availability overrides."""
    out = out or set()
    availability = availability or {}
    known = set(proj.players.index)
    missing = [p for p in player_ids if p not in known]
    rows = proj.games[proj.games["player_id"].isin([p for p in player_ids if p in known])].copy()
    rows["avail_used"] = rows["avail"]
    for pid, a in availability.items():
        rows.loc[rows["player_id"] == pid, "avail_used"] = float(np.clip(a, 0, 1))
    rows.loc[rows["player_id"].isin(list(out)), "avail_used"] = 0.0
    return rows.reset_index(drop=True), missing


def simulate_team(rows: pd.DataFrame, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    k = len(rows)
    zeros = np.zeros(n)
    if k == 0:
        return {s: zeros.copy() for s in [*COUNT_STATS, "fgm", "fga", "ftm", "fta"]}
    plays = rng.random((n, k)) < rows["avail_used"].to_numpy()[None, :]
    shared = rng.standard_normal((n, k))

    def draw(stat: str) -> np.ndarray:
        mu = rows[f"p_{stat}"].to_numpy()[None, :]
        sd = rows[f"sd_{stat}"].to_numpy()[None, :]
        noise = np.sqrt(RHO) * shared + np.sqrt(1 - RHO) * rng.standard_normal((n, k))
        return np.rint(np.clip(mu + sd * noise, 0, None)) * plays

    totals = {s: draw(s).sum(axis=1) for s in COUNT_STATS}
    for makes, att in (("fgm", "fga"), ("ftm", "fta")):
        attempts = draw(att).astype(np.int64)
        p = np.clip(rows[f"p_{makes}"].to_numpy() / np.maximum(rows[f"p_{att}"].to_numpy(), 1e-9), 0, 1)
        made = rng.binomial(attempts, np.broadcast_to(p, attempts.shape))
        totals[makes] = made.sum(axis=1).astype(float)
        totals[att] = attempts.sum(axis=1).astype(float)
    return totals


def banked_totals(proj: Projection, player_ids: list[int]) -> dict:
    """Actual stats already played this fantasy week (only non-zero when the window starts mid-week)."""
    box = repo.box_scores()
    start, end = pd.Timestamp(proj.window.week_start), pd.Timestamp(proj.window.end)
    done = box[(box["player_id"].isin(player_ids)) & (box["date"] >= start) & (box["date"] <= end)]
    totals = {s: float(done[s].sum()) for s in [*COUNT_STATS, "fgm", "fga", "ftm", "fta"]}
    totals["games"] = int(len(done))
    return totals


def _cat_values(t: dict[str, np.ndarray], key: str) -> np.ndarray:
    c = next(c for c in CATEGORIES if c.key == key)
    if c.is_pct:
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(t[c.attempts] > 0, t[c.makes] / t[c.attempts], np.nan)
    return t[key]


def compare(ta: dict[str, np.ndarray], tb: dict[str, np.ndarray], n: int) -> dict:
    wins_a = np.zeros(n)
    wins_b = np.zeros(n)
    cats = []
    for c in CATEGORIES:
        va, vb = _cat_values(ta, c.key), _cat_values(tb, c.key)
        a_nan, b_nan = np.isnan(va), np.isnan(vb)
        va_f, vb_f = np.nan_to_num(va, nan=-np.inf), np.nan_to_num(vb, nan=-np.inf)
        if c.higher_is_better:
            a_win = (va_f > vb_f) & ~a_nan
            b_win = (vb_f > va_f) & ~b_nan
        else:
            a_win = (va < vb)
            b_win = (vb < va)
        tie = ~(a_win | b_win)
        wins_a += a_win
        wins_b += b_win
        p = float(a_win.mean())
        cats.append({
            "key": c.key, "label": c.label, "higher_is_better": c.higher_is_better,
            "p_win": p, "p_tie": float(tie.mean()), "p_loss": float(b_win.mean()),
            "mean_a": float(np.nanmean(va)) if (~a_nan).any() else None,
            "mean_b": float(np.nanmean(vb)) if (~b_nan).any() else None,
            "p10_a": float(np.nanpercentile(va, 10)) if (~a_nan).any() else None,
            "p90_a": float(np.nanpercentile(va, 90)) if (~a_nan).any() else None,
            "p10_b": float(np.nanpercentile(vb, 10)) if (~b_nan).any() else None,
            "p90_b": float(np.nanpercentile(vb, 90)) if (~b_nan).any() else None,
            "se": float(np.sqrt(max(p * (1 - p), 1e-12) / n)),
        })
    win, loss = wins_a > wins_b, wins_b > wins_a
    hist = np.bincount(wins_a.astype(int), minlength=10)[:10] / n
    ranked = sorted(cats, key=lambda c: c["p_win"], reverse=True)
    p_win = float(win.mean())
    return {
        "sims": n,
        "p_win": p_win, "p_tie": float((~win & ~loss).mean()), "p_loss": float(loss.mean()),
        "p_win_se": float(np.sqrt(max(p_win * (1 - p_win), 1e-12) / n)),
        "expected_cats_won": float(wins_a.mean()), "expected_cats_lost": float(wins_b.mean()),
        "cats_won_distribution": [float(x) for x in hist],
        "p_at_least_5": float((wins_a >= 5).mean()),
        "categories": cats,
        "strongest": [c["key"] for c in ranked[:3]],
        "weakest": [c["key"] for c in ranked[::-1][:3]],
        "swing": [c["key"] for c in cats if 0.35 <= c["p_win"] <= 0.65],
    }


def simulate(proj: Projection, a_ids: list[int], b_ids: list[int], n: int = DEFAULT_SIMS, seed: int = 7,
             a_out: set[int] | None = None, b_out: set[int] | None = None,
             a_avail: dict[int, float] | None = None) -> dict:
    n = int(np.clip(n, 500, MAX_SIMS))
    rng = np.random.default_rng(seed)
    rows_a, miss_a = team_rows(proj, a_ids, a_out, a_avail)
    rows_b, miss_b = team_rows(proj, b_ids, b_out)
    ta = simulate_team(rows_a, n, rng)
    tb = simulate_team(rows_b, n, rng)
    bank_a, bank_b = banked_totals(proj, a_ids), banked_totals(proj, b_ids)
    for t, bank in ((ta, bank_a), (tb, bank_b)):
        for s in t:
            t[s] = t[s] + bank[s]
    res = compare(ta, tb, n)
    res.update({
        "window": proj.window.as_dict(),
        "team_a": _team_summary(proj, rows_a, a_ids, miss_a) | {"banked": bank_a},
        "team_b": _team_summary(proj, rows_b, b_ids, miss_b) | {"banked": bank_b},
        "seed": seed, "rho": RHO,
    })
    return res


def _team_summary(proj: Projection, rows: pd.DataFrame, ids: list[int], missing: list[int]) -> dict:
    by_player = rows.groupby("player_id").agg(games=("game_id", "size"), exp=("avail_used", "sum"))
    players = []
    for pid in ids:
        if pid not in proj.players.index:
            continue
        r = proj.players.loc[pid]
        players.append({"player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"], "headshot": r["headshot"],
                        "status": r["status"],
                        "games": int(by_player["games"].get(pid, 0)), "expected_games": float(by_player["exp"].get(pid, 0.0))})
    return {"players": players, "games": int(len(rows)), "expected_games": float(rows["avail_used"].sum()),
            "missing_player_ids": missing}


# --------------------------------------------------------------------------- Gemini
class MatchupInsight(BaseModel):
    headline: str = brief("Verdict", words=10)
    outlook: str = brief("Win probability, expected categories, what decides it", words=30)
    secure: list[str] = brief("Likely wins as 'CAT %', e.g. 'BLK 100%'", words=3, items=5)
    swing: list[str] = brief("Close categories as 'CAT %', e.g. 'PTS 47%'", words=3, items=5)
    concede: list[str] = brief("Likely losses as 'CAT %', e.g. 'FT% 7%'", words=3, items=5)
    actions: list[str] = brief("Concrete actions from the data only", words=14, items=3)

MATCHUP_INSTRUCTIONS = """Explain this simulated head-to-head 9-category fantasy matchup (team A is the user).
Use the Monte Carlo probabilities exactly as given. Identify categories to secure, swing categories,
and categories worth conceding, and suggest how to get to 5 category wins. Do not invent players or stats."""


def ai_payload(res: dict) -> dict:
    return {
        "week": res["window"]["label"], "simulations": res["sims"],
        "p_win_matchup": round(res["p_win"], 3), "p_tie": round(res["p_tie"], 3),
        "expected_categories_won": round(res["expected_cats_won"], 2),
        "p_win_5_or_more_categories": round(res["p_at_least_5"], 3),
        "categories": [{"category": c["label"], "p_win": round(c["p_win"], 3), "p_tie": round(c["p_tie"], 3),
                        "my_projected": _r(c["mean_a"], c["key"]), "opponent_projected": _r(c["mean_b"], c["key"])}
                       for c in res["categories"]],
        "my_games": res["team_a"]["games"], "opponent_games": res["team_b"]["games"],
        "my_expected_games_played": round(res["team_a"]["expected_games"], 1),
        "opponent_expected_games_played": round(res["team_b"]["expected_games"], 1),
    }


def _r(v, key):
    if v is None:
        return None
    return round(v, 3) if key.endswith("pct") else round(v, 1)


def fallback_insight(payload: dict) -> MatchupInsight:
    cats = sorted(payload["categories"], key=lambda c: c["p_win"], reverse=True)
    pct = lambda c: f"{c['category']} ({round(c['p_win'] * 100)}%)"  # noqa: E731
    secure = [pct(c) for c in cats if c["p_win"] >= 0.65]
    swing = [pct(c) for c in cats if 0.35 <= c["p_win"] < 0.65]
    concede = [pct(c) for c in cats if c["p_win"] < 0.35]
    p = payload["p_win_matchup"]
    actions = []
    if swing:
        actions.append(f"Target the swing categories: {', '.join(swing[:3])}.")
    if payload["my_games"] < payload["opponent_games"]:
        actions.append(f"You have {payload['my_games']} player-games vs {payload['opponent_games']}; stream to close the volume gap.")
    if concede:
        actions.append(f"Consider conceding {concede[0]} and reallocating roster spots to swing categories.")
    if not actions:
        actions.append("Hold your lineup; the projection favors you across the board.")
    return MatchupInsight(
        headline=("Favored this week" if p >= 0.6 else "Underdog this week" if p <= 0.4 else "Coin-flip matchup"),
        outlook=(f"Win probability {round(p * 100)}% over {payload['simulations']} simulations, with "
                 f"{payload['expected_categories_won']} categories won on average."),
        secure=secure or ["None above 65%."], swing=swing or ["No close categories."],
        concede=concede or ["None below 35%."], actions=actions[:3],
    )


def ai_insight(res: dict) -> AIResponse:
    payload = ai_payload(res)
    return gemini.generate("matchup", MATCHUP_INSTRUCTIONS, payload, MatchupInsight, lambda: fallback_insight(payload))
