"""Phase 1 API: meta, players, comparison, weekly rankings, schedule and model metrics."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.categories import CATEGORIES
from core.config import settings
from core.db import get_conn, get_meta
from data import bootstrap
from data.ingest import CURRENT_SEASON, season_label
from routers.deps import get_projection, require_data
from services import comparison, ml_model, rankings
from services import today as today_svc
from services import players as player_svc
from services.gemini_service import gemini
from services.projections import explain_player, player_row
from services.schedule import schedule_summary, today, week_window

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------------- meta
@router.get("/health")
def health() -> dict:
    return {"ok": True, "data": bootstrap.state}


@router.get("/meta")
def meta() -> dict:
    with get_conn() as conn:
        counts = conn.execute(
            "SELECT season, COUNT(*) AS rows, COUNT(DISTINCT game_id) AS games, MAX(date) AS last_date "
            "FROM box_scores GROUP BY season ORDER BY season").fetchall()
        inj = conn.execute("SELECT MAX(fetched_at) AS f, COUNT(*) AS n FROM injuries").fetchone()
    source = get_meta("data_source")
    return {
        "app": "CourtVision AI",
        "bootstrap": bootstrap.state,
        "data": {
            "source": source,
            "is_demo": source == "demo",
            "source_label": ("OFFLINE DEMO DATA - fictional players" if source == "demo"
                             else "Real NBA box scores, schedule & injuries via ESPN public API" if source == "espn"
                             else "No data loaded"),
            "last_refresh_utc": get_meta("last_refresh_utc"),
            "current_season": season_label(CURRENT_SEASON),
            "seasons": [{"season": season_label(r["season"]), "player_games": r["rows"], "games": r["games"],
                         "last_date": r["last_date"]} for r in counts],
            "injuries": {"count": inj["n"], "fetched_at": inj["f"]},
        },
        "today": today().isoformat(),
        "windows": {k: week_window(k).as_dict() for k in ("current", "next")},
        "gemini": gemini.status(),
        "model": {k: v for k, v in ml_model.summary().items() if k in
                  {"trained", "trained_at", "algorithm", "split_date", "data_through", "rows", "use_ml", "pct_method"}},
        "categories": [{"key": c.key, "label": c.label, "name": c.name, "higher_is_better": c.higher_is_better,
                        "is_pct": c.is_pct} for c in CATEGORIES],
    }


@router.post("/admin/refresh")
def refresh() -> dict:
    if settings.data_mode == "demo":
        raise HTTPException(400, "Refresh is disabled in demo mode")
    bootstrap.start_background(force_refresh=True)
    return {"started": True}


# ----------------------------------------------------------------------------- today
@router.get("/today")
def today_view(day: str = "auto", roster_id: int | None = None) -> dict:
    """Slate, your players, top projections, pickups and injuries for one day (no Gemini: instant)."""
    require_data()
    try:
        return today_svc.build(day, roster_id)
    except ValueError:
        raise HTTPException(400, "day must be 'auto', 'today', 'tomorrow' or an ISO date") from None


# ----------------------------------------------------------------------------- players
@router.get("/players/search")
def search_players(q: str = "", limit: int = Query(15, ge=1, le=50)) -> list[dict]:
    require_data()
    proj = get_projection("next")
    return player_svc.search(q, limit, proj.players)


@router.get("/players/{player_id}")
def player_detail(player_id: int, week: str = "next") -> dict:
    proj = get_projection(week)
    profile = player_svc.player_profile(player_id)
    if profile is None:
        raise HTTPException(404, "Player not found")
    return {"profile": profile, "projection": player_row(proj, player_id),
            "explain": explain_player(proj, player_id), "window": proj.window.as_dict(), "methods": proj.methods}


@router.get("/players/default/pair")
def default_pair() -> dict:
    """Default comparison: Nikola Jokic vs Victor Wembanyama (falls back to the top two players)."""
    require_data()
    ids = [player_svc.find_by_name("Nikola Jokic"), player_svc.find_by_name("Victor Wembanyama")]
    if None in ids:
        top = get_projection("next").players.index[:2]
        ids = [int(top[0]), int(top[1])]
    return {"a": ids[0], "b": ids[1]}


# ----------------------------------------------------------------------------- compare
@router.get("/compare")
def compare(a: int, b: int, week: str = "next") -> dict:
    proj = get_projection(week)
    try:
        return comparison.build(proj, a, b)
    except KeyError:
        raise HTTPException(404, "Player not found") from None


class CompareAIRequest(BaseModel):
    a: int
    b: int
    week: str = "next"


@router.post("/ai/compare")
def compare_ai(req: CompareAIRequest) -> dict:
    proj = get_projection(req.week)
    try:
        comp = comparison.build(proj, req.a, req.b)
    except KeyError:
        raise HTTPException(404, "Player not found") from None
    return comparison.ai_recommendation(comp).model_dump()


# ----------------------------------------------------------------------------- rankings
@router.get("/rankings/weekly")
def weekly_rankings(week: str = "next", sort: str = "value", position: str | None = None,
                    team: str | None = None, search: str | None = None,
                    min_games: int = Query(1, ge=0, le=5), limit: int = Query(150, ge=1, le=600),
                    order: str | None = Query(None, pattern="^(asc|desc)$")) -> dict:
    proj = get_projection(week)
    desc = None if order is None else order == "desc"
    return rankings.weekly(proj, sort, position, team, search, min_games, limit, desc)


@router.post("/ai/rankings")
def rankings_ai(week: str = "next") -> dict:
    proj = get_projection(week)
    return rankings.ai_insight(proj, schedule_summary(proj.window)).model_dump()


@router.get("/schedule/week")
def schedule(week: str = "next") -> dict:
    require_data()
    try:
        return schedule_summary(week_window(week))
    except ValueError:
        raise HTTPException(400, "invalid week") from None


# ----------------------------------------------------------------------------- model
@router.get("/model")
def model_info() -> dict:
    summary = ml_model.summary()
    return {
        **summary,
        "baseline": {
            "description": ("Weighted average: 50% season (current season shrunk toward the prior two seasons with "
                            "10 games of credibility) + 30% last-10 + 20% last-5, multiplied by an opponent "
                            "factor (shrunk toward league average, half-strength, clipped to ±15%)."),
        },
        "shooting": ("Projected makes = projected attempts x season-blended FG%/FT% when validation shows it "
                     "beats predicting makes directly."),
        "uncertainty": ("Per-game SD = player's last-30-game SD shrunk toward the model's validation residual SD; "
                        "weekly SD adds availability risk. Intervals shown are 80%."),
    }
