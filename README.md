# CourtVision AI

AI-powered fantasy basketball analytics for **head-to-head 9-category leagues**
(PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO).

Python computes the statistics, projections and valuations. **Google Gemini** (via the official
`google-genai` SDK) explains those computed results in natural language. It is never the source of a number.

> **Status: all three phases are complete.** Every feature below is implemented, unit-tested (64 backend tests)
> and checked in the browser against real NBA data.
> - **Phase 1:** dashboard, ESPN data layer, player comparison, projection engine with a trained scikit-learn model,
>   Gemini integration, weekly projected rankings.
> - **Phase 2:** roster builder, team needs analyzer, multi-player trade analyzer, historical weekly rankings with backtests.
> - **Phase 3:** Monte Carlo matchup simulator, what-if lab, streaming optimizer, breakout detector, accuracy tracker,
>   and a tool-calling Gemini fantasy assistant.
>
> All seven Gemini features have been verified live through the local `agy` CLI (no API key needed; see below).

---

## Quick start

Prerequisites: **Python 3.11+** (developed on 3.14) and **Node 20+** (developed on 24).

```bash
cp .env.example .env          # optional: Gemini works through the local agy CLI without a key
```

```bash
./scripts/start_backend.sh    # creates backend/.venv on first run, serves http://127.0.0.1:8000
```

```bash
./scripts/start_frontend.sh   # installs node_modules on first run, serves http://localhost:5173
```

Or run both at once:

```bash
./scripts/start_all.sh
```

Open **http://localhost:5173**. It lands on **Today**: tonight's slate with tip times, which of your players play and
their projected lines, the best pickups playing that day, and injuries. There's a toggle for Tomorrow. This page uses no AI,
so it loads in under a second.

**First run:** the backend downloads about 2,500 real NBA box scores (2024-25, 2025-26 and the current 2026-27 season)
plus the schedule and injury report, then trains the projection model. This takes about 1–2 minutes and the UI shows
progress while it runs. Later starts use the SQLite cache and only refresh recent days (when the data is more than 3 hours old).

### Manual commands (equivalent to the scripts)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m data.ingest          # optional: pre-download data (full history + schedule + injuries)
.venv/bin/python -m services.ml_model    # optional: (re)train the model and print validation metrics
.venv/bin/uvicorn main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

### Tests

```bash
./scripts/test.sh             # backend pytest suite + frontend type-check & production build
```

```bash
cd backend && .venv/bin/python -m pytest -q
```

---

## Gemini integration

The backend reaches Gemini through one of two providers (`backend/services/gemini_service.py`):

| Provider | How | Config |
|---|---|---|
| **agy** (default when no key is set) | Runs the local Antigravity CLI: `agy -p … --model gemini-3.8-flash-low --mode plan --output-format json --json-schema …` in an empty scratch folder (`services/agy_client.py`). Uses the account `agy` is signed in with. | `GEMINI_PROVIDER=agy` or `auto`, `AGY_MODEL`, `AGY_TIMEOUT_S`, `AGY_BIN` |
| **sdk** | Official `google-genai` SDK. | `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_S` |

`GEMINI_PROVIDER=auto` uses the SDK when `GEMINI_API_KEY` is set, otherwise `agy` when it is installed.
The React app only talks to `/api/*`, so it never sees credentials. Through `agy`, each call takes about 8–40s,
because the CLI is an agent with its own overhead; responses are cached for 6 hours.

How each AI feature works:

1. Python builds a JSON payload of **computed** numbers (projections, z-scores, schedule, injuries).
2. Gemini gets strict grounding instructions ("use only these numbers…") and returns **structured JSON**
   (a Pydantic `response_schema` on the SDK; `--json-schema` on `agy`).
3. The response is **validated** against the Pydantic schema.
4. A **grounding check** pulls every number out of Gemini's text and confirms it appears in the payload
   (rounding and percent formats are allowed). Responses with more than 3 unsupported numbers are rejected.
5. Rate limits and transient errors (408/429/5xx/timeouts) are **retried with exponential backoff**.
   Auth and model errors are not retried.
6. Output is **concise by design**:
   - Every schema field has a word or item limit (e.g. headline ≤ 10 words, bullets ≤ 10–14 words, at most 3 bullets).
     Gemini sees these limits, and `compact()` in `gemini_service.py` enforces them.
   - The UI shows a headline, a one-line summary and chips first, with numbers in bold.
   - Longer reasoning sits behind "More details".
7. Responses are **cached** in SQLite for 6 hours, keyed by the payload hash, so identical requests don't use quota.
8. Any failure (no key, invalid key, quota, bad JSON, failed grounding) returns a **deterministic rule-based
   explanation** built from the same numbers. The UI labels it "Rule-based fallback" and explains why.

Gemini powers:

1. **Player comparison recommendation** (`POST /api/ai/compare`)
2. **Weekly rankings outlook** (`POST /api/ai/rankings`)
3. **Team report**: weaknesses, strengths, add/drop moves and strategy (`POST /api/ai/team`)
4. **Trade breakdown**: verdict, benefits, risks and a negotiation tip (`POST /api/ai/trade`)
5. **Matchup analysis**: categories to secure, swing or concede, plus actions (`POST /api/ai/matchup`)
6. **Breakout explanations** grounded only in the measured changes (`POST /api/ai/breakouts`)
7. **Fantasy assistant** with **function calling** (`POST /api/assistant`). Gemini gets declarations for 10 CourtVision tools:
   player report, compare, rankings, my team, trade, matchup simulation, streaming, breakouts, schedule and player search.
   The backend runs whichever tools Gemini calls on real data, and Gemini answers from the results.
   - With the SDK this uses native function calling. With `agy`, the backend runs an equivalent loop: each turn Gemini
     returns a schema-enforced JSON step (`call_tool` with arguments, or `final_answer`), and the backend runs the tool
     and feeds the result back, for up to 5 steps.
   - The UI shows which tools were called and how many numbers in the answer were checked against tool output.
   - Without a key, a rule-based assistant routes the question to the same tools by keyword and is labelled as such.

> **Live verification (via `agy`, Gemini 3.8 Flash):** all six AI panels returned real Gemini output.
> The grounding check found 0 unsupported numbers in each: comparison 49 numbers checked, rankings 30, team 37,
> trade 31, matchup 39, breakouts 64. Three assistant questions (compare, win 5-4, pickups) called the right tools,
> chaining matchup simulation with streaming for the 5-4 question, and every cited number matched tool output.
> The SDK path is covered by unit tests with a mocked client built from real `google-genai` types.

---

## Data

- **Source: ESPN's public NBA JSON API** (`site.api.espn.com`), which provides real box scores, schedules and injury reports.
  `stats.nba.com` and `cdn.nba.com` refuse requests from this kind of environment (HTTP 403 or timeouts), so they aren't used.
- Cached in **SQLite** (`backend/storage/courtvision.db`): teams, players, games (including the next 21 days of schedule),
  per-player box scores, injuries, the AI response cache and saved projections.
- Loaded at time of writing: 2024-25 (1,234 games), 2025-26 (1,235 games) and the 2026-27 season to date.
- **Offline demo mode:** if live data can't be fetched on the first run (`DATA_MODE=auto`), or if you set `DATA_MODE=demo`,
  the app generates a **fictional** league ("(Demo)" player names, "Demo Club" teams). A persistent banner reads
  *"OFFLINE DEMO DATA — fictional players"*. Demo data is stored in separate `*_demo` files, so it never overwrites real data.
- Data refreshes on startup when older than 3 hours, or on demand with "Refresh now" in the sidebar (`POST /api/admin/refresh`).

ESPN's API is undocumented and unofficial. Endpoints can change, and this project isn't affiliated with ESPN or the NBA.

---

## Projection engine

All features are **leakage-free**: each player-game row uses only games played strictly before it
(`backend/services/features.py`). Live projections reuse the same code path through a placeholder "next game" row.

**1. Explainable weighted baseline (per stat, per game)**

```
season_blend = (n_cur · avg_current_season + k · avg_prior_two_seasons) / (n_cur + k),
               where k = 10 · min(1, prior_games / 20)
baseline     = 0.5 · season_blend + 0.3 · last10 + 0.2 · last5
projection   = baseline × opponent_factor
```

The opponent factor is the stat a defense allows relative to league average. It is shrunk toward 1 with 10 games of
credibility, applied at half strength and clipped to ±15%.

**2. scikit-learn model.** `HistGradientBoostingRegressor` uses Poisson loss for counting stats and squared error for minutes.
There is one model each for MIN, PTS, REB, AST, STL, BLK, 3PM, TO, FGM, FGA, FTM and FTA. Features: the baseline components,
minutes, games played, home/away, rest days, and opponent factors.

**Chronological validation:**

| split | rows |
|---|---|
| train: 2024-25 plus 2025-26 before 2026-01-15 | 38,687 |
| validation: 2025-26 from 2026-01-15 on | 13,522 |
| untouched 2026-27 holdout | 604 (grows each refresh) |

**Selection rule:** for each stat, the ML model is used only if it beat the weighted baseline on validation. In the current
training that is true for MIN, FGA and TO. For the other stats the two are effectively tied, so the baseline stays in use.
On the 2026-27 holdout, ML is ahead for most stats. The **Model Lab** page shows every number.

Validation per-game MAE (lower is better):

| stat | season avg | weighted baseline | gradient boosting |
|---|---|---|---|
| MIN | 5.707 | 5.334 | **5.229** |
| PTS | 4.824 | **4.698** | 4.702 |
| REB | 1.939 | **1.905** | 1.909 |
| AST | 1.404 | **1.379** | 1.379 |
| TO  | 0.915 | 0.906 | **0.901** |

**3. Shooting percentages.** Projected makes = projected attempts × the player's season-blended FG%/FT%.
This beat predicting makes directly on validation: attempt-weighted FG% error was 12.7 vs 13.2 points.
Percentages are always computed as total makes / total attempts.

**4. Availability.** Availability comes from ESPN's injury report:

- Out (before the estimated return date): 0
- Out on or after the estimated return date: 0.6
- Day-to-day: 0.6 within 2 days, 0.85 later in the week

An injury report counts as stale if the player has played since it was filed.

**5. Uncertainty.** Per-game SD is the player's last-30-game SD, shrunk toward the model's validation residual SD.
Weekly variance adds availability risk. The UI shows **80% intervals**, including a Monte Carlo interval of each player's total 9-cat value.

On backend startup the data refreshes if older than 3 hours and the model retrains if older than 24 hours.

### 9-category valuation (rankings)

Rankings use standard **z-scores** of projected **weekly totals**, so games scheduled matter. The z-scores are relative to an
iteratively found **156-player pool** (12 teams × 13). FG% and FT% use **volume-weighted impact**
(`makes − pool_pct × attempts`), and turnovers are negated. Per-game z-scores are also shown, so you can compare skill
independent of schedule.

---

## Phase 2: rosters, team needs, trades, history

**Roster builder (My Team page).** Rosters are saved in SQLite. Create an empty roster and add players with search,
or click **Sample draft** to get the team you would have from pick N of a 12-team snake draft ranked by per-game value
(players currently ruled out are skipped). Players on your *other* saved rosters count as unavailable everywhere.

**Team needs analyzer.** There are two bases:

- **Projected week:** totals for the selected week, so games scheduled matter.
- **Per-game (rest of season):** schedule-independent talent.

For each category, the team's strength is the **sum of its players' z-scores**. Because z-scores are centred on the
156-player draftable pool, an average 12-team roster sums to about 0. A category is **strong/weak** beyond ±0.5·√(roster size).
The page also shows expected totals against an average team, shooting efficiency (volume-weighted FG%/FT% with attempts)
and turnovers.

**Pickup recommendations** score free agents with **need weights**:

- weak categories count up to 2×
- strong categories count down to 0.25× (diminishing returns)
- **punted** categories count 0

Each candidate is shown with the net gain over your weakest-fit player. Free agents exclude your other saved rosters and
the top 156 players, who are assumed rostered in a 12-team league.

**Trade analyzer.** Supports 1-for-1 through 3-for-3, including 2-for-1, 2-for-2 and 3-for-2. It reports:

- per-category team z-sum change, before and after totals
- the total 9-cat Δ and a need-weighted Δ, which drives the accept / decline / roughly-even verdict
- the value balance between the two sides

**Replacement logic** makes uneven trades comparable:

- Receiving fewer players than you give fills the open spots with the best available free agent.
- Receiving more forces you to drop your lowest need-weighted players.

The default basis is rest-of-season, and you can switch to the projected week.

**Historical rankings (Past Weeks page).** Covers every Monday–Sunday week from 2024-25 to now. The page shows:

- actual weekly totals, ranked with the same 9-cat z-score method
- category leaders, and rank change from the previous week
- each player's season trend (weekly value, best rank, least-squares slope)

**Projected vs actual** backtests each week with the explainable baseline, using only games played before that Monday,
times the games actually played. This deliberately avoids the trained model, whose final fit has seen those games.
It reports:

- Spearman rank correlation between projected and actual value (for example 0.81 for Mar 9–15, 2026)
- top-50 overlap
- per-category error, and which players beat or fell short of their projection

When a saved live projection exists for that week, it is scored too.

---

## Phase 3: simulation, streaming, breakouts, accuracy, assistant

**Matchup simulator (Matchup page).** Runs 10,000 Monte Carlo weeks by default (configurable up to 50,000). Each scheduled
player-game is drawn independently:

- **Plays or sits:** the player plays with probability equal to their injury-report availability.
- **Counting stats:** Normal(projected mean, per-game SD), rounded to whole numbers and floored at 0. A shared per-game
  "performance factor" (ρ = 0.35) makes good nights lift every stat.
- **Shooting:** shot attempts are drawn the same way, and makes are Binomial(attempts, projected %). FG% and FT% are then
  total makes ÷ total attempts for the week.

For "This week", **stats already played earlier in the week are banked** and added to every simulation.

The output covers:

- matchup win / tie / loss probability, with a Monte Carlo error bar
- expected categories won, and the distribution of categories won (0–9)
- per-category win probability and projected totals (80% ranges)
- strongest, weakest and swing categories
- Gemini analysis

**What-If Lab.** Toggle drops, add any players, or mark players out (injured). Both rosters are re-simulated with the same
seed, and the page shows before and after win probability plus per-category deltas. **Find moves** handles
"prioritize steals over points": it shortlists free agents with priority categories weighted 3×, then simulates each swap
and ranks them by the gain in the priority categories.

**Streaming optimizer.** For each day of the window it compares how many of your players are expected to play against your
active slots (default 10). A streamer's game only counts on days with an open slot, so light NBA days rank higher.

- **Stream value:** the need-weighted team z-sum gain from the usable games, on the same scale as the team analyzer.
- **Candidate pool:** automatic free agents, or your own **waiver list**, saved per roster in the browser.
- **Limitation:** positional eligibility is not modelled.

**Breakout detector.** Compares each player's last 5 games with the 25 before them. The breakout score is
0.30·minutes + 0.20·usage + 0.15·shots + 0.25·production + 0.10·defense:

- **Minutes, shots:** change in minutes and FGA per game.
- **Usage:** change in (FGA + 0.44·FTA + TOV) per 36 minutes.
- **Production:** change in per-game 9-cat value.
- **Defense:** change in (STL + BLK) per 36 minutes.

Each change is standardized across the league before weighting. Windows that span the offseason are flagged, and an
"as of" date lets you run the detector at any point in the past.

**Accuracy tracker.** Every completed week since 2024-25 (49 weeks at the time of writing) is re-projected using only
earlier games and scored against actual weekly totals. It compares CourtVision's weighted baseline with a season-average
baseline:

- Rank correlation of 9-cat value: 0.775 vs 0.766
- Error is lower for most categories, e.g. PTS 8.55 vs 8.79 per player-week.

Live pre-week projections, which include the ML model and the injury and opponent adjustments, are saved automatically
and scored once their week finishes.

---

## Gemini forecast: a second projection model

Alongside the statistical model, CourtVision can ask **Gemini to forecast players itself**, through `agy`, then measure
which model predicts better.

- **Input:** for each player, Gemini gets only real data from the cached box scores:
  - the last 10 games (minutes and every 9-cat stat)
  - current- and prior-season averages
  - the scheduled games in the window (opponent, home/away, rest)
  - the injury-report status
- **Output:** per-game forecasts (minutes plus the 11 raw stats), expected games played, a confidence level and a one-line rationale.
- **Validation:** Python validates every number. Negatives and absurd values are clamped, makes are capped at attempts,
  and expected games are capped at scheduled games. Each correction is listed with the forecast.
- **Valuation:** forecasts become weekly totals and are valued with the **same 9-cat z-score pool** as the statistical
  model, so the two are directly comparable.
- **Gemini Forecast page:** "Generate Gemini forecast" forecasts the top N statistical players plus everyone on a saved
  roster, in batches of 20 (a few minutes in total). The page shows:
  - each player side by side (every category, value, rank, expected games, minutes)
  - the agreement between the models and the biggest disagreements
  - Gemini's reasoning per player
- **Compare page:** a "Gemini forecast / game" row appears once a forecast exists.

**Scoring both models (Accuracy Tracker):**
- **Forward test (clean):** forecasts generated for *next* week are saved to `projection_log` (method `gemini`) next to
  the statistical projections. When the week ends, both are scored on the same players.
- **Backtest:** "Run Gemini backtest" forecasts 40 players in each of 4 past weeks, using only games before each week.
  It scores Gemini against the statistical model and the season average on identical players. Players are picked by the
  statistical model's pre-week value, not by results.
  Caveat: Gemini may have seen those seasons during training, so its backtest scores may be optimistic.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness + bootstrap status |
| GET | `/api/today?day=auto\|today\|tomorrow\|YYYY-MM-DD&roster_id=` | one-day slate, your players, pickups, injuries (no Gemini) |
| GET | `/api/meta` | data source/freshness, seasons, Gemini + model status, week windows |
| POST | `/api/admin/refresh` | refresh recent results, schedule and injuries |
| GET | `/api/players/search?q=` | player search (accent-insensitive) |
| GET | `/api/players/{id}?week=` | profile, season/L5/L10 averages, game log, projection breakdown |
| GET | `/api/players/default/pair` | default comparison (Jokić vs Wembanyama) |
| GET | `/api/compare?a=&b=&week=` | full head-to-head comparison |
| POST | `/api/ai/compare` | Gemini recommendation for a comparison |
| GET | `/api/rankings/weekly?week=&sort=&order=&position=&team=&search=&min_games=` | projected leaderboard + category leaders |
| POST | `/api/ai/rankings?week=` | Gemini outlook for the week |
| GET | `/api/schedule/week?week=` | games per day / per team |
| GET | `/api/model` | training info and validation metrics |
| GET/POST | `/api/rosters` | list / create rosters (`{name, kind, player_ids}`) |
| POST | `/api/rosters/sample` | create a snake-draft sample roster (`{name, draft_slot, teams, size}`) |
| GET/PUT/DELETE | `/api/rosters/{id}` | read / update (name, players) / delete a roster |
| POST | `/api/team/analyze` | team needs analysis (`{player_ids, roster_id?, week, basis, punt, assume_rostered}`) |
| POST | `/api/ai/team` | Gemini team report (same body) |
| POST | `/api/trade/analyze` | trade evaluation (`{roster_player_ids, give, get, roster_id?, week, basis, punt}`) |
| POST | `/api/ai/trade` | Gemini trade breakdown (same body) |
| GET | `/api/history/weeks` | available historical weeks |
| GET | `/api/history/week?start=&sort=&position=&search=` | actual weekly rankings + category leaders |
| GET | `/api/history/player/{id}?season=` | a player's weekly value trend |
| GET | `/api/history/backtest?start=` | projected-vs-actual backtest for a week |
| POST | `/api/matchup/simulate` | Monte Carlo matchup (`{roster_player_ids, opponent_player_ids, week, sims, seed}`) |
| POST | `/api/ai/matchup` | Gemini matchup analysis (same body) |
| POST | `/api/whatif` | re-simulate after changes (`{..., add, drop, out, availability}`) |
| POST | `/api/whatif/suggest` | best swaps for priority categories (`{..., priority, punt}`) |
| POST | `/api/streaming` | streaming candidates (`{roster_player_ids, week, slots, available_ids?, punt}`) |
| GET | `/api/breakouts?as_of=&limit=&min_minutes=` | breakout candidates |
| POST | `/api/ai/breakouts?as_of=` | Gemini breakout explanations |
| GET | `/api/accuracy` | weekly projection accuracy (backtests + saved live projections) |
| POST | `/api/assistant` | Gemini tool-calling assistant (`{message, history, roster_id, opponent_roster_id, week}`) |
| GET | `/api/forecast?week=` | statistical vs Gemini forecast, side by side |
| GET | `/api/forecast/players?ids=&week=` | Gemini forecast rows for specific players |
| POST | `/api/forecast/run` | start a Gemini forecast job (`{week, top_n}`) |
| POST | `/api/forecast/backtest` | start a Gemini backtest job (`{weeks?, per_week}`) |
| GET | `/api/forecast/status` | progress of both forecast jobs |

`week` is `next` (next Monday–Sunday, the default), `current` (the rest of this week), or any ISO date (that date's Monday–Sunday week).
Interactive docs: http://127.0.0.1:8000/docs

---

## Project structure

```
backend/
  main.py                    FastAPI app (startup bootstrap in a background thread)
  core/        config.py (env), db.py (SQLite schema), categories.py (9-cat math)
  data/        espn_client.py, ingest.py, repository.py, bootstrap.py, demo_data.py
  services/    features.py, ml_model.py, projections.py, valuation.py, schedule.py,
               players.py, comparison.py, rankings.py, gemini_service.py,
               rosters.py, team.py, trade.py, history.py           (Phase 2)
               matchup.py, whatif.py, streaming.py, breakouts.py,
               accuracy.py, assistant.py                          (Phase 3)
               agy_client.py, gemini_forecast.py                  (Gemini via agy + forecast model)
               today.py                                           (Today / Tomorrow landing page)
  routers/     api.py (Phase 1), phase2.py, phase3.py, deps.py
  tests/       categories/valuation, features (leakage), projections, Gemini service, Phase 2, Phase 3
frontend/
  src/pages/       Today (landing), Dashboard (Week Overview), About, Compare, Rankings, Breakouts, History, Team, Trade, Streaming,
                   Matchup, WhatIf, Assistant, GeminiForecast, ModelLab, Accuracy
  src/components/  Layout, PlayerSearch, AIPanel, RosterManager, Category charts, ui primitives
  src/lib/         api client, types, hooks, formatting
scripts/           start_backend.sh, start_frontend.sh, start_all.sh, test.sh
```

## Troubleshooting

- **"Gemini not configured"**: make sure `agy` is installed and signed in (`agy models` should list Gemini models),
  or set `GEMINI_API_KEY` in `.env`. Then restart the backend.
- **AI panels are slow**: through `agy`, each call takes about 8–40s. Repeat requests for the same data are cached for 6 hours.
- **Model 404**: set `GEMINI_MODEL` to a model your key can access (see https://ai.google.dev/gemini-api/docs/models).
- **Stuck on "Downloading NBA box scores"**: check your network connection. With `DATA_MODE=auto`, a failed first download switches to the labelled demo league.
- **Start fresh**: stop the backend, delete `backend/storage/`, and start it again.
