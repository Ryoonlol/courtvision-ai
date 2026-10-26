"""What-if scenarios: re-simulate a matchup after roster changes.

A scenario can drop players, add players, mark players out (injured/resting) and override
availability. Both the baseline and the scenario are simulated with the same seed and number of
simulations, so differences reflect the roster change rather than sampling noise as much as possible.

``suggest_moves`` handles "prioritise X over Y": it shortlists free agents with a need-weighting that
boosts the priority categories, then verifies each candidate swap by simulation.
"""
from __future__ import annotations

from core.categories import CATEGORIES
from services import matchup
from services.projections import Projection
from services.team import DEFAULT_ROSTERED, free_agents, need_weights, player_frame, team_profile, weighted_scores

PRIORITY_WEIGHT = 3.0


class ScenarioError(ValueError):
    pass


def apply(roster: list[int], add: list[int], drop: list[int]) -> list[int]:
    if set(drop) - set(roster):
        raise ScenarioError("Can only drop players on the roster")
    if set(add) & (set(roster) - set(drop)):
        raise ScenarioError("Player is already on the roster")
    return [p for p in roster if p not in drop] + [p for p in add if p not in roster or p in drop]


def run(proj: Projection, roster: list[int], opponent: list[int], add: list[int] | None = None,
        drop: list[int] | None = None, out: list[int] | None = None, availability: dict[int, float] | None = None,
        n: int = matchup.DEFAULT_SIMS, seed: int = 11) -> dict:
    add, drop, out = add or [], drop or [], out or []
    after = apply(roster, add, drop)
    before = matchup.simulate(proj, roster, opponent, n=n, seed=seed)
    scenario = matchup.simulate(proj, after, opponent, n=n, seed=seed, a_out=set(out), a_avail=availability)
    deltas = [{"key": b["key"], "label": b["label"], "p_before": b["p_win"], "p_after": a["p_win"],
               "delta": a["p_win"] - b["p_win"], "mean_before": b["mean_a"], "mean_after": a["mean_a"]}
              for b, a in zip(before["categories"], scenario["categories"])]
    names = lambda ids: [proj.players.at[p, "name"] for p in ids if p in proj.players.index]  # noqa: E731
    return {
        "window": proj.window.as_dict(),
        "changes": {"add": names(add), "drop": names(drop), "out": names(out),
                    "availability": {proj.players.at[p, "name"]: v for p, v in (availability or {}).items()
                                     if p in proj.players.index}},
        "roster_after": after,
        "before": _brief(before), "after": _brief(scenario),
        "delta_p_win": scenario["p_win"] - before["p_win"],
        "delta_expected_cats": scenario["expected_cats_won"] - before["expected_cats_won"],
        "categories": deltas,
        "before_full": before, "after_full": scenario,
    }


def _brief(res: dict) -> dict:
    return {k: res[k] for k in ("p_win", "p_tie", "p_loss", "expected_cats_won", "p_at_least_5", "p_win_se",
                                "cats_won_distribution")} | {"games": res["team_a"]["games"],
                                                             "expected_games": res["team_a"]["expected_games"]}


def suggest_moves(proj: Projection, roster: list[int], opponent: list[int], priority: list[str],
                  punt: list[str] | None = None, exclude: set[int] | None = None,
                  assume_rostered: int = DEFAULT_ROSTERED, candidates: int = 8, n: int = 3000, seed: int = 5) -> dict:
    """Best single add/drop swaps for the priority categories, verified by simulation."""
    punt = set(punt or [])
    valid = {c.key for c in CATEGORIES}
    if not priority or set(priority) - valid:
        raise ScenarioError("priority must list 1+ category keys")
    profile = team_profile(proj, roster, "week")
    weights = need_weights(profile, punt)
    for k in priority:
        weights[k] = PRIORITY_WEIGHT
    pf = player_frame(proj, "week")
    scores = weighted_scores(pf, weights)
    in_roster = [p for p in roster if p in pf.index]
    if not in_roster:
        raise ScenarioError("Roster has no projected players")
    drop = min(in_roster, key=lambda p: scores[p])
    fa = free_agents(proj, "week", (exclude or set()) | set(roster) | set(opponent), assume_rostered)
    shortlist = scores.loc[fa].sort_values(ascending=False).index[:candidates]

    base = matchup.simulate(proj, roster, opponent, n=n, seed=seed)
    base_pri = {c["key"]: c["p_win"] for c in base["categories"]}
    results = []
    for pid in shortlist:
        after = [p for p in roster if p != drop] + [int(pid)]
        sim = matchup.simulate(proj, after, opponent, n=n, seed=seed)
        cat = {c["key"]: c["p_win"] for c in sim["categories"]}
        r = proj.players.loc[pid]
        results.append({
            "player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"], "headshot": r["headshot"],
            "games": int(r["games"]), "drop_player_id": int(drop), "drop_name": proj.players.at[drop, "name"],
            "priority_gain": sum(cat[k] - base_pri[k] for k in priority) / len(priority),
            "delta_p_win": sim["p_win"] - base["p_win"],
            "delta_expected_cats": sim["expected_cats_won"] - base["expected_cats_won"],
            "category_deltas": {k: cat[k] - base_pri[k] for k in cat},
        })
    results.sort(key=lambda x: (x["priority_gain"], x["delta_p_win"]), reverse=True)
    return {"priority": priority, "base_p_win": base["p_win"], "base_priority_p": {k: base_pri[k] for k in priority},
            "sims_per_candidate": n, "moves": results}
