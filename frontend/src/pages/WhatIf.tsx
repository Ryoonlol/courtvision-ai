import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, Crosshair, HeartPulse, RotateCcw, UserMinus, X } from 'lucide-react'
import { PuntPicker, tooltipStyle } from '../components/Category'
import { PlayerSearch } from '../components/PlayerSearch'
import { OpponentPicker, RosterBar, useOpponent, useRosters } from '../components/RosterManager'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { CATS, fmt, fmtCat, fmtPct, signed } from '../lib/format'
import { useApp, useAsync, useDebounced } from '../lib/hooks'
import type { CatKey, PlayerHit, SuggestResult, WhatIfResult } from '../lib/types'
import { A } from './Matchup'

export default function WhatIfPage() {
  const { week } = useApp()
  const rs = useRosters()
  const opp = useOpponent(rs.rosters, rs.selectedId)
  const roster = rs.selected?.player_ids ?? []
  const [drop, setDrop] = useState<number[]>([])
  const [out, setOut] = useState<number[]>([])
  const [add, setAdd] = useState<PlayerHit[]>([])
  const [priority, setPriority] = useState<CatKey[]>(['stl'])
  const [punt, setPunt] = useState<CatKey[]>([])
  const [suggest, setSuggest] = useState<SuggestResult | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestErr, setSuggestErr] = useState<string | null>(null)

  useEffect(() => { setDrop([]); setOut([]); setAdd([]); setSuggest(null) }, [rs.selectedId, opp.opponent?.id])

  // names for roster rows come from a quick team analysis call (same projections)
  const team = useAsync(() => api.analyzeTeam({ player_ids: roster, week, basis: 'week', punt: [] }),
    [roster.join(','), week], roster.length > 0)

  const body = useMemo(() => (roster.length && opp.opponent?.player_ids.length ? {
    roster_player_ids: roster, opponent_player_ids: opp.opponent.player_ids, week,
    add: add.map((p) => p.id), drop, out, sims: 8000,
  } : null), [roster, opp.opponent, week, add, drop, out])
  const key = useDebounced(JSON.stringify(body), 350)
  const res = useAsync(() => api.whatif(JSON.parse(key)), [key], !!body && key !== 'null')
  const changed = drop.length + out.length + add.length > 0

  const toggle = (list: number[], set: (v: number[]) => void, id: number) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])

  const findMoves = async () => {
    if (!body) return
    setSuggesting(true)
    setSuggestErr(null)
    try {
      setSuggest(await api.suggest({ roster_player_ids: roster, opponent_player_ids: body.opponent_player_ids, week, priority, punt, roster_id: rs.selectedId }))
    } catch (e) {
      setSuggestErr((e as Error).message)
    } finally {
      setSuggesting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-bold tracking-wide">What-If Lab</h1>
        <p className="text-sm text-fg-2">Change your lineup, see your new odds.</p>
      </div>
      <Card className="flex flex-wrap items-center gap-3 p-3">
        <RosterBar state={rs} />
        <OpponentPicker state={rs} opp={opp} />
      </Card>
      {!body && !rs.loading && <Card className="p-8 text-center text-sm text-fg-2">Select your roster and an opponent to start.</Card>}

      {body && (
        <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
          <Card className="h-fit p-4">
            <SectionTitle kicker="Scenario" title="Roster changes" right={changed && (
              <button onClick={() => { setDrop([]); setOut([]); setAdd([]) }} className="inline-flex items-center gap-1 text-xs text-muted hover:text-brand"><RotateCcw size={12} /> Reset</button>)} />
            <div className="space-y-1">
              {team.loading && !team.data && <Skeleton className="h-60" />}
              {team.data?.roster.map((p) => {
                const isDrop = drop.includes(p.player_id)
                const isOut = out.includes(p.player_id)
                return (
                  <div key={p.player_id} className={`flex items-center gap-2 rounded-lg px-2 py-1.5 ${isDrop ? 'bg-bad/10 opacity-60' : isOut ? 'bg-warn/10' : ''}`}>
                    <Headshot src={p.headshot} name={p.name} size={26} />
                    <span className={`min-w-0 flex-1 truncate text-sm ${isDrop ? 'line-through' : ''}`}>{p.name} <span className="text-[11px] text-muted">{p.games}G</span></span>
                    <button onClick={() => toggle(out, setOut, p.player_id)} disabled={isDrop} title="Mark injured / out this week"
                      className={`rounded p-1 ${isOut ? 'text-warn' : 'text-muted hover:text-warn'}`} aria-pressed={isOut}><HeartPulse size={15} /></button>
                    <button onClick={() => toggle(drop, setDrop, p.player_id)} title="Drop player"
                      className={`rounded p-1 ${isDrop ? 'text-bad' : 'text-muted hover:text-bad'}`} aria-pressed={isDrop}><UserMinus size={15} /></button>
                  </div>
                )
              })}
            </div>
            <div className="mt-3 border-t border-line-soft pt-3">
              <div className="mb-1.5 text-[11px] uppercase tracking-wider text-muted">Add players</div>
              <PlayerSearch placeholder="Add a free agent or trade target…" onSelect={(p) => {
                if (!roster.includes(p.id) && !add.some((x) => x.id === p.id) && add.length < 5) setAdd([...add, p])
              }} />
              <div className="mt-2 flex flex-wrap gap-1.5">
                {add.map((p) => (
                  <span key={p.id} className="inline-flex items-center gap-1 rounded-full border border-good/40 bg-good/10 px-2 py-0.5 text-xs text-good">
                    + {p.name}<button onClick={() => setAdd(add.filter((x) => x.id !== p.id))} aria-label={`Remove ${p.name}`}><X size={12} /></button>
                  </span>
                ))}
              </div>
            </div>
          </Card>

          <div className="min-w-0 space-y-4">
            {res.error && <ErrorState error={res.error} onRetry={res.reload} />}
            {!res.data && res.loading && <Skeleton className="h-64" />}
            {res.data && <ScenarioView r={res.data} dim={res.loading} changed={changed} />}

            <Card className="p-5">
              <SectionTitle kicker="Prioritize categories" title="Find the best swap" right={<Crosshair size={16} className="text-brand" />} />
              <div className="mb-3 flex flex-wrap items-center gap-1">
                <span className="mr-1 text-[11px] uppercase tracking-wider text-muted">Priority</span>
                {CATS.map((c) => {
                  const on = priority.includes(c.key)
                  return (
                    <button key={c.key} onClick={() => setPriority(on ? priority.filter((k) => k !== c.key) : priority.length < 4 ? [...priority, c.key] : priority)}
                      className={`rounded-md border px-2 py-0.5 text-xs ${on ? 'border-brand bg-brand/15 text-brand' : 'border-line text-fg-2 hover:text-fg'}`}>{c.label}</button>
                  )
                })}
              </div>
              <div className="mb-3"><PuntPicker value={punt} onChange={setPunt} /></div>
              <button onClick={findMoves} disabled={suggesting || priority.length === 0}
                className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-ink disabled:opacity-50">{suggesting ? 'Simulating swaps…' : 'Find moves'}</button>
              {suggestErr && <div className="mt-2 text-sm text-bad">{suggestErr}</div>}
              {suggest && (
                <div className="mt-4">
                  <div className="mb-2 text-xs text-muted">
                    Current odds in {suggest.priority.map((k) => `${CATS.find((c) => c.key === k)?.label} ${fmtPct(suggest.base_priority_p[k], 0)}`).join(', ')} ·
                    each swap verified with {suggest.sims_per_candidate.toLocaleString()} simulations
                  </div>
                  <div className="scrollbar-thin overflow-x-auto">
                    <table className="w-full min-w-[600px] text-sm">
                      <thead className="text-[11px] uppercase tracking-wider text-muted">
                        <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Move</th><th className="text-right font-medium">Priority Δ</th><th className="text-right font-medium">Win prob Δ</th><th className="text-right font-medium">Exp. cats Δ</th><th /></tr>
                      </thead>
                      <tbody>
                        {suggest.moves.map((m) => (
                          <tr key={m.player_id} className="border-b border-line-soft">
                            <td className="py-1.5">
                              <div className="flex items-center gap-2"><Headshot src={m.headshot} name={m.name} size={26} />
                                <span>Add <b>{m.name}</b> <span className="text-muted">({m.games}G)</span> <ArrowRight size={11} className="inline text-muted" /> drop {m.drop_name}</span></div>
                            </td>
                            <td className={`num text-right font-semibold ${m.priority_gain > 0 ? 'text-good' : 'text-bad'}`}>{signed(m.priority_gain * 100, 1)} pts</td>
                            <td className={`num text-right ${m.delta_p_win >= 0 ? 'text-good' : 'text-bad'}`}>{signed(m.delta_p_win * 100, 1)} pts</td>
                            <td className="num text-right text-fg-2">{signed(m.delta_expected_cats, 2)}</td>
                            <td className="text-right">
                              <button onClick={() => {
                                setAdd([{ id: m.player_id, name: m.name, team_abbr: m.team_abbr, position: null, headshot: m.headshot, rank: null }])
                                setDrop([m.drop_player_id]); setOut([])
                              }} className="rounded-md border border-line px-2 py-1 text-xs text-fg-2 hover:border-brand hover:text-brand">Try it</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-2 text-[11px] text-muted">Priority Δ = average change in win probability across the priority categories (percentage points).</p>
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

function ScenarioView({ r, dim, changed }: { r: WhatIfResult; dim: boolean; changed: boolean }) {
  const data = r.categories.map((c) => ({ cat: c.label, Before: +(c.p_before * 100).toFixed(1), After: +(c.p_after * 100).toFixed(1) }))
  const d = r.delta_p_win
  return (
    <div className={`space-y-4 transition ${dim ? 'opacity-60' : ''}`}>
      <Card className="court-lines p-6">
        <div className="flex flex-wrap items-center gap-8">
          <Stat label="Before" value={fmtPct(r.before.p_win, 1)} sub={`${fmt(r.before.expected_cats_won, 2)} cats · ${r.before.games} games`} />
          <ArrowRight className="text-muted" />
          <Stat label="After" value={fmtPct(r.after.p_win, 1)} sub={`${fmt(r.after.expected_cats_won, 2)} cats · ${r.after.games} games`} color={d >= 0 ? '#34c38f' : '#ef5b5b'} />
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted">Change</div>
            <div className="num font-display text-3xl font-semibold" style={{ color: d >= 0 ? '#34c38f' : '#ef5b5b' }}>{signed(d * 100, 1)} pts</div>
            <div className="text-xs text-muted">MC error ±{fmtPct(r.after.p_win_se * 1.96 * Math.SQRT2, 1)}</div>
          </div>
          <div className="flex flex-wrap gap-1">
            {r.changes.add.map((n) => <Pill key={n} tone="good">+ {n}</Pill>)}
            {r.changes.drop.map((n) => <Pill key={n} tone="bad">− {n}</Pill>)}
            {r.changes.out.map((n) => <Pill key={n} tone="warn">out: {n}</Pill>)}
            {!changed && <span className="text-xs text-muted">No changes yet — toggle players on the left.</span>}
          </div>
        </div>
      </Card>
      <Card className="p-5">
        <SectionTitle kicker="Per category" title="Win probability before vs after" />
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={data} margin={{ left: -16, right: 8, top: 8 }} barGap={2}>
              <CartesianGrid vertical={false} stroke="#1b2638" />
              <XAxis dataKey="cat" stroke="#b4bfd1" fontSize={11} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} unit="%" />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#ffffff08' }} formatter={(v) => `${v}%`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar isAnimationActive={false} dataKey="Before" fill="#3a4a66" radius={[4, 4, 0, 0]} barSize={12} />
              <Bar isAnimationActive={false} dataKey="After" fill={A} radius={[4, 4, 0, 0]} barSize={12} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-xs sm:grid-cols-9">
          {r.categories.map((c) => (
            <div key={c.key} className="rounded-md border border-line-soft px-2 py-1 text-center">
              <div className="text-muted">{c.label}</div>
              <div className={`num font-semibold ${c.delta > 0.005 ? 'text-good' : c.delta < -0.005 ? 'text-bad' : 'text-fg-2'}`}>{signed(c.delta * 100, 0)}</div>
              <div className="num text-[10px] text-muted">{fmtCat(c.key, c.mean_after)}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function Stat({ label, value, sub, color }: { label: string; value: string; sub: string; color?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-4xl font-bold" style={{ color }}>{value}</div>
      <div className="text-xs text-muted">{sub}</div>
    </div>
  )
}
