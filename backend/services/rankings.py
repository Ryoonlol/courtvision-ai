"""Weekly projected leaderboard built on the 9-cat z-score valuation."""
from __future__ import annotations

from pydantic import BaseModel, Field

from core.categories import CATEGORIES
from services.gemini_service import AIResponse, brief, gemini
from services.projections import Projection, clean_record

ROW_FIELDS = ["rank", "name", "team_abbr", "team_logo", "position", "headshot", "status", "games", "exp_games",
              "min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fgm", "fga", "ftm", "fta",
              "fg_pct", "ft_pct", "value", "value_lo", "value_hi", "pg_value",
              *[f"z_{c.key}" for c in CATEGORIES], *[f"sd_{c.key}" for c in CATEGORIES]]
SORTABLE = {"value", "pg_value", "games", *[c.key for c in CATEGORIES], *[f"z_{c.key}" for c in CATEGORIES]}


def weekly(proj: Projection, sort: str = "value", position: str | None = None, team: str | None = None,
           search: str | None = None, min_games: int = 1, limit: int = 150, descending: bool | None = None) -> dict:
    df = proj.players
    df = df[df["games"] >= min_games]
    if position:
        df = df[df["position"].fillna("").str.upper().str.contains(position.upper()[0])]
    if team:
        df = df[df["team_abbr"] == team.upper()]
    if search:
        df = df[df["name"].str.lower().str.contains(search.lower(), regex=False)]
    sort = sort if sort in SORTABLE else "value"
    if descending is None:
        descending = not (sort == "tov")
    df = df.sort_values(sort, ascending=not descending, na_position="last").head(limit)
    rows = []
    for pid, r in df.iterrows():
        rec = clean_record({k: r[k] for k in ROW_FIELDS} | {"player_id": int(pid)})
        zs = {c.key: r[f"z_{c.key}"] for c in CATEGORIES}
        top = sorted(zs.items(), key=lambda kv: kv[1], reverse=True)
        rec["strengths"] = [k for k, v in top[:3] if v > 0.5]
        rec["weaknesses"] = [k for k, v in top[::-1][:2] if v < -0.5]
        rows.append(rec)
    return {
        "window": proj.window.as_dict(),
        "methods": proj.methods,
        "valuation": {
            "method": "9-category z-scores of projected weekly totals; FG%/FT% weighted by attempts",
            "pool_size": proj.params.pool_size,
            "pool_fg_pct": round(proj.params.pool_pct["fg_pct"], 4),
            "pool_ft_pct": round(proj.params.pool_pct["ft_pct"], 4),
        },
        "total_players": int(len(proj.players)),
        "rows": rows,
        "leaders": category_leaders(proj),
    }


def category_leaders(proj: Projection, n: int = 5) -> dict:
    df = proj.players[proj.players["games"] > 0]
    out = {}
    for c in CATEGORIES:
        # percentage leaders need meaningful volume
        sub = df[df[c.attempts] >= df[c.attempts].quantile(0.6)] if c.is_pct else df
        top = sub.sort_values(c.key, ascending=not c.higher_is_better).head(n)
        out[c.key] = [{"player_id": int(pid), "name": r["name"], "team_abbr": r["team_abbr"],
                       "value": round(float(r[c.key]), 3 if c.is_pct else 1), "headshot": r["headshot"]}
                      for pid, r in top.iterrows()]
    return out


# --------------------------------------------------------------------------- Gemini
class RankingsInsight(BaseModel):
    headline: str = brief("This week's story", words=10)
    overview: str = brief("Who leads and why", words=30)
    schedule_notes: list[str] = brief("Schedule effects, e.g. 'Wed: 12 games, Thu: 3'", words=12, items=2)
    sleepers: list[str] = brief("Players ranked outside the top 25 worth a look, with one number", words=12, items=3)
    category_specialists: list[str] = brief("Category specialists, e.g. 'STL: Dyson Daniels 12.6'", words=8, items=3)

RANKINGS_INSTRUCTIONS = """Summarize this week's projected 9-category rankings for fantasy managers.
Explain what drives the top of the board (games scheduled vs per-game quality), point out schedule
effects, sleepers outside the top 25, and category specialists. Only use the provided data."""


def ai_payload(proj: Projection, schedule: dict) -> dict:
    df = proj.players[proj.players["games"] > 0]
    def brief(r):
        return {"name": r["name"], "team": r["team_abbr"], "games": int(r["games"]),
                "value": round(float(r["value"]), 2), "per_game_value": round(float(r["pg_value"]), 2),
                "status": r["status"],
                "top_categories": [c.label for c in sorted(CATEGORIES, key=lambda c: -r[f"z_{c.key}"])[:3]]}
    top = [brief(r) | {"rank": int(r["rank"])} for _, r in df.head(15).iterrows()]
    # sleepers: strong per-game value with high weekly rank number
    s = df[(df["rank"] > 25) & (df["rank"] <= 120)].sort_values("pg_value", ascending=False).head(6)
    sleepers = [brief(r) | {"rank": int(r["rank"])} for _, r in s.iterrows()]
    leaders = {c.label: [(x["name"], x["value"]) for x in v[:3]]
               for c, v in zip(CATEGORIES, category_leaders(proj, 3).values())}
    return {"week": proj.window.label, "top15": top, "sleeper_candidates": sleepers,
            "category_leaders": leaders,
            "games_by_day": schedule["games_by_day"],
            "teams_with_most_games": schedule["games_by_team"][:6],
            "teams_with_fewest_games": schedule["games_by_team"][-4:]}


def fallback_insight(payload: dict) -> RankingsInsight:
    top = payload["top15"]
    lead = top[0] if top else None
    days = payload["games_by_day"]
    notes = []
    if days:
        light = min(days, key=lambda d: d["games"])
        heavy = max(days, key=lambda d: d["games"])
        notes.append(f"Busiest day: {heavy['weekday']} ({heavy['games']} games); lightest: {light['weekday']} ({light['games']} games).")
    most = payload["teams_with_most_games"]
    if most:
        notes.append("Most games: " + ", ".join(f"{t['abbr']} ({t['games']})" for t in most[:4]) + ".")
    four = sum(1 for t in top if t["games"] >= 4)
    overview = (f"{lead['name']} leads with a projected fantasy value of {lead['value']:.1f} over {lead['games']} games. "
                f"{four} of the top {len(top)} have 4+ games, so volume is a major driver this week." if lead else
                "No projections available for this window.")
    sleepers = [f"{s['name']} ({s['team']}): rank {s['rank']} but per-game value {s['per_game_value']:.1f} "
                f"with only {s['games']} games." for s in payload["sleeper_candidates"][:3]]
    specs = [f"{cat}: {names[0][0]} ({names[0][1]})" for cat, names in list(payload["category_leaders"].items())[:3]
             if names]
    return RankingsInsight(headline=f"{lead['name']} tops the board" if lead else "No games scheduled",
                           overview=overview, schedule_notes=notes, sleepers=sleepers or ["No clear sleepers."],
                           category_specialists=specs)


def ai_insight(proj: Projection, schedule: dict) -> AIResponse:
    payload = ai_payload(proj, schedule)
    return gemini.generate("rankings", RANKINGS_INSTRUCTIONS, payload, RankingsInsight,
                           lambda: fallback_insight(payload))

