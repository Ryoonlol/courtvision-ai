"""Multi-player trade evaluation (1-for-1 up to 3-for-3) with roster-size replacement logic.

* Receiving fewer players than you give opens roster spots, which are filled with the best
  available free agents (by need-weighted fit) -- otherwise uneven trades look free.
* Receiving more players than you give forces drops: the lowest need-weighted players on the
  post-trade roster are released.
Both sides of the deal are measured with the same 9-cat z-scores used everywhere else.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.categories import CATEGORIES
from services.gemini_service import AIResponse, brief, gemini
from services.projections import Projection
from services.team import (DEFAULT_ROSTERED, Basis, free_agents, need_weights, player_frame, team_profile,
                           weighted_scores)

MAX_SIDE = 3
ACCEPT_THRESHOLD = 1.0


class TradeError(ValueError):
    pass


def _validate(roster: list[int], give: list[int], get: list[int], known: set[int]) -> None:
    if not 1 <= len(give) <= MAX_SIDE or not 1 <= len(get) <= MAX_SIDE:
        raise TradeError(f"Each side of a trade must have 1-{MAX_SIDE} players")
    if len(set(give)) != len(give) or len(set(get)) != len(get):
        raise TradeError("Duplicate players in trade")
    if not set(give) <= set(roster):
        raise TradeError("You can only trade players on your roster")
    if set(get) & set(roster):
        raise TradeError("You already roster a player you are receiving")
    unknown = [p for p in [*roster, *get] if p not in known]
    if unknown:
        raise TradeError(f"No projection available for player ids {unknown}")


def evaluate(proj: Projection, roster: list[int], give: list[int], get: list[int], basis: Basis = "season",
             punt: set[str] | None = None, exclude: set[int] | None = None,
             assume_rostered: int = DEFAULT_ROSTERED) -> dict:
    punt = punt or set()
    _validate(roster, give, get, set(proj.players.index))
    pf = player_frame(proj, basis)
    before = team_profile(proj, roster, basis)
    weights = need_weights(before, punt)
    scores = weighted_scores(pf, weights)

    after = [p for p in roster if p not in give] + list(get)
    adjustments = []
    diff = len(roster) - len(after)
    if diff > 0:  # open roster spots -> best available free agents
        fa = free_agents(proj, basis, (exclude or set()) | set(roster) | set(get), assume_rostered)
        for pid in scores.loc[fa].sort_values(ascending=False).index[:diff]:
            after.append(int(pid))
            adjustments.append({"type": "add_replacement", "player_id": int(pid), "name": proj.players.at[pid, "name"],
                                "reason": "Best available free agent fills the open roster spot"})
    elif diff < 0:  # too many players -> drop the weakest fits
        for pid in sorted(after, key=lambda p: scores[p])[:-diff]:
            after.remove(pid)
            adjustments.append({"type": "drop", "player_id": int(pid), "name": proj.players.at[pid, "name"],
                                "reason": "Lowest need-weighted fit must be released to make room"})

    post = team_profile(proj, after, basis)
    cats = []
    for b, a in zip(before["categories"], post["categories"]):
        dz = a["z"] - b["z"]
        cats.append({"key": b["key"], "label": b["label"], "higher_is_better": b["higher_is_better"],
                     "before": b["value"], "after": a["value"], "z_before": b["z"], "z_after": a["z"],
                     "z_delta": dz, "weight": weights[b["key"]], "punted": b["key"] in punt})
    raw_delta = sum(c["z_delta"] for c in cats)
    weighted_delta = sum(c["z_delta"] * c["weight"] for c in cats)
    side = lambda ids: [_player(proj, pf, p) for p in ids]  # noqa: E731
    give_value = sum(float(pf.at[p, "value"]) for p in give)
    get_value = sum(float(pf.at[p, "value"]) for p in get)
    verdict = ("accept" if weighted_delta >= ACCEPT_THRESHOLD else
               "decline" if weighted_delta <= -ACCEPT_THRESHOLD else "fair")
    return {
        "window": proj.window.as_dict(),
        "basis": basis,
        "format": f"{len(give)}-for-{len(get)}",
        "give": side(give), "get": side(get),
        "adjustments": adjustments,
        "roster_before": roster, "roster_after": after,
        "categories": cats,
        "improved": [c["key"] for c in cats if c["z_delta"] > 0.05 and not c["punted"]],
        "worsened": [c["key"] for c in cats if c["z_delta"] < -0.05 and not c["punted"]],
        "value_delta": raw_delta,
        "need_weighted_delta": weighted_delta,
        "give_value": give_value, "get_value": get_value,
        "value_balance": get_value - give_value,
        "verdict": verdict,
        "punt": sorted(punt),
        "team_value_before": before["total_value"], "team_value_after": post["total_value"],
    }


def _player(proj: Projection, pf, pid: int) -> dict:
    r = proj.players.loc[pid]
    return {"player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"], "position": r["position"],
            "headshot": r["headshot"], "status": r["status"], "games": int(r["games"]),
            "value": float(pf.at[pid, "value"]),
            "z": {c.key: float(pf.at[pid, f"z_{c.key}"]) for c in CATEGORIES}}


# --------------------------------------------------------------------------- Gemini
class TradeInsight(BaseModel):
    headline: str = brief("Verdict", words=10)
    verdict: Literal["accept", "decline", "fair", "depends"]
    summary: str = brief("Net impact with the total and need-weighted deltas", words=30)
    benefits: list[str] = brief("Categories that improve, e.g. 'BLK: 11.7 -> 13.8'", words=10, items=3)
    risks: list[str] = brief("Categories that get worse or other risks", words=10, items=3)
    negotiation_tip: str = brief("How to adjust the offer, using only listed players", words=20)

TRADE_INSTRUCTIONS = """Evaluate this fantasy basketball trade for the user's team in a head-to-head 9-category
league. Use the computed category z-score deltas (positive = better for the user; turnover z is inverted so
positive means fewer turnovers), the need-weighted delta (weak categories count more, punted categories are
ignored), and the roster adjustments (replacement free agents or forced drops). Explain benefits and risks."""


def ai_payload(res: dict) -> dict:
    def p(x):
        return {"name": x["name"], "team": x["team_abbr"], "status": x["status"], "value": round(x["value"], 2)}
    return {
        "format": res["format"],
        "basis": "projected week" if res["basis"] == "week" else "per-game rates (rest of season)",
        "you_give": [p(x) for x in res["give"]],
        "you_get": [p(x) for x in res["get"]],
        "roster_adjustments": [{"type": a["type"], "player": a["name"]} for a in res["adjustments"]],
        "category_changes": [{"category": c["label"], "z_delta": round(c["z_delta"], 2),
                              "before": round(c["before"], 3 if c["key"].endswith("pct") else 1) if c["before"] is not None else None,
                              "after": round(c["after"], 3 if c["key"].endswith("pct") else 1) if c["after"] is not None else None,
                              "punted": c["punted"]} for c in res["categories"]],
        "total_value_delta": round(res["value_delta"], 2),
        "need_weighted_delta": round(res["need_weighted_delta"], 2),
        "value_given": round(res["give_value"], 2), "value_received": round(res["get_value"], 2),
        "computed_verdict": res["verdict"],
    }


def fallback_insight(payload: dict) -> TradeInsight:
    changes = sorted(payload["category_changes"], key=lambda c: c["z_delta"], reverse=True)
    gains = [c for c in changes if c["z_delta"] > 0.05 and not c["punted"]]
    losses = [c for c in changes[::-1] if c["z_delta"] < -0.05 and not c["punted"]]
    verdict = payload["computed_verdict"]
    give = ", ".join(x["name"] for x in payload["you_give"])
    get = ", ".join(x["name"] for x in payload["you_get"])
    benefits = [f"{c['category']}: {c['before']} -> {c['after']}" for c in gains[:3]] or ["No category improves meaningfully."]
    risks = [f"{c['category']}: {c['before']} -> {c['after']}" for c in losses[:3]]
    for a in payload["roster_adjustments"]:
        risks.append(("Forced drop: " if a["type"] == "drop" else "Relies on free agent: ") + a["player"])
    if not risks:
        risks = ["No category gets meaningfully worse."]
    lopsided = payload["value_received"] - payload["value_given"] > 3
    tip = ((f"You receive {payload['value_received']:.1f} in value for {payload['value_given']:.1f}; "
            "the other manager is unlikely to accept as-is.") if verdict == "accept" and lopsided else
           "The deal already favors you; avoid adding sweeteners." if verdict == "accept" else
           f"Ask for more value back: you give {payload['value_given']:.1f} and receive {payload['value_received']:.1f} in value."
           if verdict == "decline" else "Close to even; decide based on which categories you are targeting.")
    return TradeInsight(
        headline={"accept": "This trade helps your team", "decline": "This trade hurts your team",
                  "fair": "Roughly even trade"}[verdict],
        verdict=verdict,
        summary=(f"Trading {give} for {get} changes your overall fantasy value by {payload['total_value_delta']:+.2f} "
                 f"and your team-fit score by {payload['need_weighted_delta']:+.2f}."),
        benefits=benefits, risks=risks[:3], negotiation_tip=tip,
    )


def ai_insight(res: dict) -> AIResponse:
    payload = ai_payload(res)
    return gemini.generate("trade", TRADE_INSTRUCTIONS, payload, TradeInsight, lambda: fallback_insight(payload))
