import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, Sparkles } from 'lucide-react'
import { tooltipStyle } from '../components/Category'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Skeleton, StatusChip } from '../components/ui'
import { api } from '../lib/api'
import { CATS, fmt, fmtCat } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'
import type { CatKey, ForecastJob, ForecastRow } from '../lib/types'
import { JobProgress } from './Accuracy'
import { A, B } from './Matchup'

const GEM = B

export default function GeminiForecastPage() {
  const { week, meta } = useApp()
  const view = useAsync(() => api.forecast(week), [week])
  const [job, setJob] = useState<ForecastJob | null>(null)
  const [topN, setTopN] = useState(120)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const current = job ?? view.data?.job ?? null
  const running = current?.status === 'running'
  const reload = view.reload

  useEffect(() => {
    if (!running) return
    const t = setInterval(async () => {
      const st = await api.forecastStatus()
      setJob(st.live)
      if (st.live?.status !== 'running') { clearInterval(t); reload() }
    }, 3000)
    return () => clearInterval(t)
  }, [running, reload])

  const run = async () => {
    setErr(null)
    try { setJob(await api.forecastRun(week, topN)) } catch (e) { setErr((e as Error).message) }
  }

  const d = view.data
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Gemini vs Statistical</h1>
          <p className="text-sm text-fg-2">Gemini's projections next to ours, player by player.</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={topN} onChange={(e) => setTopN(Number(e.target.value))} className="rounded-lg border border-line bg-panel px-2 py-2 text-sm" aria-label="Players to forecast">
            {[40, 80, 120, 160, 200].map((n) => <option key={n} value={n}>Top {n} + rostered</option>)}
          </select>
          <button onClick={run} disabled={running || !meta?.gemini.available}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gemini px-4 py-2 text-sm font-semibold text-ink disabled:opacity-50">
            <Sparkles size={15} /> {running ? 'Forecasting…' : d?.players ? 'Regenerate forecast' : 'Generate Gemini forecast'}
          </button>
        </div>
      </div>

      {current && running && <JobProgress job={current} label={`Gemini (${current.model} via agy) is forecasting ${current.players ?? ''} players for ${current.window?.label ?? meta?.windows[week]?.label} — about 20–40s per batch of 20`} />}
      {current?.errors?.length ? <div className="text-xs text-warn">{current.errors.length} batch error(s); successful batches were kept. First: {current.errors[0]}</div> : null}
      {err && <div className="text-sm text-bad">{err}</div>}
      {view.error && <ErrorState error={view.error} onRetry={view.reload} />}
      {!d && !view.error && <Skeleton className="h-96" />}
      {d && d.players === 0 && !running && (
        <Card className="court-lines p-10 text-center">
          <div className="font-display text-2xl font-semibold">No Gemini forecast for {d.window.label} yet</div>
          <p className="mx-auto mt-2 max-w-lg text-sm text-fg-2">Generate one to see Gemini's projections next to the statistical model. Forecasts for next week are also saved so the Accuracy Tracker can score both once the week is played.</p>
        </Card>
      )}
      {d && d.players > 0 && (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <Tile label="Players forecast" value={String(d.players)} sub={`${d.model} · ${d.created_at ? new Date(d.created_at).toLocaleString() : ''}`} />
            <Tile label="Model agreement" value={fmt(d.agreement_spearman, 3)} sub="1 = same ranking order" />
            <Tile label="Avg value gap" value={fmt(d.mean_abs_value_gap, 2)} sub="|statistical − Gemini| per player" />
            <Tile label="Biggest disagreement" value={biggest(d.rows)?.name ?? '—'} sub={biggest(d.rows) ? `stat ${fmt(biggest(d.rows)!.stat_value)} vs Gemini ${fmt(biggest(d.rows)!.gemini_value)}` : ''} />
          </div>

          <div className="grid gap-4 xl:grid-cols-5">
            <Card className="p-5 xl:col-span-2">
              <SectionTitle kicker={d.window.label} title="Weekly fantasy value: statistical vs Gemini" />
              <ValueScatter rows={d.rows} />
              <p className="text-[11px] text-muted">Points above the line: Gemini is more optimistic than the statistical model.</p>
            </Card>
            <Card className="p-5 xl:col-span-3">
              <SectionTitle kicker="Where they differ most" title="Largest disagreements" />
              <div className="space-y-1.5">
                {[...d.rows].sort((a, b) => Math.abs(b.gemini_value - b.stat_value) - Math.abs(a.gemini_value - a.stat_value)).slice(0, 6).map((r) => (
                  <div key={r.player_id} className="flex items-start gap-3 rounded-lg border border-line-soft bg-ink/30 p-2.5">
                    <Headshot src={r.headshot} name={r.name} size={32} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-sm"><span className="font-medium">{r.name}</span><span className="text-xs text-muted">{r.team_abbr}</span>
                        <span className="num ml-auto text-xs"><span style={{ color: A }}>#{r.stat_rank}</span> → <span style={{ color: GEM }}>#{r.gemini_rank}</span></span></div>
                      <div className="text-xs text-fg-2">{r.rationale}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <Card className="p-4">
            <SectionTitle kicker="Weekly totals · statistical / Gemini" title="Side by side" right={
              <div className="flex gap-3 text-[11px] text-muted"><span style={{ color: A }}>■ statistical</span><span style={{ color: GEM }}>■ Gemini</span></div>} />
            <div className="scrollbar-thin overflow-x-auto">
              <table className="w-full min-w-[1150px] text-sm">
                <thead className="text-[11px] uppercase tracking-wider text-muted">
                  <tr className="border-b border-line">
                    <th className="px-2 py-2 text-left font-medium">Player</th>
                    <th className="px-2 text-right font-medium">Games</th>
                    <th className="px-2 text-right font-medium">MIN</th>
                    {CATS.map((c) => <th key={c.key} className="px-2 text-right font-medium">{c.label}</th>)}
                    <th className="px-2 text-right font-medium">Value</th>
                    <th className="px-2 text-right font-medium">Rank</th>
                    <th className="px-2 text-left font-medium">Conf.</th>
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((r) => (
                    <Fragment key={r.player_id}>
                      <tr onClick={() => setOpen(open === r.player_id ? null : r.player_id)} className="cursor-pointer border-b border-line-soft hover:bg-panel-2/60">
                        <td className="px-2 py-1.5">
                          <div className="flex items-center gap-2"><Headshot src={r.headshot} name={r.name} size={28} />
                            <div className="min-w-0"><div className="truncate">{r.name}</div>
                              <div className="flex items-center gap-1 text-[11px] text-muted">{r.team_abbr} · {r.position} {!r.status.startsWith('Active') && <StatusChip status={r.status} />}</div></div></div>
                        </td>
                        <Pair a={fmt(r.stat_expected_games, 1)} b={fmt(r.gemini_expected_games, 1)} />
                        <Pair a={fmt(r.stat_min)} b={fmt(r.gemini_min)} />
                        {CATS.map((c) => <CatCell key={c.key} k={c.key} v={r.categories[c.key]} />)}
                        <Pair a={fmt(r.stat_value, 2)} b={fmt(r.gemini_value, 2)} bold />
                        <Pair a={`#${r.stat_rank}`} b={`#${r.gemini_rank}`} />
                        <td className="px-2"><Pill tone={r.confidence === 'high' ? 'good' : r.confidence === 'medium' ? 'brand' : 'warn'}>{r.confidence}</Pill></td>
                      </tr>
                      {open === r.player_id && (
                        <tr className="border-b border-line-soft bg-gemini/5">
                          <td colSpan={14} className="px-4 py-2 text-xs text-fg-2">
                            <span className="font-semibold text-gemini">Gemini's reasoning: </span>{r.rationale}
                            {r.fixes.length > 0 && <span className="ml-2 text-warn">(validated: {r.fixes.join(', ')})</span>}
                            <Link to={`/compare?a=${r.player_id}`} className="ml-3 inline-flex items-center gap-1 text-brand hover:underline">Compare <ArrowRight size={11} /></Link>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-muted">Each cell shows statistical over Gemini. Gemini totals = its per-game forecast × the games it expects the player to play. Click a row for Gemini's reasoning.</p>
          </Card>
        </>
      )}
    </div>
  )
}

function biggest(rows: ForecastRow[]) {
  return [...rows].sort((a, b) => Math.abs(b.gemini_value - b.stat_value) - Math.abs(a.gemini_value - a.stat_value))[0]
}

function Pair({ a, b, bold }: { a: string; b: string; bold?: boolean }) {
  return (
    <td className={`num px-2 text-right leading-tight ${bold ? 'font-semibold' : ''}`}>
      <div style={{ color: A }}>{a}</div><div style={{ color: GEM }}>{b}</div>
    </td>
  )
}

function CatCell({ k, v }: { k: CatKey; v: { stat: number | null; gemini: number | null } }) {
  const diff = v.stat && v.gemini !== null ? (v.gemini - v.stat) / Math.abs(v.stat) : 0
  const tint = Math.abs(diff) >= 0.15 ? (diff > 0 ? 'rgba(46,155,214,0.12)' : 'rgba(229,100,26,0.12)') : 'transparent'
  return (
    <td className="num px-2 text-right leading-tight" style={{ background: tint }} title={Math.abs(diff) >= 0.15 ? `Gemini ${diff > 0 ? 'higher' : 'lower'} by ${Math.round(Math.abs(diff) * 100)}%` : undefined}>
      <div style={{ color: A }}>{fmtCat(k, v.stat)}</div><div style={{ color: GEM }}>{fmtCat(k, v.gemini)}</div>
    </td>
  )
}

function ValueScatter({ rows }: { rows: ForecastRow[] }) {
  const lim = Math.ceil(1.1 * Math.max(5, ...rows.flatMap((r) => [Math.abs(r.stat_value), Math.abs(r.gemini_value)])))
  return (
    <div className="h-80">
      <ResponsiveContainer>
        <ScatterChart margin={{ left: -10, right: 10, top: 8, bottom: 8 }}>
          <CartesianGrid stroke="#1b2638" />
          <XAxis type="number" dataKey="stat_value" name="Statistical" domain={[-lim, lim]} stroke="#7d8aa2" fontSize={11} tickLine={false}
            label={{ value: 'statistical', position: 'insideBottomRight', offset: -4, fill: '#7d8aa2', fontSize: 11 }} />
          <YAxis type="number" dataKey="gemini_value" name="Gemini" domain={[-lim, lim]} stroke="#7d8aa2" fontSize={11} tickLine={false}
            label={{ value: 'Gemini', angle: -90, position: 'insideLeft', offset: 18, fill: '#7d8aa2', fontSize: 11 }} />
          <ReferenceLine segment={[{ x: -lim, y: -lim }, { x: lim, y: lim }]} stroke="#7d8aa2" strokeDasharray="4 4" />
          <Tooltip contentStyle={tooltipStyle} content={({ payload }) => {
            const p = payload?.[0]?.payload as ForecastRow | undefined
            return p ? <div style={tooltipStyle} className="px-3 py-2"><div className="font-medium">{p.name}</div><div className="text-xs text-fg-2">statistical {p.stat_value.toFixed(2)} · Gemini {p.gemini_value.toFixed(2)}</div></div> : null
          }} />
          <Scatter isAnimationActive={false} data={rows} fill={B} fillOpacity={0.75} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num truncate font-display text-2xl font-semibold">{value}</div>
      {sub && <div className="truncate text-xs text-muted">{sub}</div>}
    </Card>
  )
}
