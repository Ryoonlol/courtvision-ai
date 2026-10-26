"""agy CLI provider: subprocess handling, schema inlining, service + assistant integration (fake binary)."""
import dataclasses
import json
import stat

import pytest
from pydantic import BaseModel

from services import agy_client


def _fake_agy(tmp_path, envelope: dict | None = None, exit_code: int = 0, raw: str | None = None):
    """Write a fake `agy` that records its argv and prints a canned JSON envelope."""
    out = raw if raw is not None else json.dumps(envelope)
    script = tmp_path / "agy"
    script.write_text(f"""#!/bin/sh
printf '%s\\n' "$@" > {tmp_path}/argv.txt
cat <<'JSON'
{out}
JSON
exit {exit_code}
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def use_fake(monkeypatch, tmp_path):
    def install(**kw):
        script = _fake_agy(tmp_path, **kw)
        monkeypatch.setattr(agy_client, "settings", dataclasses.replace(agy_client.settings, agy_bin=str(script)))
        monkeypatch.setattr(agy_client, "WORKDIR", tmp_path / "ws")
        return tmp_path
    return install


class Pick(BaseModel):
    pick: str
    reason: str


class Outer(BaseModel):
    items: list[Pick]


def test_inline_refs_removes_defs():
    schema = agy_client.inline_refs(Outer.model_json_schema())
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    assert schema["properties"]["items"]["items"]["properties"]["pick"]["type"] == "string"


def test_generate_json_returns_structured_output_and_passes_flags(use_fake):
    tmp = use_fake(envelope={"status": "SUCCESS", "structured_output": {"pick": "A", "reason": "r"}})
    out = agy_client.generate_json("hello", Pick.model_json_schema())
    assert out == {"pick": "A", "reason": "r"}
    argv = (tmp / "argv.txt").read_text().splitlines()
    assert argv[:2] == ["-p", "hello"]
    for flag in ("--model", "--mode", "--output-format", "--json-schema", "--print-timeout"):
        assert flag in argv
    assert argv[argv.index("--mode") + 1] == "plan"


@pytest.mark.parametrize("kw", [
    {"envelope": {"status": "ERROR", "error": "quota"}},
    {"envelope": {"status": "SUCCESS"}},                 # no structured output
    {"envelope": {"status": "SUCCESS"}, "exit_code": 2},
    {"raw": "not json"},
])
def test_generate_json_errors(use_fake, kw):
    use_fake(**kw)
    with pytest.raises(agy_client.AgyError):
        agy_client.generate_json("x", Pick.model_json_schema())


def test_missing_binary(monkeypatch):
    monkeypatch.setattr(agy_client, "settings", dataclasses.replace(agy_client.settings, agy_bin="/nope/agy"))
    with pytest.raises(agy_client.AgyError):
        agy_client.run("x")


def _agy_service(monkeypatch, responses):
    from services import gemini_service
    svc = gemini_service.GeminiService()
    svc.provider, svc.model = "agy", "gemini-test"
    seq = list(responses)

    def fake(prompt, schema, timeout=None):
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(gemini_service.agy_client, "generate_json", fake)
    monkeypatch.setattr(gemini_service, "_cache_get", lambda k: None)
    monkeypatch.setattr(gemini_service, "_cache_put", lambda *a: None)
    return svc


def test_service_uses_agy_and_validates(monkeypatch):
    svc = _agy_service(monkeypatch, [{"pick": "Jokic", "reason": "25.4 points"}])
    res = svc.generate("t", "explain", {"pts": 25.4}, Pick, lambda: Pick(pick="fb", reason="fb"))
    assert res.source == "gemini" and res.model == "gemini-test via agy" and res.data["pick"] == "Jokic"


def test_service_retries_once_then_falls_back(monkeypatch):
    err = agy_client.AgyError("boom")
    svc = _agy_service(monkeypatch, [err, err])
    res = svc.generate("t", "explain", {}, Pick, lambda: Pick(pick="fb", reason="fb"))
    assert res.source == "fallback" and "agy" in res.notice


def test_service_invalid_schema_falls_back(monkeypatch):
    svc = _agy_service(monkeypatch, [{"pick": "only"}])
    assert svc.generate("t", "explain", {}, Pick, lambda: Pick(pick="fb", reason="fb")).source == "fallback"


def test_assistant_agy_tool_loop(monkeypatch, demo_db):
    from services import assistant
    from services.projections import project
    from services.schedule import week_window
    proj = project(week_window("next"))
    top = proj.players.iloc[0]
    answer = f"{top['name']} leads with value {round(float(top['value']), 2)}."
    steps = [
        {"action": "call_tool", "tool": "rankings", "args_json": '{"limit": 3}'},
        {"action": "call_tool", "tool": "rankings", "args_json": "not json"},
        {"action": "final_answer", "answer": answer},
    ]
    prompts = []

    def fake(prompt, schema):
        prompts.append(prompt)
        return steps.pop(0)
    monkeypatch.setattr(assistant.gemini, "provider", "agy")
    monkeypatch.setattr(assistant.gemini, "generate_json", fake)
    res = assistant.ask(proj, "Who is the top player?", [], None, None)
    assert res["source"] == "gemini" and res["answer"] == answer
    assert [t["tool"] for t in res["tool_calls"]] == ["rankings", "rankings"]
    assert [t["ok"] for t in res["tool_calls"]] == [True, False]
    assert "TOOL RESULTS SO FAR" in prompts[1] and top["name"] in prompts[1]
    assert res["grounding"]["passed"]
