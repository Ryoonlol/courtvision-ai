import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, Sparkles, Target } from 'lucide-react'
import { tooltipStyle } from '../components/Category'
import { Card, ErrorState, Pill, SectionTitle, Segmented, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { CATS, fmt, shortDate } from '../lib/format'
import { useAsync } from '../lib/hooks'
import type { AccuracyMetrics, CatKey, ForecastJob } from '../lib/types'
import { A, B } from './Matchup'

type Metric = 'spearman' | CatKey

export default function AccuracyPage() {
  const res = useAsync(() => api.accuracy(), [])
  const [metric, setMetric] = useState<Metric>('spearman')
  const [scope, setScope] = useState<string>('overall')

  const chart = useMemo(() => res.data?.weeks.map((w) => ({
    week: w.week_start, season: w.season,
    'CourtVision weighted': w.weighted[metric] === null ? null : metricValue(metric, w.weighted[metric]!),
    'Season average': w.naive[metric] === null ? null : metricValue(metric, w.naive[metric]!),
  })) ?? [], [res.data, metric])

  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />
  if (!res.data) return <Skeleton className="h-[600px]" />
  const d = res.data
  const block = scope === 'overall' ? d.overall : d.by_season[scope]
  const lowerBetter = metric !== 'spearman'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-bold tracking-wide">Accuracy Tracker</h1>
        <p className="text-sm text-fg-2">How close our projections came, week by week.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Tile label="Weeks evaluated" value={String(d.weeks.length)} sub={Object.entries(d.by_season).map(([s, v]) => `${s}: ${v.weeks}`).join(' · ')} />
        <Tile label="Ranking accuracy" value={fmt(d.overall.weighted.spearman, 3)} sub={`season avg ${fmt(d.overall.naive.spearman, 3)}`} accent={A} />
        <Tile label="Top-50 overlap" value={`${Math.round((d.overall.weighted.top50_overlap ?? 0) * 100)}%`} sub={`season avg ${Math.round((d.overall.naive.top50_overlap ?? 0) * 100)}%`} />
        <Tile label="PTS error / week" value={fmt(d.overall.weighted.pts, 2)} sub={`season avg ${fmt(d.overall.naive.pts, 2)} · lower is better`} />
      </div>

      <Card className="p-5">
        <SectionTitle kicker="Week by week" title={metric === 'spearman' ? 'Ranking accuracy (1 = perfect order)' : `${CATS.find((c) => c.key === metric)?.label} mean absolute error per player-week`}
          right={<select value={metric} onChange={(e) => setMetric(e.target.value as Metric)} className="rounded-lg border border-line bg-panel px-2 py-1 text-sm">
            <option value="spearman">Ranking accuracy</option>
            {CATS.map((c) => <option key={c.key} value={c.key}>{c.label} error</option>)}
          </select>} />
        <div className="h-72">
          <ResponsiveContainer>
            <LineChart data={chart} margin={{ left: -10, right: 12, top: 8 }}>
              <CartesianGrid vertical={false} stroke="#1b2638" />
              <XAxis dataKey="week" tickFormatter={(v) => shortDate(v)} stroke="#7d8aa2" fontSize={10} tickLine={false} axisLine={false} minTickGap={30} />
              <YAxis stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} domain={['auto', 'auto']} unit={metric.endsWith('pct') ? ' pts' : ''} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={(l, p) => `Week of ${shortDate(String(l))} (${p?.[0]?.payload.season ?? ''})`}
                formatter={(v) => (typeof v === 'number' ? v.toFixed(3) : v)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line isAnimationActive={false} type="monotone" dataKey="CourtVision weighted" stroke={A} strokeWidth={2} dot={false} connectNulls />
              <Line isAnimationActive={false} type="monotone" dataKey="Season average" stroke={B} strokeWidth={2} dot={false} strokeDasharray="5 4" connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="text-[11px] text-muted">{lowerBetter ? 'Lower is better.' : 'Higher is better (1 = perfect ranking).'} Season openers rely on prior-season data, and final weeks include rest/tanking lineups, so those weeks are hardest.</p>
      </Card>

      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="p-5 xl:col-span-3">
          <SectionTitle kicker="Category-level accuracy" title="Average miss per player-week" right={
            <Segmented value={scope} onChange={setScope} options={[{ value: 'overall', label: 'All' }, ...Object.keys(d.by_season).map((s) => ({ value: s, label: s }))]} />} />
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Cat</th><th className="text-right font-medium">CourtVision</th><th className="text-right font-medium">Season avg</th><th className="text-right font-medium">Improvement</th></tr>
            </thead>
            <tbody>
              {CATS.map((c) => {
                const w = block.weighted[c.key], n = block.naive[c.key]
                const imp = w !== null && n ? (1 - w / n) * 100 : null
                return (
                  <tr key={c.key} className="border-b border-line-soft">
                    <td className="py-1.5 font-medium">{c.label}</td>
                    <td className="num text-right">{show(c.key, w)}</td>
                    <td className="num text-right text-muted">{show(c.key, n)}</td>
                    <td className={`num text-right font-semibold ${imp !== null && imp > 0 ? 'text-good' : 'text-bad'}`}>{imp === null ? '—' : `${imp > 0 ? '+' : ''}${imp.toFixed(1)}%`}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted">{d.method_notes.scope}. FG%/FT% errors are attempt-weighted percentage points.</p>
        </Card>
        <Card className="p-5 xl:col-span-2">
          <SectionTitle kicker="Live, pre-week projections" title="Saved projection log" right={<Target size={16} className="text-brand" />} />
          {d.saved_projections.length === 0 && <div className="text-sm text-muted">No saved projections yet.</div>}
          <div className="space-y-2">
            {d.saved_projections.map((s) => (
              <div key={s.week_start} className="rounded-xl border border-line-soft bg-ink/30 p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">Week of {shortDate(s.week_start)}</span>
                  <Pill tone={s.status === 'scored' ? 'good' : 'warn'}>{s.status}</Pill>
                </div>
                {Object.entries(s.methods).map(([m, v]) => (
                  <div key={m} className="mt-1 text-xs">
                    <span className={m === 'gemini' ? 'text-gemini' : 'text-brand'}>{m === 'gemini' ? 'Gemini forecast' : 'Statistical model'}</span>
                    <span className="text-muted"> · {v.players_projected} players · saved {new Date(v.saved_at).toLocaleString()}</span>
                    {v.mae && <div className="text-fg-2">PTS avg miss {fmt(v.mae.pts)} · REB {fmt(v.mae.reb)} · AST {fmt(v.mae.ast)}{v.spearman_value !== undefined ? ` · ranking accuracy ${fmt(v.spearman_value, 3)}` : ''}</div>}
                  </div>
                ))}
                {s.common_players !== undefined && <div className="mt-1 text-[11px] text-muted">Scored on the {s.common_players} players every method projected.</div>}
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-muted">Statistical projections are saved automatically before each week; Gemini forecasts are saved when you generate them for next week. Both are scored once the week ends — this is the clean, forward-looking comparison.</p>
          <Link to="/model" className="mt-3 inline-flex items-center gap-1 text-xs text-brand hover:underline">Per-game model validation in Model Lab <ArrowRight size={12} /></Link>
        </Card>
      </div>

      <GeminiVsStat />
    </div>
  )
}

function GeminiVsStat() {
  const res = useAsync(() => api.accuracy(), [])
  const [job, setJob] = useState<ForecastJob | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const status = useAsync(() => api.forecastStatus(), [])
  const running = (job ?? status.data?.backtest)?.status === 'running'
  const reload = res.reload

  useEffect(() => {
    if (!running) return
    const t = setInterval(async () => {
      const st = await api.forecastStatus()
      setJob(st.backtest)
      if (st.backtest?.status !== 'running') { clearInterval(t); reload() }
    }, 3000)
    return () => clearInterval(t)
  }, [running, reload])

  const start = async () => {
    setErr(null)
    try { setJob(await api.forecastBacktest(40)) } catch (e) { setErr((e as Error).message) }
  }
  const bt = res.data?.gemini_backtest
  const o = bt?.overall
  const cur = job ?? status.data?.backtest ?? null
  return (
    <Card className="p-5">
      <SectionTitle kicker="Same players, same weeks" title="Gemini forecast vs statistical model" right={
        <button onClick={start} disabled={running} className="inline-flex items-center gap-1.5 rounded-lg bg-gemini px-3 py-1.5 text-sm font-semibold text-ink disabled:opacity-50">
          <Sparkles size={14} /> {running ? 'Backtesting…' : o ? 'Re-run Gemini backtest' : 'Run Gemini backtest'}
        </button>} />
      {cur && cur.status === 'running' && <JobProgress job={cur} label="Gemini is forecasting past weeks from only the data before each week" />}
      {cur?.errors?.length ? <div className="mb-2 text-xs text-warn">{cur.errors.length} batch error(s): {cur.errors[0]}</div> : null}
      {err && <div className="mb-2 text-sm text-bad">{err}</div>}
      {!o && !running && <div className="text-sm text-muted">No Gemini backtest yet. It forecasts 40 players in each of {status.data?.default_backtest_weeks.length ?? 4} past weeks (about 3–6 minutes through agy).</div>}
      {o && bt && (
        <>
          <div className="mb-3 grid gap-3 md:grid-cols-3">
            {(['gemini', 'weighted', 'naive'] as const).map((m) => (
              <div key={m} className="rounded-xl border border-line-soft bg-ink/30 p-3">
                <div className={`text-[11px] uppercase tracking-wider ${m === 'gemini' ? 'text-gemini' : m === 'weighted' ? 'text-brand' : 'text-muted'}`}>{LABEL[m]}</div>
                <div className="num font-display text-2xl font-semibold">{fmt(o[m].spearman, 3)}</div>
                <div className="text-xs text-muted">ranking accuracy · PTS miss {fmt(o[m].pts, 2)}</div>
              </div>
            ))}
          </div>
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Cat (avg miss / player-week)</th><th className="text-right font-medium text-gemini">Gemini</th><th className="text-right font-medium text-brand">Statistical</th><th className="text-right font-medium">Season avg</th><th className="text-right font-medium">Best</th></tr>
            </thead>
            <tbody>
              {CATS.map((c) => {
                const vals = { gemini: o.gemini[c.key], weighted: o.weighted[c.key], naive: o.naive[c.key] }
                const best = (Object.entries(vals) as [keyof typeof LABEL, number | null][]).filter(([, v]) => v !== null).sort((a, b) => (a[1]! - b[1]!))[0]?.[0]
                return (
                  <tr key={c.key} className="border-b border-line-soft">
                    <td className="py-1.5 font-medium">{c.label}</td>
                    {(['gemini', 'weighted', 'naive'] as const).map((m) => <td key={m} className={`num text-right ${best === m ? 'font-semibold text-good' : ''}`}>{show(c.key, vals[m])}</td>)}
                    <td className="text-right text-xs text-muted">{best ? LABEL[best] : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
            {bt.weeks.map((w) => <Pill key={w.week_start}>Week of {shortDate(w.week_start)}: {w.players} players · Gemini {fmt(w.gemini.spearman, 2)} vs statistical {fmt(w.weighted.spearman, 2)}</Pill>)}
          </div>
          <p className="mt-3 text-[11px] text-warn">{bt.caveat}</p>
          <p className="mt-1 text-[11px] text-muted">All three use only games before each week and are scaled by games actually played. The 40 players per week were picked by the statistical model's pre-week value, not by results.</p>
        </>
      )}
    </Card>
  )
}

const LABEL = { gemini: 'Gemini forecast', weighted: 'Statistical (CourtVision)', naive: 'Season average' }

export function JobProgress({ job, label }: { job: ForecastJob; label: string }) {
  const pct = job.total ? (job.done / job.total) * 100 : 0
  return (
    <div className="mb-3 rounded-lg border border-gemini/30 bg-gemini/5 p-3">
      <div className="mb-1.5 flex items-center justify-between text-xs"><span className="text-gemini">{label}</span><span className="num text-fg-2">{job.done}/{job.total} batches</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-line-soft"><div className="h-full rounded-full bg-gemini transition-all" style={{ width: `${pct}%` }} /></div>
    </div>
  )
}

function metricValue(metric: Metric, v: number): number {
  return metric === 'fg_pct' || metric === 'ft_pct' ? +(v * 100).toFixed(2) : +v.toFixed(3)
}

function show(key: CatKey, v: AccuracyMetrics[CatKey]) {
  if (v === null || v === undefined) return '—'
  return key === 'fg_pct' || key === 'ft_pct' ? `${(v * 100).toFixed(1)} pts` : v.toFixed(2)
}

function Tile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-3xl font-semibold" style={{ color: accent }}>{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </Card>
  )
}
