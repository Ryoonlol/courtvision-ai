import json

from pydantic import BaseModel

from services import gemini_service
from services.gemini_service import GeminiService, grounding_check


class Insight(BaseModel):
    headline: str
    pick: str


def _fallback():
    return Insight(headline="rule-based", pick="A")


class FakeError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return type("Resp", (), {"text": r})()


def _service(responses, monkeypatch):
    svc = GeminiService()
    svc._client = type("Client", (), {"models": FakeModels(responses)})()
    monkeypatch.setattr(gemini_service.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini_service, "_cache_get", lambda k: None)
    monkeypatch.setattr(gemini_service, "_cache_put", lambda *a: None)
    return svc


def test_fallback_when_no_api_key():
    svc = GeminiService()
    assert not svc.available
    res = svc.generate("t", "explain", {"x": 1}, Insight, _fallback)
    assert res.source == "fallback"
    assert res.data["headline"] == "rule-based"
    assert "GEMINI_API_KEY" in res.notice


def test_valid_structured_response_is_validated(monkeypatch):
    svc = _service([json.dumps({"headline": "Jokic wins 25.4 to 20.1", "pick": "Jokic"})], monkeypatch)
    res = svc.generate("t", "explain", {"a": 25.4, "b": 20.1}, Insight, _fallback)
    assert res.source == "gemini"
    assert res.data["pick"] == "Jokic"
    assert res.grounding["passed"]


def test_invalid_json_falls_back(monkeypatch):
    svc = _service(["not json"], monkeypatch)
    res = svc.generate("t", "explain", {"a": 1}, Insight, _fallback)
    assert res.source == "fallback"


def test_schema_mismatch_falls_back(monkeypatch):
    svc = _service([json.dumps({"headline": "missing pick"})], monkeypatch)
    assert svc.generate("t", "explain", {}, Insight, _fallback).source == "fallback"


def test_rate_limit_is_retried(monkeypatch):
    svc = _service([FakeError(429), json.dumps({"headline": "ok", "pick": "B"})], monkeypatch)
    res = svc.generate("t", "explain", {}, Insight, _fallback)
    assert res.source == "gemini"
    assert svc._client.models.calls == 2


def test_persistent_errors_fall_back_with_notice(monkeypatch):
    svc = _service([FakeError(503)] * 3, monkeypatch)
    res = svc.generate("t", "explain", {}, Insight, _fallback)
    assert res.source == "fallback"
    assert "503" in res.notice


def test_auth_error_is_not_retried(monkeypatch):
    svc = _service([FakeError(403)], monkeypatch)
    res = svc.generate("t", "explain", {}, Insight, _fallback)
    assert res.source == "fallback" and svc._client.models.calls == 1


def test_hallucinated_numbers_are_rejected(monkeypatch):
    text = json.dumps({"headline": "He averages 31.7 pts, 14.2 reb, 12.9 ast and 3.3 stl, 2.8 blk", "pick": "A"})
    svc = _service([text], monkeypatch)
    res = svc.generate("t", "explain", {"pts": 25.4}, Insight, _fallback)
    assert res.source == "fallback"


def test_grounding_check_accepts_rounding_and_percentages():
    payload = {"fg_pct": 0.5381, "pts": 76.2774, "games": 3}
    g = grounding_check({"s": "Shoots 53.8% and scores 76.3 points over 3 games in 9-cat"}, payload)
    assert g["ungrounded"] == []
    g2 = grounding_check({"s": "Scores 88.8 points"}, payload)
    assert g2["ungrounded"] == ["88.8"]


def test_grounding_ignores_per_minute_units():
    g = grounding_check({"s": "Usage rose 5.2 per 36 minutes, stocks per-36 and Usage/36 climbed"}, {"usage": 5.2})
    assert g["ungrounded"] == []


def test_compact_enforces_word_and_item_limits():
    from services.gemini_service import brief, compact

    class M(BaseModel):
        title: str = brief("t", words=4)
        items: list[str] = brief("i", words=3, items=2)

    m = compact(M(title="One two three four five six. Seven.", items=["a b c d e", "x", "y"]))
    assert m.title == "One two three four…" and m.items == ["a b c…", "x"]
    assert compact(M(title="Short one. Then more words here", items=[])).title == "Short one."
