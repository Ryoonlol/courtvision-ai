"""Phase 2 API: rosters, team needs analyzer, trade analyzer, historical rankings."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.categories import CATEGORY_BY_KEY
from routers.deps import get_projection, require_data
from services import history, rosters, team, trade
from services.team import DEFAULT_ROSTERED, Basis

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------------- rosters
class RosterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str = "mine"
    player_ids: list[int] = []


class RosterPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    kind: str | None = None
    player_ids: list[int] | None = None


class SampleIn(BaseModel):
    name: str = "Sample Team"
    draft_slot: int = Field(5, ge=1, le=20)
    teams: int = Field(12, ge=2, le=20)
    size: int = Field(13, ge=5, le=rosters.MAX_ROSTER)
    kind: str = "mine"


@router.get("/rosters")
def get_rosters() -> list[dict]:
    return rosters.list_rosters()


@router.post("/rosters", status_code=201)
def post_roster(body: RosterIn) -> dict:
    try:
        return rosters.create_roster(body.name, body.kind, body.player_ids)
    except rosters.RosterError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/rosters/sample", status_code=201)
def post_sample_roster(body: SampleIn) -> dict:
    proj = get_projection("next")
    try:
        ids = rosters.sample_roster(proj, body.draft_slot, body.teams, body.size)
        return rosters.create_roster(body.name, body.kind, ids)
    except rosters.RosterError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/rosters/{roster_id}")
def get_roster(roster_id: int) -> dict:
    r = rosters.get_roster(roster_id)
    if r is None:
        raise HTTPException(404, "Roster not found")
    return r


@router.put("/rosters/{roster_id}")
def put_roster(roster_id: int, body: RosterPatch) -> dict:
    try:
        return rosters.update_roster(roster_id, body.name, body.kind, body.player_ids)
    except KeyError:
        raise HTTPException(404, "Roster not found") from None
    except rosters.RosterError as exc:
        raise HTTPException(400, str(exc)) from None


@router.delete("/rosters/{roster_id}", status_code=204)
def del_roster(roster_id: int) -> None:
    try:
        rosters.delete_roster(roster_id)
    except KeyError:
        raise HTTPException(404, "Roster not found") from None


# ----------------------------------------------------------------------------- team analyzer
class TeamIn(BaseModel):
    player_ids: list[int] = Field(min_length=1, max_length=rosters.MAX_ROSTER)
    roster_id: int | None = None          # players on OTHER saved rosters are treated as unavailable
    week: str = "next"
    basis: Basis = "week"
    punt: list[str] = []
    assume_rostered: int = Field(DEFAULT_ROSTERED, ge=0, le=400)


def _punt(keys: list[str]) -> set[str]:
    bad = [k for k in keys if k not in CATEGORY_BY_KEY]
    if bad:
        raise HTTPException(400, f"Unknown categories: {bad}")
    return set(keys)


def _team(body: TeamIn) -> dict:
    proj = get_projection(body.week)
    return team.analyze(proj, body.player_ids, body.basis, _punt(body.punt),
                        rosters.rostered_elsewhere(body.roster_id), body.assume_rostered)


@router.post("/team/analyze")
def analyze_team(body: TeamIn) -> dict:
    return _team(body)


@router.post("/ai/team")
def team_ai(body: TeamIn) -> dict:
    return team.ai_insight(_team(body)).model_dump()


# ----------------------------------------------------------------------------- trade analyzer
class TradeIn(BaseModel):
    roster_player_ids: list[int] = Field(min_length=1, max_length=rosters.MAX_ROSTER)
    give: list[int]
    get: list[int]
    roster_id: int | None = None
    week: str = "next"
    basis: Basis = "season"
    punt: list[str] = []
    assume_rostered: int = Field(DEFAULT_ROSTERED, ge=0, le=400)


def _trade(body: TradeIn) -> dict:
    proj = get_projection(body.week)
    try:
        return trade.evaluate(proj, body.roster_player_ids, body.give, body.get, body.basis, _punt(body.punt),
                              rosters.rostered_elsewhere(body.roster_id), body.assume_rostered)
    except trade.TradeError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/trade/analyze")
def analyze_trade(body: TradeIn) -> dict:
    return _trade(body)


@router.post("/ai/trade")
def trade_ai(body: TradeIn) -> dict:
    return trade.ai_insight(_trade(body)).model_dump()


# ----------------------------------------------------------------------------- history
def _date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, "start must be an ISO date") from None


@router.get("/history/weeks")
def history_weeks() -> list[dict]:
    require_data()
    return history.available_weeks()


@router.get("/history/week")
def history_week(start: str, sort: str = "value", position: str | None = None, search: str | None = None,
                 limit: int = Query(150, ge=1, le=600)) -> dict:
    require_data()
    try:
        return history.week_rankings(_date(start), sort, position, search, limit)
    except KeyError:
        raise HTTPException(404, "No games in that week") from None


@router.get("/history/player/{player_id}")
def history_player(player_id: int, season: str | None = None) -> dict:
    require_data()
    season_year = None
    if season:
        try:
            season_year = int(season.split("-")[0]) + 1
        except ValueError:
            raise HTTPException(400, "season must look like 2025-26") from None
    try:
        return history.player_trend(player_id, season_year or None)
    except KeyError:
        raise HTTPException(404, "No games for that player") from None


@router.get("/history/backtest")
def history_backtest(start: str) -> dict:
    require_data()
    try:
        return history.backtest(_date(start))
    except KeyError:
        raise HTTPException(404, "No games in that week") from None

