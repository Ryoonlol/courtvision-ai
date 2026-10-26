"""Gemini integration (official ``google-genai`` SDK).

Python computes every statistic; Gemini only *explains* structured results. Each call:
  * sends a JSON payload of computed numbers plus strict grounding instructions,
  * requests structured JSON output validated against a Pydantic schema,
  * retries rate-limit / transient server errors with exponential backoff,
  * runs a grounding check that flags numbers not present in the payload,
  * caches responses in SQLite (same payload -> no repeat API call),
  * falls back to a deterministic, rule-based explanation when Gemini is unavailable.
The API key is read server-side only and never sent to the frontend.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeVar

from pydantic import BaseModel, Field, ValidationError

from core.config import settings
from core.db import get_conn
from services import agy_client

log = logging.getLogger("courtvision.gemini")

try:  # the SDK is a hard dependency, but keep the app bootable if it is missing
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover
    genai = None
    genai_errors = None
    genai_types = None

T = TypeVar("T", bound=BaseModel)

CACHE_TTL = timedelta(hours=6)
RETRYABLE = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_UNGROUNDED = 3

BASE_INSTRUCTIONS = """You are CourtVision AI, an expert fantasy basketball analyst for head-to-head
9-category leagues (PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO).

Hard rules:
- Use ONLY the numbers in the provided JSON. Never invent statistics, injuries, trades, news or
  schedules. If something is not in the data, say it is not available.
- All projections were computed by CourtVision's statistical model; you explain them, you do
  not recompute or change them. Quote numbers exactly as given (you may round to one decimal).
- Turnovers: fewer is better. FG% and FT% are volume-weighted (makes / attempts), so a player's
  impact depends on attempts as well as percentage.
- z-scores measure value relative to a 12-team draftable pool; 0 = average starter.
- Be concise, specific and actionable. Plain text only inside JSON string fields (no markdown).

Style (strict): the reader is a busy fantasy manager on a phone. Write short fragments, not paragraphs.
Respect every "max N words" / "max N items" limit in the schema. Lead with the player or number,
e.g. "BLK: Wemby 10.6 vs 2.5". No filler, no restating the question.
Plain words only: never write "z-score", "z-sum" or "z"; say "above/below average" or use the real
stat (e.g. "10.6 blocks"). Call 9-cat value "fantasy value".
"""
STYLE_VERSION = "concise-v3"  # part of the cache key: bump when output style changes


class AIResponse(BaseModel):
    source: str              # "gemini" | "fallback"
    model: str | None
    data: dict
    cached: bool = False
    notice: str | None = None
    grounding: dict | None = None


class GeminiService:
    def __init__(self) -> None:
        self.model = settings.gemini_model
        self.provider: str | None = None   # "sdk" | "agy" | None
        self._client = None
        self.last_error: str | None = None
        want = settings.gemini_provider
        if want in ("auto", "sdk") and settings.gemini_api_key and genai is not None:
            try:
                self._client = genai.Client(
                    api_key=settings.gemini_api_key,
                    http_options=genai_types.HttpOptions(timeout=int(settings.gemini_timeout_s * 1000)),
                )
                self.provider = "sdk"
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"Gemini client init failed: {exc}"
                log.warning(self.last_error)
        if self.provider is None and want in ("auto", "agy") and agy_client.binary():
            self.provider = "agy"
            self.model = settings.agy_model

    @property
    def available(self) -> bool:
        return self.provider == "agy" or self._client is not None

    def status(self) -> dict:
        return {"configured": self.available, "available": self.available, "provider": self.provider,
                "model": self.model, "label": self.label,
                "sdk": "agy CLI" if self.provider == "agy" else "google-genai", "last_error": self.last_error}

    @property
    def label(self) -> str:
        return f"{self.model} via agy" if self.provider == "agy" else self.model

    # ------------------------------------------------------------------ public API
    def generate(self, task: str, instructions: str, payload: dict, schema: type[T],
                 fallback: Callable[[], T], use_cache: bool = True) -> AIResponse:
        """Explain ``payload`` with Gemini, returning schema-validated data or a fallback."""
        if not self.available:
            reason = ("no GEMINI_API_KEY and no agy CLI found" if not settings.gemini_configured
                      else (self.last_error or "Gemini client unavailable"))
            return self._fallback(fallback, f"Rule-based explanation ({reason}).")

        key = _cache_key(self.model, task, instructions, payload)
        if use_cache and (hit := _cache_get(key)) is not None:
            try:
                return AIResponse(source="gemini", model=self.label, data=schema.model_validate(hit["data"]).model_dump(),
                                  cached=True, grounding=hit.get("grounding"))
            except ValidationError:
                pass

        prompt = (f"{instructions}\n\nDATA (JSON computed by CourtVision; the only facts you may use):\n"
                  f"{json.dumps(payload, separators=(',', ':'), default=_json_default)}")
        try:
            if self.provider == "agy":
                data = compact(schema.model_validate(self._agy_json(prompt, schema)))
            else:
                data = compact(schema.model_validate(json.loads(self._call(prompt, schema))))
        except (ValidationError, json.JSONDecodeError) as exc:
            self.last_error = f"Invalid structured response: {str(exc)[:200]}"
            log.warning(self.last_error)
            return self._fallback(fallback, "Gemini returned an invalid response; showing rule-based explanation.")
        except Exception as exc:  # noqa: BLE001 - API errors, timeouts, network
            self.last_error = _describe_error(exc)
            log.warning("Gemini call failed: %s", self.last_error)
            return self._fallback(fallback, f"Gemini unavailable ({self.last_error}); showing rule-based explanation.")

        grounding = grounding_check(data.model_dump(), payload)
        if len(grounding["ungrounded"]) > MAX_UNGROUNDED:
            log.warning("Rejected ungrounded Gemini output: %s", grounding["ungrounded"])
            return self._fallback(fallback, "Gemini cited numbers not in the data; showing rule-based explanation.")
        self.last_error = None
        _cache_put(key, task, self.model, {"data": data.model_dump(), "grounding": grounding})
        return AIResponse(source="gemini", model=self.label, data=data.model_dump(), grounding=grounding)

    def generate_json(self, prompt: str, schema: dict) -> dict:
        """Schema-constrained JSON via agy (used by the assistant's tool loop)."""
        if self.provider != "agy":
            raise RuntimeError("generate_json is only used with the agy provider")
        return self._agy_call(prompt, schema)

    def _agy_json(self, prompt: str, schema: type[BaseModel]) -> dict:
        full = (f"{BASE_INSTRUCTIONS}\n{prompt}\n\nRespond only with the JSON object described by the schema. "
                "Do not use any tools, files or commands.")
        return self._agy_call(full, schema.model_json_schema())

    def _agy_call(self, prompt: str, schema: dict) -> dict:
        last: Exception | None = None
        for attempt in range(2):  # one retry: CLI hiccups and timeouts are usually transient
            try:
                return agy_client.generate_json(prompt, schema)
            except agy_client.AgyError as exc:
                last = exc
                log.info("agy call failed (attempt %d): %s", attempt + 1, exc)
        raise last

    def request(self, contents, config):
        """Raw generate_content call with retries (used by the tool-calling assistant)."""
        if self._client is None:
            raise RuntimeError("Gemini is not configured")
        return self._request(contents, config)

    # ------------------------------------------------------------------ internals
    def _call(self, prompt: str, schema: type[BaseModel] | None, system: str | None = None) -> str:
        config_kwargs = {"system_instruction": system or BASE_INSTRUCTIONS, "temperature": 0.35}
        if schema is not None:
            config_kwargs.update(response_mime_type="application/json", response_schema=schema)
        config = genai_types.GenerateContentConfig(**config_kwargs)
        text = self._request(prompt, config).text
        if not text:
            raise RuntimeError("empty response (possibly blocked by safety filters)")
        return text

    def _request(self, contents, config):
        delay = 1.5
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._client.models.generate_content(model=self.model, contents=contents, config=config)
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", None)
                if attempt < MAX_ATTEMPTS and (code in RETRYABLE or _is_timeout(exc)):
                    log.info("Gemini %s (attempt %d), retrying in %.1fs", code or type(exc).__name__, attempt, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        raise RuntimeError("unreachable")

    def _fallback(self, fallback: Callable[[], T], notice: str) -> AIResponse:
        return AIResponse(source="fallback", model=None, data=compact(fallback()).model_dump(), notice=notice)


# ---------------------------------------------------------------------- brevity
class Limits:
    """Brevity limits attached to a field. Called by pydantic when building the JSON schema, where it
    only adds the standard ``maxItems`` keyword; the word limit lives in the field description."""

    def __init__(self, max_words: int | None, max_items: int | None):
        self.max_words, self.max_items = max_words, max_items

    def __call__(self, schema: dict) -> None:
        if self.max_items:
            schema["maxItems"] = self.max_items


def brief(description: str, words: int | None = None, items: int | None = None, **kw):
    """Field with a word/item limit that is shown to Gemini and enforced by ``compact``."""
    limits = []
    if items:
        limits.append(f"max {items} items")
    if words:
        limits.append(f"max {words} words{' each' if items else ''}")
    return Field(description=f"{description} ({', '.join(limits)})" if limits else description,
                 json_schema_extra=Limits(words, items), **kw)


def shorten(text: str, max_words: int) -> str:
    """Trim to the first sentence if that fits, else to ``max_words`` words with an ellipsis."""
    words = text.split()
    if len(words) <= max_words:
        return text
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    if len(first.split()) <= max_words:
        return first
    return " ".join(words[:max_words]).rstrip(",;:") + "…"


def compact(obj: T) -> T:
    """Enforce ``brief`` limits on a validated model (recursively): trims lists and long strings."""
    updates = {}
    for name, field in type(obj).model_fields.items():
        lim = field.json_schema_extra if isinstance(field.json_schema_extra, Limits) else Limits(None, None)
        value = getattr(obj, name)
        max_items, max_words = lim.max_items, lim.max_words
        if isinstance(value, list):
            if max_items:
                value = value[:max_items]
            value = [compact(v) if isinstance(v, BaseModel) else
                     shorten(v, max_words) if isinstance(v, str) and max_words else v for v in value]
        elif isinstance(value, BaseModel):
            value = compact(value)
        elif isinstance(value, str) and max_words:
            value = shorten(value, max_words)
        updates[name] = value
    return obj.model_copy(update=updates)


# ---------------------------------------------------------------------- grounding
_NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(%?)")
_UNIT_BEFORE = re.compile(r"(per[\s-]|/)$", re.IGNORECASE)


def _payload_numbers(obj, acc: set[float]) -> set[float]:
    if isinstance(obj, dict):
        for v in obj.values():
            _payload_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _payload_numbers(v, acc)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        x = float(obj)
        for v in (x, abs(x), x * 100, abs(x) * 100):
            acc.add(round(v, 1))
            acc.add(round(v, 0))
    elif isinstance(obj, str):
        for m in _NUM_RE.finditer(obj):
            acc.add(round(float(m.group(1)), 1))
    return acc


def grounding_check(response: dict, payload: dict) -> dict:
    """Find numbers in Gemini's text that do not appear (after rounding) in the payload.

    Small integers (<= 9, e.g. "9-cat", "5-4", "3 games") are always allowed.
    """
    allowed = _payload_numbers(payload, set())
    texts: list[str] = []

    def collect(o):
        if isinstance(o, str):
            texts.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for v in o:
                collect(v)

    collect(response)
    ungrounded, checked = [], 0
    for text in texts:
        for m in _NUM_RE.finditer(text):
            val = float(m.group(1))
            if val <= 9 and val.is_integer():
                continue
            if _UNIT_BEFORE.search(text[max(0, m.start() - 5):m.start()]):
                continue  # unit phrases such as "per 36 minutes" are not statistics
            checked += 1
            candidates = {round(val, 1), round(val, 0)}
            if not any(any(abs(c - a) <= 0.11 for a in allowed) for c in candidates):
                ungrounded.append(m.group(0))
    return {"numbers_checked": checked, "ungrounded": ungrounded,
            "passed": len(ungrounded) <= MAX_UNGROUNDED}


# ---------------------------------------------------------------------- cache
def _cache_key(model: str, task: str, instructions: str, payload: dict) -> str:
    raw = json.dumps([model, task, instructions, payload, STYLE_VERSION], sort_keys=True, default=_json_default)
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT response, created_at FROM ai_cache WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    if datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"]) > CACHE_TTL:
        return None
    return json.loads(row["response"])


def _cache_put(key: str, task: str, model: str, value: dict) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO ai_cache(key, task, model, response, created_at) VALUES(?,?,?,?,?)",
                     (key, task, model, json.dumps(value), datetime.now(timezone.utc).isoformat()))


def _json_default(o):
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def _is_timeout(exc: Exception) -> bool:
    return "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, agy_client.AgyError):
        return f"agy: {exc}"
    code = getattr(exc, "code", None)
    if code == 429:
        return "rate limit / quota exceeded (HTTP 429)"
    if code in (401, 403) or "API key not valid" in str(exc):
        return f"API key rejected (HTTP {code}) - check GEMINI_API_KEY"
    if code == 404:
        return f"model '{settings.gemini_model}' not found (HTTP 404) - check GEMINI_MODEL"
    if code:
        return f"HTTP {code}: {str(exc)[:120]}"
    return f"{type(exc).__name__}: {str(exc)[:120]}"


gemini = GeminiService()
