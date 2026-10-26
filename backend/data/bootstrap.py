"""Startup data lifecycle: ensure data exists, refresh it when stale, keep the model trained."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from core.config import settings
from core.db import get_conn, get_meta, init_db
from data import repository as repo

log = logging.getLogger("courtvision.bootstrap")
REFRESH_EVERY = timedelta(hours=3)
RETRAIN_EVERY = timedelta(hours=24)

state = {"status": "starting", "message": "Starting up", "updated_at": None}
_lock = threading.Lock()


def _set(status: str, message: str) -> None:
    state.update(status=status, message=message, updated_at=datetime.now(timezone.utc).isoformat())
    log.info("[%s] %s", status, message)


def has_data() -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM box_scores").fetchone()[0] > 0


def _age(meta_key: str) -> timedelta | None:
    raw = get_meta(meta_key)
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts


def _train() -> None:
    from services import ml_model
    _set("training", "Training projection model on historical box scores")
    try:
        ml_model.train()
    except Exception as exc:  # noqa: BLE001 - baseline projections still work without the model
        log.warning("model training failed, using baseline only: %s", exc)


def ensure_data(force_refresh: bool = False) -> None:
    if not _lock.acquire(blocking=False):
        return
    try:
        init_db()
        from data import demo_data, ingest
        source = get_meta("data_source")
        if settings.data_mode == "demo":
            if source != "demo" or not has_data():
                _set("loading", "Generating offline demo dataset")
                demo_data.generate()
                _train()
        elif not has_data():
            _set("loading", "Downloading NBA box scores from ESPN (first run, ~1-2 minutes)")
            try:
                ingest.run_full(sorted(ingest.SEASON_WINDOWS))
                if not has_data():
                    raise RuntimeError("no box scores ingested")
            except Exception as exc:  # noqa: BLE001
                if settings.data_mode == "live":
                    _set("error", f"Live data unavailable: {exc}")
                    return
                log.warning("live ingest failed (%s); falling back to DEMO data", exc)
                _set("loading", "Live data unavailable - generating offline demo dataset")
                demo_data.generate()
            _train()
        elif source == "espn" and (force_refresh or (settings.refresh_on_startup and
                                                     (_age("last_refresh_utc") or REFRESH_EVERY) >= REFRESH_EVERY)):
            _set("refreshing", "Refreshing recent results, schedule and injuries")
            try:
                ingest.run_refresh()
            except Exception as exc:  # noqa: BLE001 - cached data still usable
                log.warning("refresh failed, using cached data: %s", exc)
        from services import ml_model
        age = _age("model_trained_at")
        if ml_model.load_model() is None or age is None or age > RETRAIN_EVERY:
            _train()
        repo.clear_cache()
        _set("ready", "Data ready")
    except Exception as exc:  # noqa: BLE001
        log.exception("bootstrap failed")
        _set("error", str(exc))
    finally:
        _lock.release()


def start_background(force_refresh: bool = False) -> None:
    threading.Thread(target=ensure_data, kwargs={"force_refresh": force_refresh}, daemon=True,
                     name="courtvision-bootstrap").start()
