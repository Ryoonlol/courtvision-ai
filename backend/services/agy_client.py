"""Gemini access through the local Antigravity CLI (``agy``).

The backend runs ``agy -p <prompt> --model <gemini model> --mode plan --output-format json`` in an empty
working directory, so the agent has nothing to read or edit. With ``--json-schema`` the CLI enforces
structured output and returns it in ``structured_output``. Authentication is whatever the local ``agy``
install is signed in with, so no API key is needed.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import threading

from core.config import BACKEND_DIR, settings

WORKDIR = BACKEND_DIR / "storage" / "agy_workspace"
_slots = threading.BoundedSemaphore(3)   # at most 3 concurrent agy processes


class AgyError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def binary() -> str | None:
    return shutil.which(settings.agy_bin)


def inline_refs(schema: dict) -> dict:
    """Resolve pydantic ``$defs`` references so the CLI receives a self-contained schema."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def run(prompt: str, schema: dict | None = None, timeout: float | None = None, model: str | None = None) -> dict:
    """Run one non-interactive agy turn. Returns the parsed CLI JSON envelope."""
    exe = binary()
    if not exe:
        raise AgyError(f"agy CLI not found ('{settings.agy_bin}')")
    timeout = timeout or settings.agy_timeout_s
    WORKDIR.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-p", prompt, "--model", model or settings.agy_model, "--mode", "plan", "--output-format", "json",
           "--print-timeout", f"{int(timeout)}s"]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(inline_refs(schema), separators=(",", ":"))]
    with _slots:
        try:
            proc = subprocess.run(cmd, cwd=WORKDIR, capture_output=True, text=True, timeout=timeout + 15)
        except subprocess.TimeoutExpired:
            raise AgyError(f"agy timed out after {int(timeout)}s", 504) from None
    if proc.returncode != 0:
        raise AgyError(f"agy exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:200]}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise AgyError(f"agy returned non-JSON output: {proc.stdout.strip()[:200]}") from None
    if envelope.get("status") != "SUCCESS":
        raise AgyError(f"agy status {envelope.get('status')}: {str(envelope.get('error') or envelope)[:200]}")
    return envelope


def generate_json(prompt: str, schema: dict, timeout: float | None = None, model: str | None = None) -> dict:
    """Structured generation: returns the object matching ``schema``."""
    env = run(prompt, schema, timeout, model)
    out = env.get("structured_output")
    if isinstance(out, dict):
        return out
    raise AgyError("agy returned no structured_output")
