import type {
  AccuracyResult, AIResponse, Backtest, Basis, BreakoutInsight, BreakoutResult, CatKey, ChatReply, Comparison,
  ComparisonInsight, ForecastJob, ForecastView, HistoryWeek, HistoryWeekResult, MatchupInsight, MatchupResult, Meta, ModelInfo, PlayerHit,
  PlayerTrend, Rankings, RankingsInsight, Roster, ScheduleSummary, StreamResult, SuggestResult, TeamAnalysis,
  TeamInsight, TodayView, TradeInsight, TradeResult, WeekKey, WhatIfResult,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  } catch {
    throw new ApiError(0, 'Cannot reach the CourtVision API. Is the backend running on port 8000?')
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      const d = body.detail
      msg = typeof d === 'string' ? d : d?.message ?? msg
    } catch { /* non-JSON error */ }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

const qs = (params: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)]),
  ).toString()

export const api = {
  meta: () => request<Meta>('/api/meta'),
  today: (day: string, roster_id?: number | null) => request<TodayView>(`/api/today?${qs({ day, roster_id })}`),
  refresh: () => request<{ started: boolean }>('/api/admin/refresh', { method: 'POST' }),
  search: (q: string) => request<PlayerHit[]>(`/api/players/search?${qs({ q, limit: 12 })}`),
  defaultPair: () => request<{ a: number; b: number }>('/api/players/default/pair'),
  compare: (a: number, b: number, week: WeekKey) => request<Comparison>(`/api/compare?${qs({ a, b, week })}`),
  compareAI: (a: number, b: number, week: WeekKey) =>
    request<AIResponse<ComparisonInsight>>('/api/ai/compare', { method: 'POST', body: JSON.stringify({ a, b, week }) }),
  rankings: (p: { week: WeekKey; sort?: string; order?: 'asc' | 'desc'; position?: string; team?: string; search?: string; min_games?: number; limit?: number }) =>
    request<Rankings>(`/api/rankings/weekly?${qs(p)}`),
  rankingsAI: (week: WeekKey) => request<AIResponse<RankingsInsight>>(`/api/ai/rankings?${qs({ week })}`, { method: 'POST' }),
  schedule: (week: WeekKey) => request<ScheduleSummary>(`/api/schedule/week?${qs({ week })}`),
  model: () => request<ModelInfo>('/api/model'),

  // Phase 2
  rosters: () => request<Roster[]>('/api/rosters'),
  createRoster: (name: string, player_ids: number[] = [], kind = 'mine') =>
    request<Roster>('/api/rosters', { method: 'POST', body: JSON.stringify({ name, kind, player_ids }) }),
  sampleRoster: (name: string, draft_slot: number, teams = 12) =>
    request<Roster>('/api/rosters/sample', { method: 'POST', body: JSON.stringify({ name, draft_slot, teams }) }),
  updateRoster: (id: number, patch: { name?: string; player_ids?: number[]; kind?: string }) =>
    request<Roster>(`/api/rosters/${id}`, { method: 'PUT', body: JSON.stringify(patch) }),
  deleteRoster: (id: number) => fetch(`/api/rosters/${id}`, { method: 'DELETE' }),
  analyzeTeam: (body: TeamRequest) => request<TeamAnalysis>('/api/team/analyze', { method: 'POST', body: JSON.stringify(body) }),
  teamAI: (body: TeamRequest) => request<AIResponse<TeamInsight>>('/api/ai/team', { method: 'POST', body: JSON.stringify(body) }),
  analyzeTrade: (body: TradeRequest) => request<TradeResult>('/api/trade/analyze', { method: 'POST', body: JSON.stringify(body) }),
  tradeAI: (body: TradeRequest) => request<AIResponse<TradeInsight>>('/api/ai/trade', { method: 'POST', body: JSON.stringify(body) }),
  historyWeeks: () => request<HistoryWeek[]>('/api/history/weeks'),
  historyWeek: (p: { start: string; sort?: string; position?: string; search?: string; limit?: number }) =>
    request<HistoryWeekResult>(`/api/history/week?${qs(p)}`),
  playerTrend: (id: number, season?: string) => request<PlayerTrend>(`/api/history/player/${id}?${qs({ season })}`),
  backtest: (start: string) => request<Backtest>(`/api/history/backtest?${qs({ start })}`),

  // Phase 3
  simulate: (body: MatchupRequest) => request<MatchupResult>('/api/matchup/simulate', post(body)),
  matchupAI: (body: MatchupRequest) => request<AIResponse<MatchupInsight>>('/api/ai/matchup', post(body)),
  whatif: (body: MatchupRequest & { add: number[]; drop: number[]; out: number[] }) => request<WhatIfResult>('/api/whatif', post(body)),
  suggest: (body: Omit<MatchupRequest, 'sims'> & { priority: CatKey[]; punt: CatKey[]; roster_id?: number | null }) =>
    request<SuggestResult>('/api/whatif/suggest', post(body)),
  streaming: (body: { roster_player_ids: number[]; roster_id?: number | null; week: WeekKey; slots: number; available_ids?: number[] | null; punt: CatKey[] }) =>
    request<StreamResult>('/api/streaming', post(body)),
  breakouts: (p: { as_of?: string; limit?: number; min_minutes?: number }) => request<BreakoutResult>(`/api/breakouts?${qs(p)}`),
  breakoutsAI: (p: { as_of?: string; min_minutes?: number }) => request<AIResponse<BreakoutInsight>>(`/api/ai/breakouts?${qs(p)}`, { method: 'POST' }),
  accuracy: () => request<AccuracyResult>('/api/accuracy'),
  forecast: (week: WeekKey) => request<ForecastView>(`/api/forecast?${qs({ week })}`),
  forecastPlayers: (week: WeekKey, ids: number[]) => request<{ rows: ForecastView['rows'] }>(`/api/forecast/players?${qs({ week, ids: ids.join(',') })}`),
  forecastRun: (week: WeekKey, top_n: number) => request<ForecastJob>('/api/forecast/run', post({ week, top_n })),
  forecastBacktest: (per_week = 40) => request<ForecastJob>('/api/forecast/backtest', post({ per_week })),
  forecastStatus: () => request<{ live: ForecastJob | null; backtest: ForecastJob | null; default_backtest_weeks: string[] }>('/api/forecast/status'),
  chat: (body: { message: string; history: { role: string; content: string }[]; roster_id?: number | null; opponent_roster_id?: number | null; week: WeekKey }) =>
    request<ChatReply>('/api/assistant', post(body)),
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export interface MatchupRequest {
  roster_player_ids: number[]
  opponent_player_ids: number[]
  week: WeekKey
  sims?: number
}

export interface TeamRequest {
  player_ids: number[]
  roster_id?: number | null
  week: WeekKey
  basis: Basis
  punt: CatKey[]
  assume_rostered?: number
}

export interface TradeRequest {
  roster_player_ids: number[]
  give: number[]
  get: number[]
  roster_id?: number | null
  week: WeekKey
  basis: Basis
  punt: CatKey[]
}
