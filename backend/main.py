"""CourtVision AI - FastAPI application entrypoint.

Run from backend/:  uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.db import init_db
from data import bootstrap
from routers.api import router
from routers.phase2 import router as phase2_router
from routers.phase3 import router as phase3_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    bootstrap.start_background()
    yield


app = FastAPI(title="CourtVision AI", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(phase2_router)
app.include_router(phase3_router)
