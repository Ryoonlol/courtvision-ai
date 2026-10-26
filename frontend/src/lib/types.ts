export type CatKey = 'pts' | 'reb' | 'ast' | 'stl' | 'blk' | 'fg3m' | 'fg_pct' | 'ft_pct' | 'tov'
export type WeekKey = 'current' | 'next'

export interface Category {
  key: CatKey
  label: string
  name: string
  higher_is_better: boolean
  is_pct: boolean
}

export interface WindowInfo {
  key: string
  start: string
  end: string
  label: string
  week_start: string
}

export interface Meta {
  app: string
  bootstrap: { status: string; message: string; updated_at: string | null }
  data: {
    source: string | null
    is_demo: boolean
    source_label: string
    last_refresh_utc: string | null
    current_season: string
    seasons: { season: string; player_games: number; games: number; last_date: string }[]
    injuries: { count: number; fetched_at: string | null }
  }
  today: string
  windows: Record<WeekKey, WindowInfo>
  gemini: { configured: boolean; available: boolean; provider: 'sdk' | 'agy' | null; model: string; label: string; sdk: string; last_error: string | null }
  model: {
    trained: boolean
    trained_at?: string
    algorithm?: string
    split_date?: string
    data_through?: string
    rows?: Record<string, number>
    use_ml?: Record<string, boolean>
    pct_method?: Record<string, string>
  }
  categories: Category[]
}

export interface PlayerHit {
  id: number
  name: string
  team_abbr: string | null
  position: string | null
  headshot: string | null
  rank: number | null
}

export interface SeasonLine {
  games: number
  min: number
  pts: number
  reb: number
  ast: number
  stl: number
  blk: number
  fg3m: number
  tov: number
  fgm: number
  fga: number
  ftm: number
  fta: number
  fg_pct: number | null
  ft_pct: number | null
  first_date: string
  last_date: string
}

export interface GameLogRow {
  date: string
  season: string
  opponent: string
  home: boolean
  min: number
  pts: number
  reb: number
  ast: number
  stl: number
  blk: number
  fg3m: number
  tov: number
  fgm: number
  fga: number
  ftm: number
  fta: number
}

export interface Profile {
  id: number
  name: string
  position: string | null
  team_abbr: string | null
  team_name: string | null
  team_logo: string | null
  headshot: string | null
  injury: { status: string; fantasy_status: string; return_date: string | null; short_comment: string | null } | null
  current_season: string
  seasons: Record<string, SeasonLine | null>
  last5: SeasonLine | null
  last10: SeasonLine | null
  game_log: GameLogRow[]
}

/** One player's projection row (weekly totals + z-scores). */
export type ProjectionRow = Record<string, number | string | null> & {
  player_id: number
  name: string
  team_abbr: string
  rank: number
  games: number
  exp_games: number
  value: number
  value_lo: number
  value_hi: number
  pg_value: number
  status: string
}

export interface UpcomingGame {
  date: string
  weekday: string
  opponent: string
  opponent_logo: string | null
  home: boolean
  rest_days: number
  availability: number
  availability_note: string
  opp_pts_factor: number
  projection: Record<string, number>
}

export interface Explain {
  games_this_season?: number
  prior_season_games?: number
  components?: Record<string, {
    season_blend: number | null
    current_season_avg: number | null
    prior_two_season_avg: number | null
    last10: number | null
    last5: number | null
    weighted_baseline: number | null
    method: string
  }>
  games: UpcomingGame[]
}

export interface CompareCategory {
  key: CatKey
  label: string
  name: string
  higher_is_better: boolean
  weekly_a: number | null
  weekly_b: number | null
  weekly_winner: 'a' | 'b' | 'tie'
  z_a: number | null
  z_b: number | null
  per_game_winner: 'a' | 'b' | 'tie'
  weekly_z_a: number | null
  weekly_z_b: number | null
}

export interface Comparison {
  window: WindowInfo
  methods: Record<string, string>
  players: { profile: Profile; projection: ProjectionRow | null; explain: Explain }[]
  categories: CompareCategory[]
  summary: { weekly_wins_a: number; weekly_wins_b: number; per_game_wins_a: number; per_game_wins_b: number }
}

export interface AIResponse<T> {
  source: 'gemini' | 'fallback'
  model: string | null
  data: T
  cached: boolean
  notice: string | null
  grounding: { numbers_checked: number; ungrounded: string[]; passed: boolean } | null
}

export interface ComparisonInsight {
  headline: string
  overall_pick: string
  summary: string
  roster_fits: { need: string; pick: string; reason: string }[]
  key_edges: string[]
  risks: string[]
  confidence: 'low' | 'medium' | 'high'
}

export interface RankingsInsight {
  headline: string
  overview: string
  schedule_notes: string[]
  sleepers: string[]
  category_specialists: string[]
}

export type RankingRow = ProjectionRow & { strengths: CatKey[]; weaknesses: CatKey[]; headshot: string | null; team_logo: string | null; position: string | null }

export interface Leader {
  player_id: number
  name: string
  team_abbr: string
  value: number
  headshot: string | null
}

export interface Rankings {
  window: WindowInfo
  methods: Record<string, string>
  valuation: { method: string; pool_size: number; pool_fg_pct: number; pool_ft_pct: number }
  total_players: number
  rows: RankingRow[]
  leaders: Record<CatKey, Leader[]>
}

export interface ScheduleSummary {
  window: WindowInfo
  games_by_day: { date: string; weekday: string; games: number }[]
  games_by_team: { abbr: string; logo: string | null; games: number }[]
  total_games: number
}

export interface MetricSplit {
  rows: number
  mae_ml: number
  mae_baseline: number
  mae_season_avg: number
  mean_actual: number
  mae_chosen?: number
}

export interface ModelInfo {
  trained: boolean
  trained_at?: string
  algorithm?: string
  split_date?: string
  data_through?: string
  rows?: Record<string, number>
  use_ml?: Record<string, boolean>
  pct_method?: Record<string, string>
  metrics?: Record<string, { method?: string; validation: MetricSplit & Record<string, number>; test?: MetricSplit }>
  baseline: { description: string }
  shooting: string
  uncertainty: string
}

// ---------------------------------------------------------------- Phase 2
export type Basis = 'week' | 'season'

export interface Roster {
  id: number
  name: string
  kind: 'mine' | 'opponent' | 'other'
  created_at: string
  updated_at: string
  player_ids: number[]
}

export interface TeamCategory {
  key: CatKey
  label: string
  name: string
  higher_is_better: boolean
  value: number | null
  average_team: number
  z: number
  status: 'strong' | 'average' | 'weak'
}

export interface TeamProfile {
  basis: Basis
  players: number
  missing_player_ids: number[]
  totals: Record<string, number>
  categories: TeamCategory[]
  strongest: CatKey[]
  weakest: CatKey[]
  total_value: number
  games: number
  status_threshold: number
}

export interface TeamPlayer {
  player_id: number
  name: string
  team_abbr: string
  position: string | null
  headshot: string | null
  status: string
  games: number
  value: number
  fit_score: number
  z: Record<CatKey, number>
  stats: Record<string, number>
}

export interface Recommendation {
  player_id: number
  name: string
  team_abbr: string
  position: string | null
  headshot: string | null
  status: string
  games: number
  fit_score: number
  net_gain: number
  drop_player_id: number
  drop_name: string
  helps: CatKey[]
  category_deltas: Record<CatKey, number>
}

export interface TeamAnalysis {
  window: WindowInfo
  profile: TeamProfile
  weights: Record<CatKey, number>
  punt: CatKey[]
  roster: TeamPlayer[]
  recommendations: Recommendation[]
  assume_rostered: number
}

export interface TeamInsight {
  headline: string
  assessment: string
  strengths: string[]
  weaknesses: string[]
  moves: { action: string; reason: string }[]
  strategy: string
}

export interface TradePlayer {
  player_id: number
  name: string
  team_abbr: string
  position: string | null
  headshot: string | null
  status: string
  games: number
  value: number
  z: Record<CatKey, number>
}

export interface TradeCategory {
  key: CatKey
  label: string
  higher_is_better: boolean
  before: number | null
  after: number | null
  z_before: number
  z_after: number
  z_delta: number
  weight: number
  punted: boolean
}

export interface TradeResult {
  window: WindowInfo
  basis: Basis
  format: string
  give: TradePlayer[]
  get: TradePlayer[]
  adjustments: { type: 'add_replacement' | 'drop'; player_id: number; name: string; reason: string }[]
  roster_before: number[]
  roster_after: number[]
  categories: TradeCategory[]
  improved: CatKey[]
  worsened: CatKey[]
  value_delta: number
  need_weighted_delta: number
  give_value: number
  get_value: number
  value_balance: number
  verdict: 'accept' | 'decline' | 'fair'
  punt: CatKey[]
  team_value_before: number
  team_value_after: number
}

export interface TradeInsight {
  headline: string
  verdict: 'accept' | 'decline' | 'fair' | 'depends'
  summary: string
  benefits: string[]
  risks: string[]
  negotiation_tip: string
}

export interface HistoryWeek {
  week_start: string
  week_end: string
  season: string
  label: string
  players: number
  in_progress: boolean
  has_saved_projection: boolean
}

export type HistoryRow = {
  player_id: number
  rank: number
  prev_rank: number | null
  name: string
  team_abbr: string
  team_logo: string | null
  position: string | null
  headshot: string | null
  games: number
  min: number
  value: number
  fgm: number
  fga: number
  ftm: number
  fta: number
} & Record<string, number | string | null>

export interface HistoryWeekResult {
  week_start: string
  week_end: string
  label: string
  in_progress: boolean
  players: number
  pool_fg_pct: number
  pool_ft_pct: number
  rows: HistoryRow[]
  leaders: Record<CatKey, Leader[]>
}

export interface PlayerTrend {
  player_id: number
  name: string | null
  season: string
  seasons_available: string[]
  weeks: ({ week_start: string; games: number; value: number; rank: number } & Record<string, number | string | null>)[]
  avg_value: number | null
  best_rank: number | null
  trend_per_week: number | null
}

export interface BacktestPlayer {
  player_id: number
  name: string
  headshot: string | null
  projected_value: number
  actual_value: number
  games: number
}

export interface Backtest {
  week_start: string
  method: string
  players: number
  category_mae: Record<CatKey, { mae: number; mean_actual?: number; unit: string }>
  value_rank_spearman: number
  top50_overlap: number
  overperformers: BacktestPlayer[]
  underperformers: BacktestPlayer[]
  scatter: { player_id: number; name: string; projected: number; actual: number }[]
  saved_projection: null | { players: number; created_at: string; weekly_mae?: Record<string, number>; note?: string }
}

// ---------------------------------------------------------------- Phase 3
export interface SimCategory {
  key: CatKey
  label: string
  higher_is_better: boolean
  p_win: number
  p_tie: number
  p_loss: number
  mean_a: number | null
  mean_b: number | null
  p10_a: number | null
  p90_a: number | null
  p10_b: number | null
  p90_b: number | null
  se: number
}

export interface SimTeam {
  players: { player_id: number; name: string; team_abbr: string; headshot: string | null; status: string; games: number; expected_games: number }[]
  games: number
  expected_games: number
  missing_player_ids: number[]
  banked?: Record<string, number>
}

export interface MatchupResult {
  sims: number
  p_win: number
  p_tie: number
  p_loss: number
  p_win_se: number
  expected_cats_won: number
  expected_cats_lost: number
  cats_won_distribution: number[]
  p_at_least_5: number
  categories: SimCategory[]
  strongest: CatKey[]
  weakest: CatKey[]
  swing: CatKey[]
  window: WindowInfo
  team_a: SimTeam
  team_b: SimTeam
}

export interface MatchupInsight {
  headline: string
  outlook: string
  secure: string[]
  swing: string[]
  concede: string[]
  actions: string[]
}

export interface ScenarioBrief {
  p_win: number
  p_tie: number
  p_loss: number
  expected_cats_won: number
  p_at_least_5: number
  p_win_se: number
  cats_won_distribution: number[]
  games: number
  expected_games: number
}

export interface WhatIfResult {
  window: WindowInfo
  changes: { add: string[]; drop: string[]; out: string[]; availability: Record<string, number> }
  roster_after: number[]
  before: ScenarioBrief
  after: ScenarioBrief
  delta_p_win: number
  delta_expected_cats: number
  categories: { key: CatKey; label: string; p_before: number; p_after: number; delta: number; mean_before: number | null; mean_after: number | null }[]
  categories_after: SimCategory[]
}

export interface MoveSuggestion {
  player_id: number
  name: string
  team_abbr: string
  headshot: string | null
  games: number
  drop_player_id: number
  drop_name: string
  priority_gain: number
  delta_p_win: number
  delta_expected_cats: number
  category_deltas: Record<CatKey, number>
}

export interface SuggestResult {
  priority: CatKey[]
  base_p_win: number
  base_priority_p: Record<CatKey, number>
  sims_per_candidate: number
  moves: MoveSuggestion[]
}

export interface StreamDay {
  date: string
  weekday: string
  league_games: number
  my_players: number
  open_slots: number
  usable: number
}

export interface StreamCandidate {
  player_id: number
  name: string
  team_abbr: string
  position: string | null
  headshot: string | null
  status: string
  games: number
  usable_games: number
  proj_min: number
  stream_value: number
  per_game_value: number
  helps: CatKey[]
  category_gain: Record<CatKey, number>
  projected_totals: Record<string, number>
  days: { date: string; weekday: string; usable: number; availability: number }[]
}

export interface StreamResult {
  window: WindowInfo
  slots: number
  mode: 'auto' | 'custom'
  pool_size: number
  weights: Record<CatKey, number>
  days: StreamDay[]
  drop_candidate: { player_id: number; name: string; games: number } | null
  candidates: StreamCandidate[]
}

export type BreakoutComponent = 'minutes' | 'usage' | 'shots' | 'production' | 'defense'

export interface BreakoutCandidate {
  player_id: number
  name: string
  team_abbr: string | null
  team_logo: string | null
  position: string | null
  headshot: string | null
  score: number
  components: Record<BreakoutComponent, number>
  deltas: Record<BreakoutComponent, number>
  recent: Record<string, number>
  baseline: Record<string, number>
  signals: string[]
  last_game: string
  spans_seasons: boolean
  recent_window: string
  baseline_season: string
}

export interface BreakoutResult {
  as_of: string
  eligible: number
  weights: Record<BreakoutComponent, number>
  recent_games: number
  baseline_games: number
  candidates: BreakoutCandidate[]
}

export interface BreakoutInsight {
  headline: string
  overview: string
  players: { player: string; why: string; sustainability: string }[]
  caution: string
}

export type AccuracyMetrics = Record<'spearman' | 'top50_overlap' | CatKey, number | null>

export interface AccuracyResult {
  method_notes: { weighted: string; naive: string; scope: string }
  weeks: { week_start: string; season: string; players: number; weighted: AccuracyMetrics; naive: AccuracyMetrics }[]
  overall: { weighted: AccuracyMetrics; naive: AccuracyMetrics }
  by_season: Record<string, { weighted: AccuracyMetrics; naive: AccuracyMetrics; weeks: number }>
  saved_projections: SavedProjectionWeek[]
  gemini_backtest: GeminiBacktest
  model_validation: { trained?: boolean; split_date?: string }
}

export interface SavedProjectionWeek {
  week_start: string
  status: string
  common_players?: number
  methods: Record<string, { players_projected: number; saved_at: string; mae?: Record<string, number>; spearman_value?: number }>
}

export type BacktestMethodMetrics = Record<'spearman' | 'top50_overlap' | CatKey, number | null>

export interface GeminiBacktest {
  weeks: { week_start: string; players: number; model: string; gemini: BacktestMethodMetrics; weighted: BacktestMethodMetrics; naive: BacktestMethodMetrics }[]
  overall: { gemini: BacktestMethodMetrics; weighted: BacktestMethodMetrics; naive: BacktestMethodMetrics } | null
  caveat?: string
}

export interface ForecastJob {
  kind: 'live' | 'backtest'
  status: 'running' | 'done' | 'error'
  done: number
  total: number
  errors: string[]
  started_at: string
  finished_at: string | null
  model: string
  players?: number
  weeks?: string[]
  window?: WindowInfo
}

export interface ForecastRow {
  player_id: number
  name: string
  team_abbr: string
  headshot: string | null
  position: string | null
  status: string
  games: number
  stat_expected_games: number
  gemini_expected_games: number
  stat_value: number
  gemini_value: number
  stat_rank: number
  gemini_rank: number
  stat_min: number | null
  gemini_min: number
  categories: Record<CatKey, { stat: number | null; gemini: number | null }>
  confidence: 'low' | 'medium' | 'high'
  rationale: string
  fixes: string[]
}

export interface ForecastView {
  window: WindowInfo
  job: ForecastJob | null
  players: number
  rows: ForecastRow[]
  model?: string
  created_at?: string
  agreement_spearman?: number | null
  mean_abs_value_gap?: number
}

export type ChatReply = Omit<ChatMessage, 'role' | 'content'> & { answer: string }

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  source?: 'gemini' | 'fallback'
  model?: string | null
  tool_calls?: { tool: string; args: Record<string, unknown>; ok: boolean; error: string | null }[]
  grounding?: { numbers_checked: number; ungrounded: string[]; passed: boolean } | null
  notice?: string | null
}

// ---------------------------------------------------------------- Today
export interface TodayGame {
  game_id: number
  tip: string | null
  status: 'scheduled' | 'live' | 'final'
  away: string
  home: string
  away_logo: string | null
  home_logo: string | null
  away_score: number | null
  home_score: number | null
}

export interface TodayLine {
  player_id: number
  name: string
  team: string
  position: string | null
  headshot: string | null
  status: string
  value: number
  opponent?: string
  home?: boolean
  play_chance?: number
  min?: number
  pts?: number
  reb?: number
  ast?: number
  stl?: number
  blk?: number
  fg3m?: number
  tov?: number
  fg_pct?: number | null
  ft_pct?: number | null
  helps?: string[]
}

export interface TodayView {
  day: 'today' | 'tomorrow' | 'date'
  date: string
  label: string
  games: TodayGame[]
  games_left: number
  my_team: null | {
    roster_id: number
    name: string
    size: number
    playing: TodayLine[]
    already_played: ({ player_id: number; name: string; headshot: string | null } & Record<'pts' | 'reb' | 'ast' | 'stl' | 'blk' | 'fg3m' | 'tov' | 'min', number>)[]
    not_playing: { player_id: number; name: string; headshot: string | null }[]
  }
  top: TodayLine[]
  pickups: TodayLine[]
  injuries: { player_id: number; name: string; team: string; mine: boolean; status: string; return_date: string | null; note: string }[]
  tomorrow: string
}
