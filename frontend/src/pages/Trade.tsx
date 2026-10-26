import { useEffect, useMemo, useState } from 'react'
import { ArrowRightLeft, Check, CircleAlert, Minus, UserMinus, UserPlus, X } from 'lucide-react'
import { AIPanel } from '../components/AIPanel'
import { ChipRow, Headline, Lead, More } from '../components/Insight'
import { DivergingCats, PuntPicker } from '../components/Category'
import { PlayerSearch } from '../components/PlayerSearch'
import { RosterBar, useRosters } from '../components/RosterManager'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Segmented, Skeleton, StatusChip } from '../components/ui'
import { api, type TradeRequest } from '../lib/api'
import { CAT_LABEL, fmt, fmtCat, signed } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'
import type { Basis, CatKey, PlayerHit, TradeInsight, TradePlayer, TradeResult } from '../lib/types'

const MAX = 3

export default function TradePage() {
  const { week } = useApp()
  const rs = useRosters()
  const [give, setGive] = useState<number[]>([])
  const [get, setGet] = useState<PlayerHit[]>([])
  const [basis, setBasis] = useState<Basis>('season')
  const [punt, setPunt] = useState<CatKey[]>([])
  const roster = rs.selected
  const ids = useMemo(() => roster?.player_ids ?? [], [roster])

  useEffect(() => { setGive([]) }, [roster?.id])

  // names/values for the roster list come from the team analyzer (same projection)
  const team = useAsync(() => api.analyzeTeam({ player_ids: ids, roster_id: roster!.id, week, basis, punt: [] }),
    [roster?.id, ids.join(','), week, basis], !!roster && ids.length > 0)

  const req: TradeRequest | null = useMemo(() => (roster && give.length && get.length
    ? { roster_player_ids: ids, give, get: get.map((g) => g.id), roster_id: roster.id, week, basis, punt } : null),
  [roster, ids, give, get, week, basis, punt])
  const key = JSON.stringify(req)
  const result = useAsync(() => api.analyzeTrade(req!), [key], !!req)
  const ai = useAsync(() => api.tradeAI(req!), [key], !!req)

  const toggleGive = (pid: number) =>
    setGive((g) => (g.includes(pid) ? g.filter((x) => x !== pid) : g.length < MAX ? [...g, pid] : g))
  const addGet = (p: PlayerHit) => {
    if (ids.includes(p.id)) return
    setGet((g) => (g.some((x) => x.id === p.id) || g.length >= MAX ? g : [...g, p]))
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Trade Analyzer</h1>
          <p className="text-sm text-fg-2">Does this trade help your team?</p>
        </div>
        <RosterBar state={rs} />
      </div>
      {rs.error && <div className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{rs.error}</div>}
      {!rs.loading && !roster && <Card className="p-8 text-center text-sm text-fg-2">Create a roster first (use “Sample draft” for a quick start).</Card>}

      {roster && (
        <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr]">
          <Card className="p-4">
            <SectionTitle kicker={`Select up to ${MAX}`} title={<span className="inline-flex items-center gap-2"><UserMinus size={18} className="text-bad" /> You give</span>} />
            {team.loading && !team.data && <Skeleton className="h-60" />}
            <div className="space-y-1">
              {team.data?.roster.map((p) => {
                const on = give.includes(p.player_id)
                return (
                  <button key={p.player_id} onClick={() => toggleGive(p.player_id)}
                    className={`flex w-full items-center gap-2.5 rounded-lg border px-2 py-1.5 text-left transition ${on ? 'border-bad/60 bg-bad/10' : 'border-transparent hover:bg-panel-2'} ${!on && give.length >= MAX ? 'opacity-40' : ''}`}>
                    <span className={`flex h-4 w-4 items-center justify-center rounded border ${on ? 'border-bad bg-bad text-ink' : 'border-line'}`}>{on && <Check size={11} />}</span>
                    <Headshot src={p.headshot} name={p.name} size={28} />
                    <span className="min-w-0 flex-1 truncate text-sm">{p.name} <span className="text-[11px] text-muted">{p.team_abbr}</span></span>
                    <span className="num text-sm text-fg-2">{fmt(p.value)}</span>
                  </button>
                )
              })}
            </div>
          </Card>

          <div className="flex items-center justify-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full border border-line bg-panel text-brand"><ArrowRightLeft size={20} /></div>
          </div>

          <Card className="h-fit p-4">
            <SectionTitle kicker={`Add up to ${MAX}`} title={<span className="inline-flex items-center gap-2"><UserPlus size={18} className="text-good" /> You get</span>} />
            <PlayerSearch placeholder="Search players to receive…" onSelect={addGet} />
            <div className="mt-3 space-y-1">
              {get.length === 0 && <div className="py-6 text-center text-xs text-muted">Players you would receive appear here.</div>}
              {get.map((p) => (
                <div key={p.id} className="flex items-center gap-2.5 rounded-lg border border-good/40 bg-good/5 px-2 py-1.5">
                  <Headshot src={p.headshot} name={p.name} size={28} />
                  <span className="min-w-0 flex-1 truncate text-sm">{p.name} <span className="text-[11px] text-muted">{p.team_abbr}</span></span>
                  <button onClick={() => setGet((g) => g.filter((x) => x.id !== p.id))} className="text-muted hover:text-bad" aria-label={`Remove ${p.name}`}><X size={15} /></button>
                </div>
              ))}
            </div>
            <div className="mt-4 space-y-2 border-t border-line-soft pt-3">
              <Segmented<Basis> value={basis} onChange={setBasis} options={[{ value: 'season', label: 'Rest of season' }, { value: 'week', label: 'Projected week' }]} />
              <PuntPicker value={punt} onChange={setPunt} />
            </div>
          </Card>
        </div>
      )}

      {roster && !req && <div className="text-center text-sm text-muted">Pick at least one player on each side to evaluate the trade.</div>}
      {result.error && <ErrorState error={result.error} onRetry={result.reload} />}
      {req && result.loading && !result.data && <Skeleton className="h-64" />}
      {req && result.data && <TradeBody r={result.data} />}
      {req && (
        <AIPanel title="Gemini Trade Breakdown" res={ai.data} loading={ai.loading} error={ai.error}>
          {(d) => <TradeInsightBody d={d} />}
        </AIPanel>
      )}
    </div>
  )
}

const VERDICT = {
  accept: { label: 'Accept', tone: 'good' as const, color: '#34c38f', icon: Check },
  decline: { label: 'Decline', tone: 'bad' as const, color: '#ef5b5b', icon: X },
  fair: { label: 'Roughly even', tone: 'warn' as const, color: '#f2b33d', icon: Minus },
}

function TradeBody({ r }: { r: TradeResult }) {
  const v = VERDICT[r.verdict]
  const Icon = v.icon
  return (
    <>
      <Card className="court-lines relative overflow-hidden p-6">
        <div className="absolute inset-y-0 left-0 w-1.5" style={{ background: v.color }} />
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl" style={{ background: `${v.color}22`, color: v.color }}><Icon size={28} /></div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted">{r.format} · {r.basis === 'season' ? 'rest of season' : r.window.label}</div>
              <div className="font-display text-3xl font-bold" style={{ color: v.color }}>{v.label}</div>
            </div>
          </div>
          <Metric label="Fit for your team" value={signed(r.need_weighted_delta, 2)} color={r.need_weighted_delta >= 0 ? '#34c38f' : '#ef5b5b'} />
          <Metric label="Overall value change" value={signed(r.value_delta, 2)} />
          <Metric label="Value given → received" value={`${fmt(r.give_value)} → ${fmt(r.get_value)}`} />
          <div className="flex flex-wrap gap-1">
            {r.improved.map((k) => <Pill key={k} tone="good">▲ {CAT_LABEL[k]}</Pill>)}
            {r.worsened.map((k) => <Pill key={k} tone="bad">▼ {CAT_LABEL[k]}</Pill>)}
          </div>
        </div>
        {r.adjustments.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {r.adjustments.map((a) => (
              <div key={a.player_id} className="inline-flex items-center gap-2 rounded-lg border border-warn/40 bg-warn/5 px-3 py-1.5 text-xs text-warn">
                <CircleAlert size={13} /> {a.type === 'drop' ? 'Drop' : 'Add free agent'} <b>{a.name}</b> — {a.reason.toLowerCase()}
              </div>
            ))}
          </div>
        )}
        {r.value_balance > 3 && r.verdict === 'accept' && (
          <div className="mt-3 text-xs text-muted">You receive {fmt(r.value_balance)} more value than you give — the other manager may not accept.</div>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="p-5">
          <SectionTitle kicker="Change vs your current team" title="Category impact" />
          <DivergingCats data={r.categories.map((c) => ({ key: c.key, label: c.label, value: c.z_delta, dim: c.punted }))} valueLabel="change" />
        </Card>
        <Card className="p-5">
          <SectionTitle kicker={r.basis === 'season' ? 'Sum of per-game rates' : 'Projected week totals'} title="Before → after" />
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Cat</th><th className="text-right font-medium">Before</th><th className="text-right font-medium">After</th><th className="text-right font-medium">Change</th><th className="text-right font-medium">Weight</th></tr>
            </thead>
            <tbody>
              {r.categories.map((c) => (
                <tr key={c.key} className={`border-b border-line-soft ${c.punted ? 'opacity-40' : ''}`}>
                  <td className="py-1.5 font-medium">{c.label}</td>
                  <td className="num text-right text-muted">{fmtCat(c.key, c.before)}</td>
                  <td className="num text-right">{fmtCat(c.key, c.after)}</td>
                  <td className={`num text-right font-semibold ${c.z_delta > 0.05 ? 'text-good' : c.z_delta < -0.05 ? 'text-bad' : 'text-muted'}`}>{signed(c.z_delta, 2)}</td>
                  <td className="num text-right text-muted">{c.punted ? 'punt' : `${c.weight.toFixed(2)}×`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted">Weight = how much each category matters to you: weak categories count more, strong ones less.</p>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <SideCard title="Outgoing" players={r.give} tone="bad" />
        <SideCard title="Incoming" players={r.get} tone="good" />
      </div>
    </>
  )
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-2xl font-semibold" style={{ color }}>{value}</div>
    </div>
  )
}

function SideCard({ title, players, tone }: { title: string; players: TradePlayer[]; tone: 'good' | 'bad' }) {
  return (
    <Card className="p-4">
      <div className={`mb-2 text-[11px] font-semibold uppercase tracking-wider ${tone === 'good' ? 'text-good' : 'text-bad'}`}>{title}</div>
      {players.map((p) => {
        const top = (Object.entries(p.z) as [CatKey, number][]).sort((a, b) => b[1] - a[1])
        return (
          <div key={p.player_id} className="flex items-center gap-3 py-1.5">
            <Headshot src={p.headshot} name={p.name} size={36} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 text-sm">{p.name} {!p.status.startsWith('Active') && <StatusChip status={p.status} />}</div>
              <div className="text-[11px] text-muted">{p.team_abbr} · best: {top.slice(0, 3).map(([k]) => CAT_LABEL[k]).join(', ')} · worst: {CAT_LABEL[top[top.length - 1][0]]}</div>
            </div>
            <span className="num font-display text-lg font-semibold">{fmt(p.value)}</span>
          </div>
        )
      })}
    </Card>
  )
}

function TradeInsightBody({ d }: { d: TradeInsight }) {
  return (
    <div className="space-y-3">
      <Headline text={d.headline}>
        <Pill tone={d.verdict === 'accept' ? 'good' : d.verdict === 'decline' ? 'bad' : 'warn'}>{d.verdict}</Pill>
      </Headline>
      <Lead text={d.summary} />
      <ChipRow label="Gain" items={d.benefits} tone="good" labelClass="text-good" />
      <ChipRow label="Lose" items={d.risks} tone="bad" labelClass="text-bad" />
      <More label="Negotiation tip"><Lead text={d.negotiation_tip} /></More>
    </div>
  )
}

