"""Phase 3 API: matchup simulator, what-if, streaming, breakouts, accuracy tracker, assistant."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.categories import CATEGORY_BY_KEY
from routers.deps import get_projection, require_data
from services import accuracy, assistant, breakouts, gemini_forecast, matchup, rosters, streaming, whatif
from services.team import DEFAULT_ROSTERED

router = APIRouter(prefix="/api")
MAX = rosters.MAX_ROSTER


class MatchupIn(BaseModel):
    roster_player_ids: list[int] = Field(min_length=1, max_length=MAX)
    opponent_player_ids: list[int] = Field(min_length=1, max_length=MAX)
    week: str = "next"
    sims: int = Field(matchup.DEFAULT_SIMS, ge=500, le=matchup.MAX_SIMS)
    seed: int = 7


def _keys(keys: list[str]) -> list[str]:
    bad = [k for k in keys if k not in CATEGORY_BY_KEY]
    if bad:
        raise HTTPException(400, f"Unknown categories: {bad}")
    return keys


@router.post("/matchup/simulate")
def simulate(body: MatchupIn) -> dict:
    proj = get_projection(body.week)
    return matchup.simulate(proj, body.roster_player_ids, body.opponent_player_ids, body.sims, body.seed)


@router.post("/ai/matchup")
def matchup_ai(body: MatchupIn) -> dict:
    proj = get_projection(body.week)
    res = matchup.simulate(proj, body.roster_player_ids, body.opponent_player_ids, body.sims, body.seed)
    return matchup.ai_insight(res).model_dump()


# ----------------------------------------------------------------------------- what-if
class WhatIfIn(BaseModel):
    roster_player_ids: list[int] = Field(min_length=1, max_length=MAX)
    opponent_player_ids: list[int] = Field(min_length=1, max_length=MAX)
    add: list[int] = Field(default_factory=list, max_length=5)
    drop: list[int] = Field(default_factory=list, max_length=5)
    out: list[int] = Field(default_factory=list, max_length=MAX)
    availability: dict[int, float] = Field(default_factory=dict)
    week: str = "next"
    sims: int = Field(matchup.DEFAULT_SIMS, ge=500, le=matchup.MAX_SIMS)


@router.post("/whatif")
def run_whatif(body: WhatIfIn) -> dict:
    proj = get_projection(body.week)
    try:
        res = whatif.run(proj, body.roster_player_ids, body.opponent_player_ids, body.add, body.drop, body.out,
                         body.availability, body.sims)
    except whatif.ScenarioError as exc:
        raise HTTPException(400, str(exc)) from None
    res.pop("before_full")
    after = res.pop("after_full")
    res["categories_after"] = after["categories"]
    return res


class SuggestIn(BaseModel):
    roster_player_ids: list[int] = Field(min_length=1, max_length=MAX)
    opponent_player_ids: list[int] = Field(min_length=1, max_length=MAX)
    priority: list[str] = Field(min_length=1, max_length=4)
    punt: list[str] = Field(default_factory=list)
    roster_id: int | None = None
    week: str = "next"
    assume_rostered: int = Field(DEFAULT_ROSTERED, ge=0, le=400)


@router.post("/whatif/suggest")
def suggest(body: SuggestIn) -> dict:
    proj = get_projection(body.week)
    try:
        return whatif.suggest_moves(proj, body.roster_player_ids, body.opponent_player_ids, _keys(body.priority),
                                    _keys(body.punt), rosters.rostered_elsewhere(body.roster_id), body.assume_rostered)
    except whatif.ScenarioError as exc:
        raise HTTPException(400, str(exc)) from None


# ----------------------------------------------------------------------------- streaming
class StreamIn(BaseModel):
    roster_player_ids: list[int] = Field(min_length=1, max_length=MAX)
    roster_id: int | None = None
    week: str = "current"
    slots: int = Field(streaming.DEFAULT_SLOTS, ge=1, le=15)
    available_ids: list[int] | None = Field(None, max_length=200)
    punt: list[str] = Field(default_factory=list)
    assume_rostered: int = Field(DEFAULT_ROSTERED, ge=0, le=400)
    limit: int = Field(15, ge=1, le=50)


@router.post("/streaming")
def stream(body: StreamIn) -> dict:
    proj = get_projection(body.week)
    return streaming.optimize(proj, body.roster_player_ids, body.slots, body.available_ids or None,
                              rosters.rostered_elsewhere(body.roster_id), _keys(body.punt), body.assume_rostered, body.limit)


# ----------------------------------------------------------------------------- breakouts
def _as_of(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, "as_of must be an ISO date") from None


@router.get("/breakouts")
def get_breakouts(as_of: str | None = None, limit: int = Query(25, ge=1, le=60),
                  min_minutes: float = Query(breakouts.MIN_RECENT_MIN, ge=0, le=40)) -> dict:
    require_data()
    return breakouts.detect(_as_of(as_of), limit, min_minutes)


@router.post("/ai/breakouts")
def breakouts_ai(as_of: str | None = None, min_minutes: float = Query(breakouts.MIN_RECENT_MIN, ge=0, le=40)) -> dict:
    require_data()
    return breakouts.ai_insight(breakouts.detect(_as_of(as_of), 10, min_minutes)).model_dump()


# ----------------------------------------------------------------------------- accuracy
@router.get("/accuracy")
def get_accuracy() -> dict:
    require_data()
    return accuracy.compute()


# ----------------------------------------------------------------------------- assistant
class ChatTurn(BaseModel):
    role: str
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=30)
    roster_id: int | None = None
    opponent_roster_id: int | None = None
    week: str = "next"


@router.post("/assistant")
def chat(body: ChatIn) -> dict:
    proj = get_projection(body.week)
    return assistant.ask(proj, body.message, [t.model_dump() for t in body.history], body.roster_id,
                         body.opponent_roster_id)


# ----------------------------------------------------------------------------- Gemini forecast model
class ForecastRunIn(BaseModel):
    week: str = "next"
    top_n: int = Field(120, ge=10, le=300)


class ForecastBacktestIn(BaseModel):
    weeks: list[str] | None = Field(None, max_length=8)
    per_week: int = Field(40, ge=10, le=100)


def _require_agy() -> None:
    from services import agy_client
    if not agy_client.binary():
        raise HTTPException(400, "The Gemini forecast runs through the agy CLI, which was not found on this machine")


@router.get("/forecast")
def forecast_view(week: str = "next") -> dict:
    return gemini_forecast.view(get_projection(week))


@router.get("/forecast/players")
def forecast_players(ids: str, week: str = "next") -> dict:
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers") from None
    return gemini_forecast.players_view(get_projection(week), wanted)


@router.post("/forecast/run")
def forecast_run(body: ForecastRunIn) -> dict:
    _require_agy()
    rostered = {p for r in rosters.list_rosters() for p in r["player_ids"]}
    return gemini_forecast.start_live(get_projection(body.week), body.top_n, rostered)


@router.post("/forecast/backtest")
def forecast_backtest(body: ForecastBacktestIn) -> dict:
    _require_agy()
    require_data()
    return gemini_forecast.start_backtest(body.weeks, body.per_week)


@router.get("/forecast/status")
def forecast_status() -> dict:
    return {"live": gemini_forecast.job_status("live"), "backtest": gemini_forecast.job_status("backtest"),
            "default_backtest_weeks": gemini_forecast.default_backtest_weeks()}
