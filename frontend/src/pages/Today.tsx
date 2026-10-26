import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CalendarClock, UserPlus } from 'lucide-react'
import { useRosters } from '../components/RosterManager'
import { Card, ErrorState, Headshot, Pill, Segmented, Skeleton, StatusChip, TeamLogo } from '../components/ui'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { useAsync } from '../lib/hooks'
import type { TodayGame, TodayLine, TodayView } from '../lib/types'

type Day = 'auto' | 'today' | 'tomorrow'

export default function TodayPage() {
  const rs = useRosters()
  const [day, setDay] = useState<Day>('auto')
  const res = useAsync(() => api.today(day, rs.selectedId), [day, rs.selectedId], !rs.loading)
  const d = res.data
  const shown: Day = d ? (d.day === 'tomorrow' ? 'tomorrow' : 'today') : day

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-3xl font-bold tracking-wide">{d?.label ?? 'Today'}</h1>
        <Segmented<Day> value={shown} onChange={setDay} options={[{ value: 'today', label: 'Today' }, { value: 'tomorrow', label: 'Tomorrow' }]} />
        {d && <Pill>{d.games.length} games{d.games_left !== d.games.length ? ` · ${d.games_left} left` : ''}</Pill>}
        <div className="ml-auto flex items-center gap-2 text-sm">
          <span className="text-muted">My team</span>
          <select value={rs.selectedId ?? ''} onChange={(e) => rs.setSelectedId(Number(e.target.value))}
            className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm" aria-label="Select my team">
            {rs.rosters.length === 0 && <option value="">None yet</option>}
            {rs.rosters.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
      </div>

      {res.error && <ErrorState error={res.error} onRetry={res.reload} />}
      {!d && !res.error && <Skeleton className="h-96" />}
      {d && (
        <div className={`space-y-5 transition ${res.loading ? 'opacity-60' : ''}`}>
          <Slate games={d.games} />
          {d.games.length === 0 && <Card className="p-8 text-center text-sm text-muted">No NBA games on this day.</Card>}
          <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
            <MyPlayers d={d} />
            <Pickups items={d.pickups} />
          </div>
          <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
            <TopPlayers items={d.top} />
            <Injuries items={d.injuries} />
          </div>
        </div>
      )}
    </div>
  )
}

function Slate({ games }: { games: TodayGame[] }) {
  if (!games.length) return null
  return (
    <div className="scrollbar-thin -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {games.map((g) => (
        <div key={g.game_id} className="card flex min-w-[150px] shrink-0 flex-col gap-1 px-3 py-2">
          <div className="text-[11px] font-semibold text-muted">
            {g.status === 'final' ? 'Final' : g.status === 'live' ? <span className="text-good">Live</span> : g.tip ?? 'TBD'}
          </div>
          {[['away', g.away, g.away_logo, g.away_score], ['home', g.home, g.home_logo, g.home_score]].map(([side, abbr, logo, score]) => (
            <div key={side as string} className="flex items-center gap-2 text-sm">
              <TeamLogo src={logo as string | null} abbr={abbr as string} size={18} />
              <span className="font-medium">{abbr as string}</span>
              {g.status !== 'scheduled' && <span className="num ml-auto font-semibold">{score as number}</span>}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function Box({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="min-w-0 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="truncate font-display text-lg font-semibold tracking-wide">{title}</h2>
        <div className="shrink-0">{right}</div>
      </div>
      {children}
    </Card>
  )
}

const opp = (l: TodayLine) => (l.opponent ? `${l.home ? 'vs' : '@'} ${l.opponent}` : '')

/** Projected stat line: PTS / REB / AST plus the one or two stats the player is best at. */
function StatLine({ l }: { l: TodayLine }) {
  const extras = [['3PM', l.fg3m, 1.5], ['STL', l.stl, 1], ['BLK', l.blk, 1]].filter(([, v, min]) => (v as number) >= (min as number))
  return (
    <span className="num text-sm">
      <b>{fmt(l.pts)}</b> <span className="text-muted">pts</span> · <b>{fmt(l.reb)}</b> <span className="text-muted">reb</span> · <b>{fmt(l.ast)}</b> <span className="text-muted">ast</span>
      {extras.map(([k, v]) => <span key={k as string}> · <b>{fmt(v as number)}</b> <span className="text-muted">{(k as string).toLowerCase()}</span></span>)}
    </span>
  )
}

function PlayerRow({ l, right, rank }: { l: TodayLine; right?: React.ReactNode; rank?: number }) {
  return (
    <Link to={`/compare?a=${l.player_id}`} className="flex min-w-0 items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-panel-2">
      {rank !== undefined && <span className="w-4 text-right font-display text-sm text-muted">{rank}</span>}
      <Headshot src={l.headshot} name={l.name} size={34} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 truncate text-sm font-medium">
          {l.name} <span className="text-xs font-normal text-muted">{l.team} {opp(l)}</span>
          {l.play_chance !== undefined && l.play_chance < 1 && <Pill tone={l.play_chance === 0 ? 'bad' : 'warn'}>{Math.round(l.play_chance * 100)}% to play</Pill>}
          {!l.status.startsWith('Active') && l.play_chance === 1 && <StatusChip status={l.status} />}
        </div>
        <StatLine l={l} />
      </div>
      {right}
    </Link>
  )
}

function MyPlayers({ d }: { d: TodayView }) {
  const m = d.my_team
  if (!m) {
    return (
      <Box title="My players">
        <div className="py-6 text-center text-sm text-fg-2">
          Add your team to see who plays. <Link to="/team" className="text-brand hover:underline">Build my team →</Link>
        </div>
      </Box>
    )
  }
  return (
    <Box title="My players" right={<Pill tone={m.playing.length ? 'good' : 'warn'}>{m.playing.length + m.already_played.length} of {m.size} play</Pill>}>
      {m.playing.length === 0 && m.already_played.length === 0 && <div className="py-4 text-sm text-muted">None of your players play {d.day === 'tomorrow' ? 'tomorrow' : 'today'}.</div>}
      <div className="space-y-0.5">
        {m.playing.map((l) => <PlayerRow key={l.player_id} l={l} />)}
        {m.already_played.map((p) => (
          <div key={p.player_id} className="flex items-center gap-3 px-2 py-1.5 text-sm">
            <Headshot src={p.headshot} name={p.name} size={34} />
            <span className="flex-1 font-medium">{p.name} <Pill tone="good">Final</Pill></span>
            <span className="num"><b>{p.pts}</b> pts · <b>{p.reb}</b> reb · <b>{p.ast}</b> ast</span>
          </div>
        ))}
      </div>
      {m.not_playing.length > 0 && (
        <div className="mt-3 border-t border-line-soft pt-2 text-xs text-muted">
          <span className="font-semibold">Off:</span> {m.not_playing.map((p) => p.name).join(', ')}
        </div>
      )}
    </Box>
  )
}

function Pickups({ items }: { items: TodayLine[] }) {
  return (
    <Box title="Best pickups" right={<Link to="/streaming" className="inline-flex items-center gap-1 text-xs text-brand hover:underline">More <ArrowRight size={12} /></Link>}>
      {items.length === 0 && <div className="py-4 text-sm text-muted">No strong free agents playing.</div>}
      <div className="space-y-0.5">
        {items.slice(0, 5).map((l) => (
          <PlayerRow key={l.player_id} l={l} right={
            <div className="flex shrink-0 gap-1">{(l.helps ?? []).map((h) => <Pill key={h} tone="good">{h}</Pill>)}<UserPlus size={15} className="text-muted" /></div>} />
        ))}
      </div>
      <div className="mt-2 text-[11px] text-muted">Free agents playing this day, outside the top 156 and your saved rosters.</div>
    </Box>
  )
}

function TopPlayers({ items }: { items: TodayLine[] }) {
  return (
    <Box title="Top projected" right={<Link to="/rankings" className="inline-flex items-center gap-1 text-xs text-brand hover:underline">Full rankings <ArrowRight size={12} /></Link>}>
      <div className="space-y-0.5">
        {items.map((l, i) => (
          <PlayerRow key={l.player_id} l={l} rank={i + 1} right={
            <span className="num shrink-0 font-display text-lg font-semibold text-brand" title="Fantasy value: overall 9-category contribution (0 = average starter)">{fmt(l.value)}</span>} />
        ))}
      </div>
    </Box>
  )
}

function Injuries({ items }: { items: TodayView['injuries'] }) {
  return (
    <Box title="Injury watch" right={<CalendarClock size={16} className="text-muted" />}>
      {items.length === 0 && <div className="py-4 text-sm text-muted">No notable injuries on this slate.</div>}
      <div className="space-y-1.5">
        {items.map((i) => (
          <div key={i.player_id} className={`flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm ${i.mine ? 'bg-brand/10' : ''}`} title={i.note}>
            <StatusChip status={i.status === 'Out' ? 'Out' : i.status} />
            <div className="min-w-0">
              <div className="font-medium">{i.name} <span className="text-xs font-normal text-muted">{i.team}{i.mine ? ' · your player' : ''}</span></div>
              {i.return_date && <div className="text-xs text-muted">Back ~{new Date(`${i.return_date}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</div>}
            </div>
          </div>
        ))}
      </div>
    </Box>
  )
}
