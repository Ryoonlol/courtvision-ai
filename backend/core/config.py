"""Central configuration loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

# .env may live at the project root or inside backend/
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    gemini_model: str
    gemini_timeout_s: float
    gemini_provider: str  # "auto" | "agy" | "sdk"
    agy_bin: str
    agy_model: str
    agy_timeout_s: float
    forecast_model: str
    forecast_batch: int
    data_mode: str  # "live" | "demo" | "auto"
    db_path: Path
    model_path: Path
    timezone: str
    refresh_on_startup: bool
    cors_origins: list[str]

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    storage = BACKEND_DIR / "storage"
    storage.mkdir(exist_ok=True)
    data_mode = os.getenv("DATA_MODE", "auto").lower()
    # Demo data lives in its own files so it can never overwrite cached real NBA data.
    suffix = "_demo" if data_mode == "demo" else ""
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        gemini_timeout_s=float(os.getenv("GEMINI_TIMEOUT_S", "45")),
        gemini_provider=os.getenv("GEMINI_PROVIDER", "auto").lower(),
        agy_bin=os.getenv("AGY_BIN", "agy"),
        agy_model=os.getenv("AGY_MODEL", "gemini-3.8-flash-low"),
        agy_timeout_s=float(os.getenv("AGY_TIMEOUT_S", "120")),
        forecast_model=os.getenv("FORECAST_MODEL", os.getenv("AGY_MODEL", "gemini-3.8-flash-low")),
        forecast_batch=int(os.getenv("FORECAST_BATCH", "20")),
        data_mode=data_mode,
        db_path=Path(os.getenv("COURTVISION_DB", storage / f"courtvision{suffix}.db")),
        model_path=Path(os.getenv("COURTVISION_MODEL", storage / f"projection_model{suffix}.joblib")),
        timezone="America/New_York",
        refresh_on_startup=_bool("REFRESH_ON_STARTUP", True),
        cors_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    )


settings = load_settings()
