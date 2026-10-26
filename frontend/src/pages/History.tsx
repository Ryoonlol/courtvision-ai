import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search, X } from 'lucide-react'
import { POS, tooltipStyle } from '../components/Category'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Segmented, Skeleton, TeamLogo } from '../components/ui'
import { api } from '../lib/api'
import { CATS, fmt, fmtCat, shortDate, zTint } from '../lib/format'
import { useAsync, useDebounced } from '../lib/hooks'
import type { Backtest, BacktestPlayer, CatKey, HistoryWeekResult } from '../lib/types'

type Tab = 'rankings' | 'backtest'

export default function HistoryPage() {
  const weeks = useAsync(() => api.historyWeeks(), [])
  const [start, setStart] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('rankings')
  const [sort, setSort] = useState<string>('value')
  const [position, setPosition] = useState('')
  const [search, setSearch] = useState('')
  const [player, setPlayer] = useState<number | null>(null)
  const dsearch = useDebounced(search, 250)

  useEffect(() => {
    if (!start && weeks.data?.length) setStart((weeks.data.find((w) => !w.in_progress) ?? weeks.data[0]).week_start)
  }, [weeks.data, start])

  const idx = weeks.data?.findIndex((w) => w.week_start === start) ?? -1
  const week = idx >= 0 ? weeks.data![idx] : null
  const data = useAsync(() => api.historyWeek({ start: start!, sort, position, search: dsearch, limit: 200 }),
    [start, sort, position, dsearch], !!start)
  const bt = useAsync(() => api.backtest(start!), [start], !!start && tab === 'backtest')

  const seasons = useMemo(() => {
    const out: Record<string, typeof weeks.data> = {}
    weeks.data?.forEach((w) => { (out[w.season] ??= []).push(w) })
    return out
  }, [weeks.data])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Past Weeks</h1>
          <p className="text-sm text-fg-2">Real results from past weeks.</p>
        </div>
        <div className="flex items-center gap-2">
          <button disabled={!weeks.data || idx >= weeks.data.length - 1} onClick={() => setStart(weeks.data![idx + 1].week_start)}
            className="rounded-lg border border-line p-2 text-fg-2 hover:text-brand disabled:opacity-30" aria-label="Previous week"><ChevronLeft size={16} /></button>
          <select value={start ?? ''} onChange={(e) => setStart(e.target.value)} className="rounded-lg border border-line bg-panel px-3 py-2 text-sm text-fg" aria-label="Select week">
            {Object.entries(seasons).map(([season, ws]) => (
              <optgroup key={season} label={season}>
                {ws!.map((w) => <option key={w.week_start} value={w.week_start}>{w.label}{w.in_progress ? ' (in progress)' : ''}</option>)}
              </optgroup>
            ))}
          </select>
          <button disabled={idx <= 0} onClick={() => setStart(weeks.data![idx - 1].week_start)}
            className="rounded-lg border border-line p-2 text-fg-2 hover:text-brand disabled:opacity-30" aria-label="Next week"><ChevronRight size={16} /></button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Segmented<Tab> value={tab} onChange={setTab} options={[{ value: 'rankings', label: 'Actual rankings' }, { value: 'backtest', label: 'Projected vs actual' }]} />
        {week?.in_progress && <Pill tone="warn">Week in progress — partial results</Pill>}
        {week && <Pill>{week.season} · {week.players} players</Pill>}
      </div>

      {weeks.error && <ErrorState error={weeks.error} onRetry={weeks.reload} />}

      {tab === 'rankings' && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
          <Card className="min-w-0 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <div className="flex min-w-[200px] flex-1 items-center gap-2 rounded-lg border border-line bg-panel px-3 py-1.5">
                <Search size={14} className="text-muted" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter by name" className="w-full bg-transparent text-sm focus:outline-none" />
              </div>
              <Segmented value={position} onChange={setPosition} options={[{ value: '', label: 'All' }, { value: 'G', label: 'G' }, { value: 'F', label: 'F' }, { value: 'C', label: 'C' }]} />
            </div>
            {data.error && <ErrorState error={data.error} onRetry={data.reload} />}
            {!data.data && !data.error && <Skeleton className="h-96" />}
            {data.data && <WeekTable d={data.data} sort={sort} onSort={setSort} onPick={setPlayer} dim={data.loading} />}
          </Card>
          <div className="space-y-4">
            {player && <TrendCard playerId={player} defaultSeason={week?.season} onClose={() => setPlayer(null)} />}
            {data.data && <Leaders d={data.data} />}
          </div>
        </div>
      )}

      {tab === 'backtest' && (
        <>
          {bt.error && <ErrorState error={bt.error} onRetry={bt.reload} />}
          {bt.loading && <Skeleton className="h-96" />}
          {bt.data && !bt.loading && <BacktestView b={bt.data} />}
        </>
      )}
    </div>
  )
}

function WeekTable({ d, sort, onSort, onPick, dim }: { d: HistoryWeekResult; sort: string; onSort: (s: string) => void; onPick: (id: number) => void; dim: boolean }) {
  const Th = ({ k, label }: { k: string; label: string }) => (
    <th onClick={() => onSort(k)} className={`cursor-pointer select-none px-2 py-2 text-right font-medium hover:text-fg ${sort === k ? 'text-brand' : ''}`}>{label}</th>
  )
  return (
    <div className={`scrollbar-thin overflow-x-auto ${dim ? 'opacity-60' : ''}`}>
      <table className="w-full min-w-[1000px] text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-muted">
          <tr className="border-b border-line">
            <th className="px-2 py-2 text-left font-medium">#</th>
            <th className="px-2 py-2 text-left font-medium">Player</th>
            <Th k="games" label="G" />
            <Th k="min" label="MIN" />
            {CATS.map((c) => <Th key={c.key} k={c.key} label={c.label} />)}
            <Th k="value" label="Value" />
          </tr>
        </thead>
        <tbody>
          {d.rows.map((r) => {
            const delta = r.prev_rank ? r.prev_rank - r.rank : null
            return (
              <tr key={r.player_id} onClick={() => onPick(r.player_id)} className="cursor-pointer border-b border-line-soft hover:bg-panel-2/60">
                <td className="px-2 py-1.5">
                  <div className="font-display text-base text-muted">{r.rank}</div>
                  {delta !== null && delta !== 0 && (
                    <div className={`flex items-center text-[10px] ${delta > 0 ? 'text-good' : 'text-bad'}`}>
                      {delta > 0 ? <ArrowUp size={10} /> : <ArrowDown size={10} />}{Math.abs(delta)}
                    </div>
                  )}
                </td>
                <td className="px-2">
                  <div className="flex items-center gap-2.5">
                    <Headshot src={r.headshot} name={r.name} size={30} />
                    <div className="min-w-0">
                      <div className="truncate font-medium">{r.name}</div>
                      <div className="flex items-center gap-1 text-[11px] text-muted"><TeamLogo src={r.team_logo} abbr={r.team_abbr} size={13} /> {r.team_abbr} · {r.position}</div>
                    </div>
                  </div>
                </td>
                <td className="num px-2 text-right">{r.games}</td>
                <td className="num px-2 text-right text-muted">{fmt(r.min, 0)}</td>
                {CATS.map((c) => (
                  <td key={c.key} className="num px-2 text-right" style={{ background: zTint(r[`z_${c.key}`] as number) }} title={c.key === 'fg_pct' ? `${r.fgm}/${r.fga} FG` : c.key === 'ft_pct' ? `${r.ftm}/${r.fta} FT` : undefined}>
                    {fmtCat(c.key, r[c.key] as number, c.pct ? 1 : 0)}
                  </td>
                ))}
                <td className="num px-2 text-right font-display text-base font-semibold text-brand">{fmt(r.value, 2)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-muted">Actual weekly totals; blue = above average, red = below. Arrows show rank change from the previous week. Click a player for their season trend.</p>
    </div>
  )
}

function Leaders({ d }: { d: HistoryWeekResult }) {
  const [cat, setCat] = useState<CatKey>('pts')
  return (
    <Card className="p-5">
      <SectionTitle kicker={d.label} title="Category leaders" />
      <div className="mb-3 flex flex-wrap gap-1">
        {CATS.map((c) => (
          <button key={c.key} onClick={() => setCat(c.key)} className={`rounded-md px-2 py-0.5 text-xs ${cat === c.key ? 'bg-brand text-ink' : 'bg-panel-2 text-fg-2 hover:text-fg'}`}>{c.label}</button>
        ))}
      </div>
      {d.leaders[cat].map((l, i) => (
        <div key={l.player_id} className="flex items-center gap-3 py-1.5">
          <span className="w-4 font-display text-muted">{i + 1}</span>
          <Headshot src={l.headshot} name={l.name} size={28} />
          <span className="flex-1 truncate text-sm">{l.name} <span className="text-xs text-muted">{l.team_abbr}</span></span>
          <span className="num font-display text-lg font-semibold">{fmtCat(cat, l.value)}</span>
        </div>
      ))}
    </Card>
  )
}

function TrendCard({ playerId, defaultSeason, onClose }: { playerId: number; defaultSeason?: string; onClose: () => void }) {
  const [season, setSeason] = useState<string | undefined>(defaultSeason)
  useEffect(() => setSeason(defaultSeason), [playerId, defaultSeason])
  const t = useAsync(() => api.playerTrend(playerId, season), [playerId, season])
  return (
    <Card className="p-5">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-brand">Player trend</div>
          <div className="font-display text-xl font-semibold">{t.data?.name ?? '…'}</div>
        </div>
        <button onClick={onClose} className="text-muted hover:text-fg" aria-label="Close trend"><X size={16} /></button>
      </div>
      {t.data && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <select value={t.data.season} onChange={(e) => setSeason(e.target.value)} className="rounded border border-line bg-panel px-2 py-1 text-xs">
            {t.data.seasons_available.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <Pill>avg value {fmt(t.data.avg_value)}</Pill>
          {t.data.best_rank && <Pill tone="brand">best rank #{t.data.best_rank}</Pill>}
          {t.data.trend_per_week !== null && (
            <Pill tone={t.data.trend_per_week > 0.05 ? 'good' : t.data.trend_per_week < -0.05 ? 'bad' : 'default'}>
              {t.data.trend_per_week > 0 ? '▲' : '▼'} {fmt(Math.abs(t.data.trend_per_week), 2)}/wk
            </Pill>
          )}
        </div>
      )}
      {!t.data && <Skeleton className="h-44" />}
      {t.data && (
        <div className="h-48">
          <ResponsiveContainer>
            <LineChart data={t.data.weeks} margin={{ left: -20, right: 8, top: 6 }}>
              <CartesianGrid vertical={false} stroke="#1b2638" />
              <XAxis dataKey="week_start" tickFormatter={shortDate} stroke="#7d8aa2" fontSize={10} tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis stroke="#7d8aa2" fontSize={10} tickLine={false} axisLine={false} />
              <ReferenceLine y={0} stroke="#7d8aa2" strokeDasharray="3 3" />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={(l) => `Week of ${shortDate(String(l))}`}
                formatter={(v, n, item) => n === 'value' ? [`${Number(v).toFixed(2)} (rank #${item.payload.rank}, ${item.payload.games}G)`, 'fantasy value'] : [v, n]} />
              <Line isAnimationActive={false} type="monotone" dataKey="value" stroke={POS} strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: POS }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-[11px] text-muted">Actual fantasy value each week; trend = average change per week.</p>
    </Card>
  )
}

function BacktestView({ b }: { b: Backtest }) {
  const lim = Math.ceil(Math.max(...b.scatter.flatMap((s) => [Math.abs(s.projected), Math.abs(s.actual)]), 5))
  return (
    <div className="space-y-4">
      <Card className="border-warn/30 p-4 text-sm text-fg-2">
        <span className="font-semibold text-warn">Backtest method: </span>{b.method} This answers “how well would the explainable model have ranked this week?” without peeking at the week itself.
      </Card>
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted">Ranking accuracy</div>
          <div className="num font-display text-3xl font-semibold text-brand">{b.value_rank_spearman.toFixed(2)}</div>
          <div className="text-xs text-muted">1 = perfect order · {b.players} players</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted">Top-50 overlap</div>
          <div className="num font-display text-3xl font-semibold">{Math.round(b.top50_overlap * 100)}%</div>
          <div className="text-xs text-muted">of projected top 50 finished top 50</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted">Saved live projection</div>
          {b.saved_projection ? (
            <>
              <div className="num font-display text-3xl font-semibold text-good">{b.saved_projection.players} players</div>
              <div className="text-xs text-muted">PTS MAE {fmt(b.saved_projection.weekly_mae?.pts)} · {b.saved_projection.note}</div>
            </>
          ) : (
            <>
              <div className="font-display text-xl font-semibold text-muted">None for this week</div>
              <div className="text-xs text-muted">Live projections are saved before each upcoming week and scored here once it is played.</div>
            </>
          )}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="p-5">
          <SectionTitle kicker="Top 120 actual performers" title="Projected vs actual value" />
          <div className="h-80">
            <ResponsiveContainer>
              <ScatterChart margin={{ left: -10, right: 10, top: 8, bottom: 8 }}>
                <CartesianGrid stroke="#1b2638" />
                <XAxis type="number" dataKey="projected" name="Projected" domain={[-lim, lim]} stroke="#7d8aa2" fontSize={11} tickLine={false} label={{ value: 'projected', position: 'insideBottomRight', offset: -4, fill: '#7d8aa2', fontSize: 11 }} />
                <YAxis type="number" dataKey="actual" name="Actual" domain={[-lim, lim]} stroke="#7d8aa2" fontSize={11} tickLine={false} label={{ value: 'actual', angle: -90, position: 'insideLeft', offset: 18, fill: '#7d8aa2', fontSize: 11 }} />
                <ReferenceLine segment={[{ x: -lim, y: -lim }, { x: lim, y: lim }]} stroke="#7d8aa2" strokeDasharray="4 4" />
                <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: '3 3' }}
                  content={({ payload }) => {
                    const p = payload?.[0]?.payload as Backtest['scatter'][number] | undefined
                    return p ? <div style={tooltipStyle} className="px-3 py-2"><div className="font-medium">{p.name}</div><div className="text-xs text-fg-2">projected {p.projected.toFixed(2)} · actual {p.actual.toFixed(2)}</div></div> : null
                  }} />
                <Scatter isAnimationActive={false} data={b.scatter} fill={POS} fillOpacity={0.75} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11px] text-muted">Points on the dashed line were projected exactly; above = beat projection.</p>
        </Card>
        <Card className="p-5">
          <SectionTitle kicker="Weekly totals" title="Error by category" />
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Cat</th><th className="text-right font-medium">Mean abs. error</th><th className="text-right font-medium">Avg actual</th><th className="text-right font-medium">Relative</th></tr>
            </thead>
            <tbody>
              {CATS.map((c) => {
                const m = b.category_mae[c.key]
                return (
                  <tr key={c.key} className="border-b border-line-soft">
                    <td className="py-1.5 font-medium">{c.label}</td>
                    <td className="num text-right">{c.pct ? `${(m.mae * 100).toFixed(1)} pts` : fmt(m.mae, 2)}</td>
                    <td className="num text-right text-muted">{m.mean_actual !== undefined ? fmt(m.mean_actual) : 'attempt-wtd'}</td>
                    <td className="num text-right text-muted">{m.mean_actual ? `${Math.round((m.mae / m.mean_actual) * 100)}%` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Movers title="Beat projection" players={b.overperformers} tone="good" />
            <Movers title="Fell short" players={b.underperformers} tone="bad" />
          </div>
        </Card>
      </div>
    </div>
  )
}

function Movers({ title, players, tone }: { title: string; players: BacktestPlayer[]; tone: 'good' | 'bad' }) {
  return (
    <div>
      <div className={`mb-1 text-[11px] font-semibold uppercase tracking-wider ${tone === 'good' ? 'text-good' : 'text-bad'}`}>{title}</div>
      {players.map((p) => (
        <div key={p.player_id} className="flex items-center gap-2 py-1 text-xs">
          <Headshot src={p.headshot} name={p.name} size={22} />
          <span className="flex-1 truncate">{p.name}</span>
          <span className="num text-muted">{fmt(p.projected_value)} → </span>
          <span className={`num font-semibold ${tone === 'good' ? 'text-good' : 'text-bad'}`}>{fmt(p.actual_value)}</span>
        </div>
      ))}
    </div>
  )
}
