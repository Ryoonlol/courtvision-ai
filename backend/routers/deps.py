"""Shared request helpers."""
from __future__ import annotations

from fastapi import HTTPException

from data import bootstrap
from services.projections import Projection, project
from services.schedule import week_window


def require_data() -> None:
    if not bootstrap.has_data():
        raise HTTPException(503, detail={"status": bootstrap.state["status"], "message": bootstrap.state["message"]})


def get_projection(week: str) -> Projection:
    require_data()
    try:
        window = week_window(week)
    except ValueError:
        raise HTTPException(400, "week must be 'current', 'next' or an ISO date") from None
    return project(window)
