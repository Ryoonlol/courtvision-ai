import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AIPanel } from '../components/AIPanel'
import { Bullets, ChipRow, Emph, Headline, Lead, More, Sub } from '../components/Insight'
import { tooltipStyle } from '../components/Category'
import { OpponentPicker, RosterBar, useOpponent, useRosters } from '../components/RosterManager'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Skeleton, StatusChip } from '../components/ui'
import { api, type MatchupRequest } from '../lib/api'
import { CAT_LABEL, fmt, fmtCat, fmtPct } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'
import type { MatchupInsight, MatchupResult, SimCategory, SimTeam } from '../lib/types'

export const A = '#e5641a'
export const B = '#2e9bd6'

export default function MatchupPage() {
  const { week } = useApp()
  const rs = useRosters()
  const opp = useOpponent(rs.rosters, rs.selectedId)
  const req: MatchupRequest | null = rs.selected?.player_ids.length && opp.opponent?.player_ids.length
    ? { roster_player_ids: rs.selected.player_ids, opponent_player_ids: opp.opponent.player_ids, week, sims: 10000 } : null
  const key = JSON.stringify(req)
  const sim = useAsync(() => api.simulate(req!), [key], !!req)
  const ai = useAsync(() => api.matchupAI(req!), [key], !!req)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Matchup Simulator</h1>
          <p className="text-sm text-fg-2 cursor-help" title="10,000 simulated weeks using projections, game-to-game variance and injury odds.">Your odds to win this week's matchup. ⓘ</p>
        </div>
      </div>
      <Card className="flex flex-wrap items-center gap-3 p-3">
        <RosterBar state={rs} />
        <OpponentPicker state={rs} opp={opp} />
      </Card>
      {rs.error && <div className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{rs.error}</div>}
      {!req && !rs.loading && <Card className="p-8 text-center text-sm text-fg-2">Select your roster and an opponent (use “Sample opponent” to draft one).</Card>}
      {sim.error && <ErrorState error={sim.error} onRetry={sim.reload} />}
      {req && sim.loading && !sim.data && <Skeleton className="h-80" />}
      {req && sim.data && <MatchupBody r={sim.data} mine={rs.selected!.name} theirs={opp.opponent!.name} dim={sim.loading} />}
      {req && (
        <AIPanel title="Gemini Matchup Analysis" res={ai.data} loading={ai.loading} error={ai.error}>
          {(d) => <MatchupInsightBody d={d} />}
        </AIPanel>
      )}
    </div>
  )
}

function MatchupBody({ r, mine, theirs, dim }: { r: MatchupResult; mine: string; theirs: string; dim: boolean }) {
  return (
    <div className={`space-y-4 transition ${dim ? 'opacity-60' : ''}`}>
      <WinHero r={r} mine={mine} theirs={theirs} />
      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="p-5 xl:col-span-3">
          <SectionTitle kicker={r.window.label} title="Category win probability" right={
            <div className="flex flex-wrap gap-1">{r.swing.map((k) => <Pill key={k} tone="warn">swing {CAT_LABEL[k]}</Pill>)}</div>} />
          <CategoryBars cats={r.categories} />
        </Card>
        <Card className="p-5 xl:col-span-2">
          <SectionTitle kicker="Distribution" title="Categories won" />
          <CatsWonChart dist={r.cats_won_distribution} />
          <p className="text-[11px] text-muted">Share of simulations by number of categories you win. 5+ (orange) wins the week outright.</p>
        </Card>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <RosterCard title={mine} team={r.team_a} color={A} />
        <RosterCard title={theirs} team={r.team_b} color={B} />
      </div>
    </div>
  )
}

export function WinHero({ r, mine, theirs }: { r: { p_win: number; p_tie: number; p_loss: number; p_win_se: number; expected_cats_won: number; p_at_least_5: number; sims?: number }; mine: string; theirs: string }) {
  return (
    <Card className="court-lines p-6">
      <div className="flex flex-wrap items-end gap-8">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-muted">Win probability</div>
          <div className="num font-display text-6xl font-bold" style={{ color: r.p_win >= 0.5 ? '#34c38f' : '#ef5b5b' }}>{fmtPct(r.p_win, 1)}</div>
          <div className="text-xs text-muted">±{fmtPct(r.p_win_se * 1.96, 1)} (95% MC error){r.sims ? ` · ${r.sims.toLocaleString()} sims` : ''}</div>
        </div>
        <Big label="Expected categories won" value={fmt(r.expected_cats_won, 2)} sub="of 9" />
        <Big label="Win 5+ categories" value={fmtPct(r.p_at_least_5, 0)} />
        <Big label="Tie / loss" value={`${fmtPct(r.p_tie, 0)} / ${fmtPct(r.p_loss, 0)}`} />
      </div>
      <div className="mt-5">
        <div className="mb-1 flex justify-between text-xs"><span style={{ color: A }}>{mine}</span><span style={{ color: B }}>{theirs}</span></div>
        <div className="flex h-3 overflow-hidden rounded-full bg-line-soft" role="img" aria-label={`Win ${fmtPct(r.p_win)}, tie ${fmtPct(r.p_tie)}, loss ${fmtPct(r.p_loss)}`}>
          <div style={{ width: `${r.p_win * 100}%`, background: A }} />
          <div style={{ width: `${r.p_tie * 100}%`, background: '#7d8aa2' }} />
          <div style={{ width: `${r.p_loss * 100}%`, background: B }} />
        </div>
      </div>
    </Card>
  )
}

function Big({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-3xl font-semibold">{value} {sub && <span className="text-base text-muted">{sub}</span>}</div>
    </div>
  )
}

export function CategoryBars({ cats }: { cats: SimCategory[] }) {
  return (
    <div className="space-y-2.5">
      {cats.map((c) => (
        <div key={c.key} className="grid grid-cols-[44px_1fr_110px] items-center gap-3 sm:grid-cols-[44px_120px_1fr_120px]">
          <div className="font-display text-sm font-semibold tracking-wider">{c.label}</div>
          <div className="num hidden text-right text-xs text-fg-2 sm:block" title={`80% range ${fmtCat(c.key, c.p10_a)} – ${fmtCat(c.key, c.p90_a)}`}>{fmtCat(c.key, c.mean_a)}</div>
          <div className="relative flex h-6 overflow-hidden rounded-md bg-line-soft" title={`Win ${fmtPct(c.p_win)} · tie ${fmtPct(c.p_tie)} · loss ${fmtPct(c.p_loss)}`}>
            <div className="flex items-center justify-start pl-1.5 text-[11px] font-semibold text-ink" style={{ width: `${c.p_win * 100}%`, background: A }}>{c.p_win >= 0.12 ? fmtPct(c.p_win, 0) : ''}</div>
            <div style={{ width: `${c.p_tie * 100}%`, background: '#7d8aa2' }} />
            <div className="flex flex-1 items-center justify-end pr-1.5 text-[11px] font-semibold text-ink" style={{ background: B }}>{c.p_loss >= 0.12 ? fmtPct(c.p_loss, 0) : ''}</div>
          </div>
          <div className="num text-right text-xs text-fg-2" title={`80% range ${fmtCat(c.key, c.p10_b)} – ${fmtCat(c.key, c.p90_b)}`}>
            <span className="sm:hidden">{fmtCat(c.key, c.mean_a)} vs </span>{fmtCat(c.key, c.mean_b)}
          </div>
        </div>
      ))}
      <div className="grid grid-cols-[44px_1fr_110px] gap-3 text-[10px] text-muted sm:grid-cols-[44px_120px_1fr_120px]">
        <span /><span className="hidden text-right sm:block">your avg</span><span className="text-center">win · tie · loss</span><span className="text-right">their avg</span>
      </div>
    </div>
  )
}

function CatsWonChart({ dist }: { dist: number[] }) {
  const data = dist.map((p, k) => ({ k: String(k), p: +(p * 100).toFixed(1) }))
  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ left: -20, right: 6, top: 8 }}>
          <CartesianGrid vertical={false} stroke="#1b2638" />
          <XAxis dataKey="k" stroke="#b4bfd1" fontSize={11} tickLine={false} axisLine={false} />
          <YAxis stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} unit="%" />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#ffffff08' }} formatter={(v) => [`${v}%`, 'of simulations']} labelFormatter={(l) => `${l} categories won`} />
          <Bar isAnimationActive={false} dataKey="p" radius={[4, 4, 0, 0]} barSize={22}>
            {data.map((d) => <Cell key={d.k} fill={Number(d.k) >= 5 ? A : '#3a4a66'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function RosterCard({ title, team, color }: { title: string; team: SimTeam; color: string }) {
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-medium" style={{ color }}>{title}</div>
        <div className="flex gap-1">
          {!!team.banked?.games && <Pill tone="brand" title="Actual stats already played this week are included in every simulation">{team.banked.games} played · {fmt(team.banked.pts, 0)} pts banked</Pill>}
          <Pill>{team.games} remaining · {fmt(team.expected_games)} expected</Pill>
        </div>
      </div>
      <div className="grid gap-1 sm:grid-cols-2">
        {team.players.map((p) => (
          <div key={p.player_id} className="flex items-center gap-2 text-sm">
            <Headshot src={p.headshot} name={p.name} size={24} />
            <span className="flex-1 truncate">{p.name}</span>
            {!p.status.startsWith('Active') && <StatusChip status={p.status} />}
            <span className="num text-xs text-muted">{p.games}G</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function MatchupInsightBody({ d }: { d: MatchupInsight }) {
  return (
    <div className="space-y-3">
      <Headline text={d.headline} />
      <Lead text={d.outlook} />
      <ChipRow label="Secure" items={d.secure} tone="good" labelClass="text-good" />
      <ChipRow label="Swing" items={d.swing} tone="warn" labelClass="text-warn" />
      <ChipRow label="Concede" items={d.concede} tone="bad" labelClass="text-bad" />
      <Sub title="Do this" className="text-brand"><Bullets dot="bg-brand" items={d.actions.slice(0, 2).map((a) => <Emph text={a} />)} /></Sub>
      {d.actions.length > 2 && <More label="More actions"><Bullets items={d.actions.slice(2).map((a) => <Emph text={a} />)} /></More>}
    </div>
  )
}

