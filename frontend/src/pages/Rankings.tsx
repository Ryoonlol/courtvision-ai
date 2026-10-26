import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowDown, ArrowUp, Search } from 'lucide-react'
import { AIPanel } from '../components/AIPanel'
import { Bullets, ChipRow, Emph, Headline, Lead, More, Sub } from '../components/Insight'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Segmented, Skeleton, StatusChip, TeamLogo } from '../components/ui'
import { api } from '../lib/api'
import { CATS, CAT_LABEL, fmt, fmtCat, signed, zTint } from '../lib/format'
import { useApp, useAsync, useDebounced } from '../lib/hooks'
import type { CatKey, RankingRow, Rankings, RankingsInsight } from '../lib/types'

type SortKey = 'value' | 'pg_value' | 'games' | CatKey

export default function RankingsPage() {
  const { week } = useApp()
  const [sort, setSort] = useState<SortKey>('value')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [position, setPosition] = useState('')
  const [team, setTeam] = useState('')
  const [search, setSearch] = useState('')
  const [minGames, setMinGames] = useState(1)
  const [mode, setMode] = useState<'total' | 'z'>('total')
  const dsearch = useDebounced(search, 250)

  const data = useAsync(() => api.rankings({ week, sort, order, position, team, search: dsearch, min_games: minGames, limit: 200 }),
    [week, sort, order, position, team, dsearch, minGames])
  const ai = useAsync(() => api.rankingsAI(week), [week])
  const schedule = useAsync(() => api.schedule(week), [week])
  const teams = schedule.data?.games_by_team.map((t) => t.abbr).sort() ?? []

  const clickSort = (k: SortKey) => {
    if (k === sort) setOrder(order === 'desc' ? 'asc' : 'desc')
    else { setSort(k); setOrder(k === 'tov' ? 'asc' : 'desc') }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-bold tracking-wide">Projected Leaderboard</h1>
        <p className="text-sm text-fg-2 cursor-help" title="Ranked by fantasy value: each player's projected weekly totals across all 9 categories, compared with the average starter.">Best projected players for the week. ⓘ</p>
      </div>

      <Card className="p-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="flex min-w-[200px] flex-1 items-center gap-2 rounded-lg border border-line bg-panel px-3 py-1.5">
            <Search size={14} className="text-muted" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter by name" className="w-full bg-transparent text-sm focus:outline-none" />
          </div>
          <Segmented value={position} onChange={setPosition} options={[{ value: '', label: 'All' }, { value: 'G', label: 'G' }, { value: 'F', label: 'F' }, { value: 'C', label: 'C' }]} />
          <select value={team} onChange={(e) => setTeam(e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-fg-2">
            <option value="">All teams</option>
            {teams.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={minGames} onChange={(e) => setMinGames(Number(e.target.value))} className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-fg-2">
            {[0, 1, 2, 3, 4].map((g) => <option key={g} value={g}>{g === 0 ? 'Any games' : `${g}+ games`}</option>)}
          </select>
          <select value={sort} onChange={(e) => { const k = e.target.value as SortKey; setSort(k); setOrder(k === 'tov' ? 'asc' : 'desc') }} className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-fg-2">
            <option value="value">Sort: fantasy value</option>
            <option value="pg_value">Sort: per-game value</option>
            <option value="games">Sort: games</option>
            {CATS.map((c) => <option key={c.key} value={c.key}>Sort: {c.label}</option>)}
          </select>
          <Segmented value={mode} onChange={setMode} options={[{ value: 'total', label: 'Totals' }, { value: 'z', label: 'vs average' }]} />
        </div>
        {data.error && <ErrorState error={data.error} onRetry={data.reload} />}
        {data.loading && !data.data && <div className="space-y-2">{Array.from({ length: 10 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>}
        {data.data && <RankTable rows={data.data.rows} sort={sort} order={order} onSort={clickSort} mode={mode} dim={data.loading} />}
      </Card>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <AIPanel title="Gemini Week Outlook" res={ai.data} loading={ai.loading} error={ai.error}>
            {(d) => <RankInsight d={d} />}
          </AIPanel>
        </div>
        <Leaders data={data.data} />
      </div>

    </div>
  )
}

function RankInsight({ d }: { d: RankingsInsight }) {
  return (
    <div className="space-y-3">
      <Headline text={d.headline} />
      <Lead text={d.overview} />
      <ChipRow label="Leaders" items={d.category_specialists} />
      <Sub title="Sleepers" className="text-good"><Bullets dot="bg-good" items={d.sleepers.map((s) => <Emph text={s} />)} /></Sub>
      <More label="Schedule notes">
        <Bullets items={d.schedule_notes.map((s) => <Emph text={s} />)} />
      </More>
    </div>
  )
}

function Leaders({ data }: { data: Rankings | null }) {
  const [cat, setCat] = useState<CatKey>('pts')
  const list = data?.leaders[cat] ?? []
  return (
    <Card className="p-5">
      <SectionTitle kicker="Projected week" title="Category leaders" />
      <div className="mb-3 flex flex-wrap gap-1">
        {CATS.map((c) => (
          <button key={c.key} onClick={() => setCat(c.key)} className={`rounded-md px-2 py-0.5 text-xs ${cat === c.key ? 'bg-brand text-ink' : 'bg-panel-2 text-fg-2 hover:text-fg'}`}>{c.label}</button>
        ))}
      </div>
      {!data && <Skeleton className="h-48" />}
      <div className="space-y-1.5">
        {list.map((l, i) => (
          <Link to={`/compare?a=${l.player_id}`} key={l.player_id} className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-panel-2">
            <span className="w-4 font-display text-muted">{i + 1}</span>
            <Headshot src={l.headshot} name={l.name} size={30} />
            <span className="flex-1 truncate text-sm">{l.name} <span className="text-xs text-muted">{l.team_abbr}</span></span>
            <span className="num font-display text-lg font-semibold">{fmtCat(cat, l.value)}</span>
          </Link>
        ))}
      </div>
      {(cat === 'fg_pct' || cat === 'ft_pct') && <div className="mt-2 text-[10px] text-muted">Min. volume: top 40% of projected attempts.</div>}
    </Card>
  )
}

function RankTable({ rows, sort, order, onSort, mode, dim }: {
  rows: RankingRow[]; sort: SortKey; order: 'asc' | 'desc'; onSort: (k: SortKey) => void; mode: 'total' | 'z'; dim: boolean
}) {
  const nav = useNavigate()
  const maxHi = Math.max(...rows.map((r) => r.value_hi), 1)
  const minLo = Math.min(...rows.map((r) => r.value_lo), -1)
  const span = maxHi - minLo
  const Th = ({ k, label, className = '' }: { k: SortKey; label: string; className?: string }) => (
    <th onClick={() => onSort(k)} className={`cursor-pointer select-none px-2 py-2 text-right font-medium hover:text-fg ${sort === k ? 'text-brand' : ''} ${className}`}>
      <span className="inline-flex items-center gap-0.5">{label}{sort === k && (order === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}</span>
    </th>
  )
  if (rows.length === 0) return <div className="py-10 text-center text-sm text-muted">No players match these filters.</div>
  return (
    <div className={`scrollbar-thin overflow-x-auto transition ${dim ? 'opacity-60' : ''}`}>
      <table className="w-full min-w-[1100px] text-sm">
        <thead className="sticky top-0 bg-panel text-[11px] uppercase tracking-wider text-muted">
          <tr className="border-b border-line">
            <th className="px-2 py-2 text-left font-medium">#</th>
            <th className="px-2 py-2 text-left font-medium">Player</th>
            <Th k="games" label="G" />
            {CATS.map((c) => <Th key={c.key} k={c.key} label={c.label} />)}
            <Th k="value" label="Value" />
            <th className="px-2 py-2 text-left font-medium" title="80% of outcomes land in this range">Likely range</th>
            <Th k="pg_value" label="Per game" />
            <th className="px-2 py-2 text-left font-medium">Strengths</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.player_id} onClick={() => nav(`/compare?a=${r.player_id}`)} className="cursor-pointer border-b border-line-soft hover:bg-panel-2/60">
              <td className="px-2 py-1.5 font-display text-base text-muted">{r.rank}</td>
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-2.5">
                  <Headshot src={r.headshot} name={r.name} size={32} />
                  <div className="min-w-0">
                    <div className="truncate font-medium">{r.name}</div>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted">
                      <TeamLogo src={r.team_logo} abbr={r.team_abbr} size={14} /> {r.team_abbr} · {r.position}
                      {!String(r.status).startsWith('Active') && <StatusChip status={r.status} />}
                    </div>
                  </div>
                </div>
              </td>
              <td className="num px-2 text-right">{r.games}</td>
              {CATS.map((c) => {
                const z = r[`z_${c.key}`] as number
                return (
                  <td key={c.key} className="num px-2 text-right" style={{ background: zTint(z) }} title={`${signed(z, 1)} vs average starter`}>
                    {mode === 'z' ? signed(z, 1) : fmtCat(c.key, r[c.key] as number, c.pct ? 1 : 1)}
                  </td>
                )
              })}
              <td className="num px-2 text-right font-display text-base font-semibold text-brand">{fmt(r.value, 2)}</td>
              <td className="px-2" title={`${fmt(r.value_lo)} to ${fmt(r.value_hi)}`}>
                <div className="relative h-2 w-28 rounded-full bg-line-soft">
                  <div className="absolute h-2 rounded-full bg-pb/50" style={{ left: `${((r.value_lo - minLo) / span) * 100}%`, width: `${((r.value_hi - r.value_lo) / span) * 100}%` }} />
                  <div className="absolute -top-0.5 h-3 w-0.5 rounded bg-fg" style={{ left: `${((r.value - minLo) / span) * 100}%` }} />
                </div>
              </td>
              <td className="num px-2 text-right text-fg-2">{fmt(r.pg_value, 2)}</td>
              <td className="px-2">
                <div className="flex gap-1">
                  {r.strengths.map((s) => <Pill key={s} tone="good">{CAT_LABEL[s]}</Pill>)}
                  {r.weaknesses.slice(0, 1).map((s) => <Pill key={s} tone="bad">{CAT_LABEL[s]}</Pill>)}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-muted">
        <span className="inline-flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: zTint(2) }} /> helps category (z &gt; 0)</span>
        <span className="inline-flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: zTint(-2) }} /> hurts category</span>
        <span>Click a player to open the comparison view.</span>
      </div>
    </div>
  )
}
