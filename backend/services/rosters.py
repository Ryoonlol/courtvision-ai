"""Fantasy rosters saved in SQLite (manual roster builder) plus a sample snake-draft helper."""
from __future__ import annotations

from datetime import datetime, timezone

from core.db import get_conn
from services.projections import Projection

MAX_ROSTER = 20
KINDS = {"mine", "opponent", "other"}


class RosterError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_rosters() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM rosters ORDER BY kind != 'mine', updated_at DESC").fetchall()
        players = conn.execute("SELECT roster_id, player_id FROM roster_players ORDER BY roster_id, slot").fetchall()
    by_roster: dict[int, list[int]] = {}
    for p in players:
        by_roster.setdefault(p["roster_id"], []).append(p["player_id"])
    return [{**dict(r), "player_ids": by_roster.get(r["id"], [])} for r in rows]


def get_roster(roster_id: int) -> dict | None:
    return next((r for r in list_rosters() if r["id"] == roster_id), None)


def _validate(name: str | None, kind: str | None, player_ids: list[int] | None) -> None:
    if name is not None and not name.strip():
        raise RosterError("Roster name cannot be empty")
    if kind is not None and kind not in KINDS:
        raise RosterError(f"kind must be one of {sorted(KINDS)}")
    if player_ids is not None:
        if len(player_ids) > MAX_ROSTER:
            raise RosterError(f"A roster can hold at most {MAX_ROSTER} players")
        if len(set(player_ids)) != len(player_ids):
            raise RosterError("A player can only appear once on a roster")


def create_roster(name: str, kind: str = "mine", player_ids: list[int] | None = None) -> dict:
    player_ids = player_ids or []
    _validate(name, kind, player_ids)
    now = _now()
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO rosters(name, kind, created_at, updated_at) VALUES(?,?,?,?)",
                           (name.strip(), kind, now, now))
        rid = cur.lastrowid
        _write_players(conn, rid, player_ids)
    return get_roster(rid)


def update_roster(roster_id: int, name: str | None = None, kind: str | None = None,
                  player_ids: list[int] | None = None) -> dict:
    if get_roster(roster_id) is None:
        raise KeyError(roster_id)
    _validate(name, kind, player_ids)
    with get_conn() as conn:
        if name is not None:
            conn.execute("UPDATE rosters SET name=? WHERE id=?", (name.strip(), roster_id))
        if kind is not None:
            conn.execute("UPDATE rosters SET kind=? WHERE id=?", (kind, roster_id))
        if player_ids is not None:
            conn.execute("DELETE FROM roster_players WHERE roster_id=?", (roster_id,))
            _write_players(conn, roster_id, player_ids)
        conn.execute("UPDATE rosters SET updated_at=? WHERE id=?", (_now(), roster_id))
    return get_roster(roster_id)


def delete_roster(roster_id: int) -> None:
    with get_conn() as conn:
        if conn.execute("DELETE FROM rosters WHERE id=?", (roster_id,)).rowcount == 0:
            raise KeyError(roster_id)


def _write_players(conn, roster_id: int, player_ids: list[int]) -> None:
    for slot, pid in enumerate(player_ids):
        conn.execute("INSERT INTO roster_players(roster_id, player_id, slot) VALUES(?,?,?)", (roster_id, pid, slot))


def rostered_elsewhere(roster_id: int | None) -> set[int]:
    """Players on any saved roster other than ``roster_id`` (treated as unavailable)."""
    return {p for r in list_rosters() if r["id"] != roster_id for p in r["player_ids"]}


def snake_draft_picks(slot: int, teams: int, rounds: int) -> list[int]:
    """Overall pick numbers (1-based) for a draft slot in a snake draft."""
    if not 1 <= slot <= teams:
        raise RosterError("draft slot must be between 1 and the number of teams")
    picks = []
    for rnd in range(rounds):
        pos = slot if rnd % 2 == 0 else teams - slot + 1
        picks.append(rnd * teams + pos)
    return picks


def sample_roster(proj: Projection, slot: int = 5, teams: int = 12, size: int = 13) -> list[int]:
    """Players a manager at ``slot`` would get if everyone drafted by per-game 9-cat value
    (players currently ruled out are skipped by every drafter)."""
    healthy = proj.players[~proj.players["status"].astype(str).str.startswith(("Out", "Suspended"))]
    ordered = healthy.sort_values("pg_value", ascending=False).index.tolist()
    picks = snake_draft_picks(slot, teams, size)
    return [int(ordered[p - 1]) for p in picks if p - 1 < len(ordered)]
