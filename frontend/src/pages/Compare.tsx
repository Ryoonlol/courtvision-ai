import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ArrowLeftRight, CalendarDays, ChevronDown, Info, Plane, Home as HomeIcon } from 'lucide-react'
import { AIPanel } from '../components/AIPanel'
import { Bullets, ChipRow, Emph, Headline, Lead, More, Sub } from '../components/Insight'
import { PlayerSearch } from '../components/PlayerSearch'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Segmented, Skeleton, StatusChip, TeamLogo } from '../components/ui'
import { api } from '../lib/api'
import { CATS, CAT_LABEL, fmt, fmtCat, fmtPct, shortDate } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'
import type { CatKey, Comparison, ComparisonInsight, Explain, Profile, ProjectionRow, SeasonLine } from '../lib/types'

const A = '#e5641a'
const B = '#2e9bd6'
const tooltipStyle = { background: '#172033', border: '1px solid #233047', borderRadius: 10, fontSize: 12, color: '#e6eaf2' }

export default function Compare() {
  const { week } = useApp()
  const [params, setParams] = useSearchParams()
  const a = Number(params.get('a')) || null
  const b = Number(params.get('b')) || null

  // default matchup: Jokic vs Wembanyama
  useEffect(() => {
    if (a && b) return
    api.defaultPair().then((p) => setParams({ a: String(a ?? p.a), b: String(b && b !== (a ?? p.a) ? b : p.b) }, { replace: true }))
  }, [a, b, setParams])

  const comp = useAsync(() => api.compare(a!, b!, week), [a, b, week], !!(a && b))
  const ai = useAsync(() => api.compareAI(a!, b!, week), [a, b, week], !!(a && b))

  const setPlayer = (slot: 'a' | 'b', id: number) => {
    const next = { a: String(a ?? ''), b: String(b ?? ''), [slot]: String(id) }
    setParams(next)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Head-to-Head</h1>
          <p className="text-sm text-fg-2">Any two players, side by side.</p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr]">
        <PlayerSearch accent={A} placeholder="Player A — search by name" onSelect={(p) => setPlayer('a', p.id)} />
        <button onClick={() => setParams({ a: String(b), b: String(a) })} className="mx-auto flex h-10 w-10 items-center justify-center rounded-full border border-line text-fg-2 hover:border-brand hover:text-brand" title="Swap players">
          <ArrowLeftRight size={16} />
        </button>
        <PlayerSearch accent={B} placeholder="Player B — search by name" onSelect={(p) => setPlayer('b', p.id)} />
      </div>

      {comp.error && <ErrorState error={comp.error} onRetry={comp.reload} />}
      {(comp.loading || !comp.data) && !comp.error && <CompareSkeleton />}
      {comp.data && !comp.loading && <CompareBody comp={comp.data} ai={ai} />}
    </div>
  )
}

function CompareSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-48" /><Skeleton className="h-48" /></div>
      <Skeleton className="h-80" />
    </div>
  )
}

function CompareBody({ comp, ai }: { comp: Comparison; ai: ReturnType<typeof useAsync<import('../lib/types').AIResponse<ComparisonInsight>>> }) {
  const [pa, pb] = comp.players
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        <PlayerHero p={pa.profile} proj={pa.projection} color={A} wins={comp.summary.weekly_wins_a} />
        <PlayerHero p={pb.profile} proj={pb.projection} color={B} wins={comp.summary.weekly_wins_b} />
      </div>

      <AIPanel title="Gemini Recommendation" res={ai.data} loading={ai.loading} error={ai.error}>
        {(d) => <InsightBody d={d} nameA={pa.profile.name} nameB={pb.profile.name} />}
      </AIPanel>

      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="p-5 xl:col-span-3">
          <SectionTitle kicker={comp.window.label} title="Projected weekly categories"
            right={<Pill>{comp.summary.weekly_wins_a}–{comp.summary.weekly_wins_b}{9 - comp.summary.weekly_wins_a - comp.summary.weekly_wins_b ? `–${9 - comp.summary.weekly_wins_a - comp.summary.weekly_wins_b}` : ''}</Pill>} />
          <Butterfly comp={comp} />
        </Card>
        <Card className="p-5 xl:col-span-2">
          <SectionTitle kicker="Skill profile" title="Category strengths per game" />
          <ZChart comp={comp} />
          <p className="mt-2 text-[11px] text-muted">0 = average fantasy starter; right = better. FG%/FT% weighted by attempts; fewer turnovers counts as better.</p>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="p-5 xl:col-span-3">
          <TrendChart a={pa.profile} b={pb.profile} />
        </Card>
        <Card className="p-5 xl:col-span-2">
          <SectionTitle kicker="Schedule" title="Upcoming games" />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <Upcoming name={pa.profile.name} color={A} explain={pa.explain} />
            <Upcoming name={pb.profile.name} color={B} explain={pb.explain} />
          </div>
        </Card>
      </div>

      <Card className="p-5">
        <SectionTitle kicker="Actual production vs projections" title="Season, last 5 & last 10" />
        <StatsTable comp={comp} />
      </Card>

      <Explainer comp={comp} />
    </>
  )
}

function PlayerHero({ p, proj, color, wins }: { p: Profile; proj: ProjectionRow | null; color: string; wins: number }) {
  return (
    <Card className="court-lines relative overflow-hidden p-5">
      <div className="absolute inset-y-0 left-0 w-1" style={{ background: color }} />
      <div className="flex items-start gap-4">
        <Headshot src={p.headshot} name={p.name} size={84} ring={color} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-display text-2xl font-bold tracking-wide">{p.name}</h2>
            {proj?.rank && <Pill tone="brand">#{proj.rank} this week</Pill>}
          </div>
          <div className="mt-1 flex items-center gap-2 text-sm text-fg-2">
            <TeamLogo src={p.team_logo} abbr={p.team_abbr} /> {p.team_name ?? p.team_abbr} · {p.position}
            <StatusChip status={(proj?.status as string) ?? (p.injury ? p.injury.status : 'Active')} />
          </div>
          {p.injury?.short_comment && <div className="mt-2 line-clamp-2 text-xs text-muted">{p.injury.short_comment}</div>}
        </div>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 2xl:grid-cols-4">
        <MiniStat label="Fantasy value" value={fmt(proj?.value as number)} sub={proj ? `likely ${fmt(proj.value_lo)} to ${fmt(proj.value_hi)}` : undefined} color={color} />
        <MiniStat label="Games" value={proj ? String(proj.games) : '—'} sub={proj ? `exp. ${fmt(proj.exp_games)} played` : undefined} />
        <MiniStat label="Proj MIN" value={fmt(proj?.pg_min as number)} sub="per game" />
        <MiniStat label="Cat wins" value={String(wins)} sub="of 9 this week" color={color} />
      </div>
    </Card>
  )
}

function MiniStat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded-lg border border-line-soft bg-ink/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-2xl font-semibold" style={{ color }}>{value}</div>
      {sub && <div className="text-[10px] text-muted">{sub}</div>}
    </div>
  )
}

function InsightBody({ d, nameA, nameB }: { d: ComparisonInsight; nameA: string; nameB: string }) {
  const colorFor = (n: string) => (n === nameA ? A : n === nameB ? B : '#b4bfd1')
  return (
    <div className="space-y-3">
      <Headline text={d.headline} color={colorFor(d.overall_pick)}>
        <Pill tone={d.confidence === 'high' ? 'good' : d.confidence === 'medium' ? 'brand' : 'warn'}>{d.confidence} confidence</Pill>
      </Headline>
      <Lead text={d.summary} />
      <div className="grid gap-2 sm:grid-cols-3">
        {d.roster_fits.map((f) => (
          <div key={f.need} className="rounded-lg border border-line bg-ink/40 px-3 py-2" title={f.reason}>
            <div className="text-[11px] uppercase tracking-wider text-muted">{f.need}</div>
            <div className="font-semibold" style={{ color: colorFor(f.pick) }}>{f.pick}</div>
          </div>
        ))}
      </div>
      <ChipRow label="Edges" items={d.key_edges} />
      <More>
        <Sub title="Why each pick"><Bullets items={d.roster_fits.map((f) => <><b className="text-fg">{f.need}:</b> <Emph text={f.reason} /></>)} /></Sub>
        <Sub title="Risks" className="text-warn"><Bullets dot="bg-warn" items={d.risks.map((r) => <Emph text={r} />)} /></Sub>
      </More>
    </div>
  )
}

function Butterfly({ comp }: { comp: Comparison }) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-[11px] text-muted">
        <span style={{ color: A }}>{comp.players[0].profile.name}</span>
        <span style={{ color: B }}>{comp.players[1].profile.name}</span>
      </div>
      {comp.categories.map((c) => {
        const va = c.weekly_a ?? 0
        const vb = c.weekly_b ?? 0
        const max = Math.max(va, vb, 1e-9)
        const winA = c.weekly_winner === 'a'
        const winB = c.weekly_winner === 'b'
        return (
          <div key={c.key} className="group grid grid-cols-[64px_1fr_52px_1fr_64px] items-center gap-2" title={`${c.name}${c.higher_is_better ? '' : ' (lower is better)'}`}>
            <div className={`num text-right text-sm ${winA ? 'font-semibold text-fg' : 'text-muted'}`}>{fmtCat(c.key, c.weekly_a)}</div>
            <div className="flex h-5 justify-end">
              <div className="h-full rounded-l-[4px] transition-all group-hover:brightness-125" style={{ width: `${(va / max) * 100}%`, background: A, opacity: winA ? 1 : 0.35 }} />
            </div>
            <div className="text-center font-display text-sm font-semibold tracking-wider text-fg-2">
              {c.label}{!c.higher_is_better && <span className="block text-[9px] font-normal text-muted">lower ✓</span>}
            </div>
            <div className="flex h-5">
              <div className="h-full rounded-r-[4px] transition-all group-hover:brightness-125" style={{ width: `${(vb / max) * 100}%`, background: B, opacity: winB ? 1 : 0.35 }} />
            </div>
            <div className={`num text-sm ${winB ? 'font-semibold text-fg' : 'text-muted'}`}>{fmtCat(c.key, c.weekly_b)}</div>
          </div>
        )
      })}
      <p className="pt-2 text-[11px] text-muted">Weekly totals = per-game projection × scheduled games × availability. Brighter bar wins the category.</p>
    </div>
  )
}

function ZChart({ comp }: { comp: Comparison }) {
  const [pa, pb] = comp.players
  const data = comp.categories.map((c) => ({ cat: c.label, [pa.profile.name]: c.z_a, [pb.profile.name]: c.z_b }))
  return (
    <div className="h-[330px]">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 0, right: 12, top: 4, bottom: 0 }} barGap={2} barCategoryGap="22%">
          <CartesianGrid horizontal={false} stroke="#1b2638" />
          <XAxis type="number" stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="cat" stroke="#b4bfd1" fontSize={11} width={38} tickLine={false} axisLine={false} />
          <ReferenceLine x={0} stroke="#7d8aa2" />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#ffffff08' }} formatter={(v) => (typeof v === 'number' ? v.toFixed(2) : v)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar isAnimationActive={false} dataKey={pa.profile.name} fill={A} radius={[0, 4, 4, 0]} barSize={9} />
          <Bar isAnimationActive={false} dataKey={pb.profile.name} fill={B} radius={[0, 4, 4, 0]} barSize={9} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

const TREND_STATS = [
  { key: 'pts', label: 'PTS' }, { key: 'reb', label: 'REB' }, { key: 'ast', label: 'AST' },
  { key: 'stl', label: 'STL' }, { key: 'blk', label: 'BLK' }, { key: 'fg3m', label: '3PM' }, { key: 'min', label: 'MIN' },
] as const

function TrendChart({ a, b }: { a: Profile; b: Profile }) {
  const [stat, setStat] = useState<(typeof TREND_STATS)[number]['key']>('pts')
  const data = useMemo(() => {
    const la = a.game_log.slice(0, 10).reverse()
    const lb = b.game_log.slice(0, 10).reverse()
    const n = Math.max(la.length, lb.length)
    return Array.from({ length: n }, (_, i) => {
      const ga = la[la.length - n + i]
      const gb = lb[lb.length - n + i]
      return {
        g: i === n - 1 ? 'Last' : `-${n - 1 - i}`,
        [a.name]: ga ? ga[stat] : null,
        [b.name]: gb ? gb[stat] : null,
        da: ga ? `${shortDate(ga.date)} ${ga.home ? 'vs' : '@'} ${ga.opponent}` : '',
        db: gb ? `${shortDate(gb.date)} ${gb.home ? 'vs' : '@'} ${gb.opponent}` : '',
      }
    })
  }, [a, b, stat])
  return (
    <>
      <SectionTitle kicker="Recent form" title="Last 10 games" right={
        <Segmented value={stat} onChange={setStat} options={TREND_STATS.map((s) => ({ value: s.key, label: s.label }))} />
      } />
      <div className="h-[260px]">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ left: -16, right: 12, top: 8 }}>
            <CartesianGrid vertical={false} stroke="#1b2638" />
            <XAxis dataKey="g" stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={tooltipStyle} labelFormatter={(_, p) => {
              const row = p?.[0]?.payload
              return row ? `${a.name.split(' ').pop()}: ${row.da || '—'} · ${b.name.split(' ').pop()}: ${row.db || '—'}` : ''
            }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line isAnimationActive={false} type="monotone" dataKey={a.name} stroke={A} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: '#111826' }} connectNulls />
            <Line isAnimationActive={false} type="monotone" dataKey={b.name} stroke={B} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: '#111826' }} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-muted">Most recent games played (may span the previous season early in the year). Hover for dates and opponents.</p>
    </>
  )
}

function Upcoming({ name, color, explain }: { name: string; color: string; explain: Explain }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm font-medium" style={{ color }}><CalendarDays size={14} /> {name}</div>
      {explain.games.length === 0 && <div className="text-xs text-muted">No remaining games in this window.</div>}
      <div className="space-y-1.5">
        {explain.games.map((g) => (
          <div key={g.date} className="flex items-center gap-2 rounded-lg border border-line-soft bg-ink/30 px-2.5 py-1.5 text-xs">
            <span className="w-14 text-muted">{g.weekday} {shortDate(g.date).split(' ')[1]}</span>
            {g.home ? <HomeIcon size={12} className="text-muted" /> : <Plane size={12} className="text-muted" />}
            <TeamLogo src={g.opponent_logo} abbr={g.opponent} size={18} />
            <span className="w-9 font-medium">{g.opponent}</span>
            <span className="num ml-auto text-fg-2">{fmt(g.projection.pts)} / {fmt(g.projection.reb)} / {fmt(g.projection.ast)}</span>
            {g.rest_days <= 1 && <Pill tone="warn" title="Second night of a back-to-back">B2B</Pill>}
            {g.availability < 1 && <Pill tone={g.availability === 0 ? 'bad' : 'warn'} title={g.availability_note}>{fmtPct(g.availability, 0)}</Pill>}
          </div>
        ))}
      </div>
      {explain.games.length > 0 && <div className="mt-1 text-[10px] text-muted">Projected PTS / REB / AST per game</div>}
    </div>
  )
}

function StatsTable({ comp }: { comp: Comparison }) {
  const { week } = useApp()
  const ids = comp.players.map((p) => p.profile.id)
  const gem = useAsync(() => api.forecastPlayers(week, ids), [week, ids.join(',')])
  const cols = ['games', 'min', ...CATS.map((c) => c.key)] as const
  const head = ['GP', 'MIN', ...CATS.map((c) => c.label)]
  const rowsFor = (p: Profile, proj: ProjectionRow | null) => {
    const r: { label: string; line: Partial<SeasonLine> | null; projected?: boolean; gemini?: boolean }[] = []
    Object.entries(p.seasons).forEach(([season, line]) => r.push({ label: season, line }))
    r.push({ label: 'Last 10', line: p.last10 }, { label: 'Last 5', line: p.last5 })
    if (proj) {
      const pg: Partial<SeasonLine> = {
        games: proj.games, min: proj.pg_min as number, pts: proj.pg_pts as number, reb: proj.pg_reb as number,
        ast: proj.pg_ast as number, stl: proj.pg_stl as number, blk: proj.pg_blk as number, fg3m: proj.pg_fg3m as number,
        tov: proj.pg_tov as number,
        fg_pct: (proj.pg_fgm as number) / (proj.pg_fga as number), ft_pct: (proj.pg_ftm as number) / (proj.pg_fta as number),
      }
      r.push({ label: 'Baseline / game', line: pg, projected: true })
    }
    const g = gem.data?.rows.find((x) => x.player_id === p.id)
    if (g) {
      const games = g.gemini_expected_games || 1
      const per = (k: CatKey) => (g.categories[k].gemini ?? 0) / games
      r.push({ label: 'Gemini forecast / game', gemini: true, line: {
        games: Math.round(g.gemini_expected_games * 10) / 10, min: g.gemini_min,
        pts: per('pts'), reb: per('reb'), ast: per('ast'), stl: per('stl'), blk: per('blk'), fg3m: per('fg3m'), tov: per('tov'),
        fg_pct: g.categories.fg_pct.gemini, ft_pct: g.categories.ft_pct.gemini,
      } })
    }
    return r
  }
  return (
    <div className="scrollbar-thin overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-line text-[11px] uppercase tracking-wider text-muted">
            <th className="py-2 text-left font-medium">Split</th>
            {head.map((h) => <th key={h} className="py-2 text-right font-medium">{h}</th>)}
          </tr>
        </thead>
        {comp.players.map((pl, idx) => (
          <tbody key={pl.profile.id}>
            <tr><td colSpan={12} className="pt-4 pb-1 text-xs font-semibold" style={{ color: idx === 0 ? A : B }}>{pl.profile.name}</td></tr>
            {rowsFor(pl.profile, pl.projection).map((r) => (
              <tr key={r.label} className={`border-b border-line-soft ${r.projected ? 'text-brand' : ''} ${r.gemini ? 'text-gemini' : ''}`}>
                <td className="py-1.5 text-fg-2">{r.label}</td>
                {cols.map((k) => (
                  <td key={k} className="num py-1.5 text-right">
                    {r.line ? (k === 'games' ? (r.line.games ?? '—') : fmtCat(k, r.line[k as keyof SeasonLine] as number)) : '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
      <p className="mt-2 text-[11px] text-muted">“Baseline / game” is the statistical model's weighted-average state (before opponent and availability adjustments). “Gemini forecast / game” appears once a Gemini forecast has been generated for this window (Gemini Forecast page); its GP column is Gemini's expected games.</p>
    </div>
  )
}

function Explainer({ comp }: { comp: Comparison }) {
  const [open, setOpen] = useState(false)
  const stats = ['min', 'pts', 'reb', 'ast', 'stl', 'blk', 'fg3m', 'tov', 'fga', 'fta'] as const
  return (
    <Card className="p-5">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between text-left">
        <div className="flex items-center gap-2">
          <Info size={16} className="text-brand" />
          <span className="font-display text-lg font-semibold tracking-wide">How these projections were built</span>
        </div>
        <ChevronDown size={18} className={`text-muted transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="mt-4 grid gap-6 lg:grid-cols-2">
          {comp.players.map((pl, i) => (
            <div key={pl.profile.id}>
              <div className="mb-2 text-sm font-semibold" style={{ color: i === 0 ? A : B }}>
                {pl.profile.name} · {pl.explain.games_this_season ?? 0} games this season, {pl.explain.prior_season_games ?? 0} in prior two
              </div>
              <table className="w-full text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-muted">
                  <tr><th className="text-left">Stat</th><th className="text-right">Season</th><th className="text-right">Prior</th><th className="text-right">Blend</th><th className="text-right">L10</th><th className="text-right">L5</th><th className="text-right">Baseline</th><th className="text-right">Method</th></tr>
                </thead>
                <tbody>
                  {stats.map((s) => {
                    const c = pl.explain.components?.[s]
                    if (!c) return null
                    return (
                      <tr key={s} className="border-b border-line-soft">
                        <td className="py-1 text-fg-2">{CAT_LABEL[s] ?? s.toUpperCase()}</td>
                        <td className="num text-right">{fmt(c.current_season_avg)}</td>
                        <td className="num text-right">{fmt(c.prior_two_season_avg)}</td>
                        <td className="num text-right">{fmt(c.season_blend)}</td>
                        <td className="num text-right">{fmt(c.last10)}</td>
                        <td className="num text-right">{fmt(c.last5)}</td>
                        <td className="num text-right text-brand">{fmt(c.weighted_baseline)}</td>
                        <td className="text-right text-[10px] text-muted">{c.method.startsWith('ml') ? 'ML' : 'Weighted'}{c.method.includes('%') ? ' ×%' : ''}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ))}
          <p className="text-xs text-muted lg:col-span-2">
            Baseline = 50% season blend (current season shrunk toward the prior two seasons) + 30% last-10 + 20% last-5, then scaled by
            opponent strength. Where the gradient-boosted model beat this baseline on chronological validation it is used instead (see Model Lab).
            Makes = projected attempts × season-blended FG%/FT%.
          </p>
        </div>
      )}
    </Card>
  )
}
