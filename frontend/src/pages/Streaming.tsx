import { useEffect, useState } from 'react'
import { ListPlus, X } from 'lucide-react'
import { PuntPicker } from '../components/Category'
import { PlayerSearch } from '../components/PlayerSearch'
import { RosterBar, useRosters } from '../components/RosterManager'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Segmented, Skeleton, StatusChip } from '../components/ui'
import { api } from '../lib/api'
import { CAT_LABEL, fmt, signed } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'
import type { CatKey, PlayerHit, StreamDay, StreamResult } from '../lib/types'

type Mode = 'auto' | 'custom'

function loadWaivers(rosterId: number | null): PlayerHit[] {
  try { return JSON.parse(localStorage.getItem(`cv-waivers-${rosterId}`) ?? '[]') } catch { return [] }
}

export default function StreamingPage() {
  const { week } = useApp()
  const rs = useRosters()
  const [slots, setSlots] = useState(10)
  const [mode, setMode] = useState<Mode>('auto')
  const [punt, setPunt] = useState<CatKey[]>([])
  const [waivers, setWaivers] = useState<PlayerHit[]>([])
  const roster = rs.selected

  useEffect(() => { setWaivers(loadWaivers(rs.selectedId)) }, [rs.selectedId])
  const saveWaivers = (list: PlayerHit[]) => {
    setWaivers(list)
    try { localStorage.setItem(`cv-waivers-${rs.selectedId}`, JSON.stringify(list)) } catch { /* storage unavailable */ }
  }

  const body = roster?.player_ids.length ? {
    roster_player_ids: roster.player_ids, roster_id: roster.id, week, slots, punt,
    available_ids: mode === 'custom' ? waivers.map((w) => w.id) : null,
  } : null
  const enabled = !!body && (mode === 'auto' || waivers.length > 0)
  const res = useAsync(() => api.streaming(body!), [JSON.stringify(body)], enabled)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Streaming</h1>
          <p className="text-sm text-fg-2">Best pickups for your open lineup spots.</p>
        </div>
        <RosterBar state={rs} />
      </div>

      <Card className="flex flex-wrap items-center gap-4 p-3">
        <label className="flex items-center gap-2 text-sm text-fg-2">
          Active slots/day
          <select value={slots} onChange={(e) => setSlots(Number(e.target.value))} className="rounded-lg border border-line bg-panel px-2 py-1 text-sm">
            {[6, 7, 8, 9, 10, 11, 12, 13].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <Segmented<Mode> value={mode} onChange={setMode} options={[{ value: 'auto', label: 'Auto free agents' }, { value: 'custom', label: `My waiver list (${waivers.length})` }]} />
        <PuntPicker value={punt} onChange={setPunt} />
      </Card>

      {mode === 'custom' && (
        <Card className="p-4">
          <SectionTitle kicker="Designate who is actually available in your league" title="Waiver wire" right={<ListPlus size={16} className="text-brand" />} />
          <div className="max-w-md"><PlayerSearch placeholder="Add an available player…" onSelect={(p) => {
            if (!waivers.some((w) => w.id === p.id) && !roster?.player_ids.includes(p.id)) saveWaivers([...waivers, p])
          }} /></div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {waivers.length === 0 && <span className="text-xs text-muted">Add players that are on your league's waiver wire. Saved in this browser per roster.</span>}
            {waivers.map((w) => (
              <span key={w.id} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel-2 py-0.5 pl-1 pr-2 text-xs">
                <Headshot src={w.headshot} name={w.name} size={18} /> {w.name}
                <button onClick={() => saveWaivers(waivers.filter((x) => x.id !== w.id))} className="text-muted hover:text-bad" aria-label={`Remove ${w.name}`}><X size={12} /></button>
              </span>
            ))}
          </div>
        </Card>
      )}

      {!roster && !rs.loading && <Card className="p-8 text-center text-sm text-fg-2">Create or select a roster first.</Card>}
      {res.error && <ErrorState error={res.error} onRetry={res.reload} />}
      {enabled && res.loading && !res.data && <Skeleton className="h-80" />}
      {enabled && res.data && <StreamBody r={res.data} dim={res.loading} />}
    </div>
  )
}

function StreamBody({ r, dim }: { r: StreamResult; dim: boolean }) {
  return (
    <div className={`space-y-4 transition ${dim ? 'opacity-60' : ''}`}>
      <Card className="p-5">
        <SectionTitle kicker={`${r.slots} active slots`} title="Your week, day by day" />
        <div className="grid grid-cols-7 gap-2">
          {r.days.map((d) => <DayCell key={d.date} d={d} slots={r.slots} />)}
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-[11px] text-muted">
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-good" /> open slots — streamer games count</span>
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-bad" /> lineup full — a streamer would sit</span>
          <span>Positional eligibility is not modelled; slots are treated as generic.</span>
        </div>
      </Card>

      <Card className="p-5">
        <SectionTitle kicker={`${r.mode === 'auto' ? 'Auto: free agents outside the top 156 & your saved rosters' : 'Your waiver list'} · ${r.pool_size} considered`}
          title="Best streamers" right={r.drop_candidate && <Pill tone="bad">Suggested drop: {r.drop_candidate.name}</Pill>} />
        {r.candidates.length === 0 && <div className="py-6 text-center text-sm text-muted">No candidates with games in this window.</div>}
        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line">
                <th className="py-1.5 text-left font-medium">Player</th><th className="text-left font-medium">Games</th>
                <th className="text-right font-medium">Usable</th><th className="text-right font-medium">Proj MIN</th>
                <th className="text-right font-medium">Stream value</th><th className="pl-3 text-left font-medium">Helps</th>
              </tr>
            </thead>
            <tbody>
              {r.candidates.map((c) => (
                <tr key={c.player_id} className="border-b border-line-soft">
                  <td className="py-1.5">
                    <div className="flex items-center gap-2"><Headshot src={c.headshot} name={c.name} size={28} />
                      <div><div className="flex items-center gap-1.5">{c.name} {!c.status.startsWith('Active') && <StatusChip status={c.status} />}</div>
                        <div className="text-[11px] text-muted">{c.team_abbr} · {c.position}</div></div></div>
                  </td>
                  <td>
                    <div className="flex gap-1">
                      {c.days.map((d) => (
                        <span key={d.date} title={`${d.weekday}: ${d.usable >= 1 ? 'open slot' : d.usable > 0 ? 'partly open' : 'lineup full'}${d.availability < 1 ? ` · ${Math.round(d.availability * 100)}% to play` : ''}`}
                          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${d.usable >= 1 ? 'bg-good/20 text-good' : d.usable > 0 ? 'bg-warn/20 text-warn' : 'bg-bad/15 text-bad line-through'}`}>{d.weekday}</span>
                      ))}
                    </div>
                  </td>
                  <td className="num text-right">{fmt(c.usable_games)}<span className="text-muted">/{c.games}</span></td>
                  <td className="num text-right text-fg-2">{fmt(c.proj_min)}</td>
                  <td className="num text-right font-display text-base font-semibold text-brand">{fmt(c.stream_value, 2)}</td>
                  <td className="pl-3"><div className="flex gap-1">{c.helps.map((k) => <Pill key={k} tone="good">{CAT_LABEL[k]} {signed(c.category_gain[k])}</Pill>)}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-muted">Stream value = how much the usable games help your team, weighted toward your weak categories.</p>
      </Card>
    </div>
  )
}

function DayCell({ d, slots }: { d: StreamDay; slots: number }) {
  const full = d.open_slots < 0.5
  const fill = Math.min(d.my_players / slots, 1)
  return (
    <div className={`rounded-xl border p-2.5 text-center ${full ? 'border-bad/40 bg-bad/5' : 'border-good/40 bg-good/5'}`}>
      <div className="text-[11px] uppercase tracking-wider text-muted">{d.weekday}</div>
      <div className="num font-display text-2xl font-semibold">{d.league_games}</div>
      <div className="text-[10px] text-muted">NBA games</div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line-soft"><div className="h-full rounded-full" style={{ width: `${fill * 100}%`, background: full ? '#ef5b5b' : '#34c38f' }} /></div>
      <div className="mt-1 text-[10px] text-fg-2">{fmt(d.my_players)} of {slots} used</div>
      <div className={`text-[11px] font-semibold ${full ? 'text-bad' : 'text-good'}`}>{full ? 'full' : `${fmt(d.open_slots)} open`}</div>
    </div>
  )
}
