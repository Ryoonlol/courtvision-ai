import { useState } from 'react'
import { Link } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'
import { AIPanel } from '../components/AIPanel'
import { Bullets, Emph, Headline, Lead, More } from '../components/Insight'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Skeleton, TeamLogo } from '../components/ui'
import { api } from '../lib/api'
import { fmt, signed } from '../lib/format'
import { useAsync, useDebounced } from '../lib/hooks'
import type { BreakoutCandidate, BreakoutComponent, BreakoutInsight } from '../lib/types'

const COMPONENTS: { key: BreakoutComponent; label: string; color: string }[] = [
  { key: 'minutes', label: 'Minutes', color: '#e5641a' },
  { key: 'usage', label: 'Usage', color: '#2e9bd6' },
  { key: 'shots', label: 'Shots', color: '#8ab4f8' },
  { key: 'production', label: 'Production', color: '#34c38f' },
  { key: 'defense', label: 'Defense', color: '#c58af9' },
]

export default function BreakoutsPage() {
  const [asOf, setAsOf] = useState('')
  const [minMin, setMinMin] = useState(12)
  const dAsOf = useDebounced(asOf, 400)
  const res = useAsync(() => api.breakouts({ as_of: dAsOf || undefined, limit: 25, min_minutes: minMin }), [dAsOf, minMin])
  const ai = useAsync(() => api.breakoutsAI({ as_of: dAsOf || undefined, min_minutes: minMin }), [dAsOf, minMin])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Breakouts</h1>
          <p className="text-sm text-fg-2 cursor-help" title="Last 5 games vs the 25 before. Score = 30% minutes, 20% usage, 15% shots, 25% production, 10% defense.">Players whose minutes and production are rising. ⓘ</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-fg-2">As of
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1 text-sm" />
          </label>
          <label className="flex items-center gap-2 text-sm text-fg-2">Min recent MIN
            <select value={minMin} onChange={(e) => setMinMin(Number(e.target.value))} className="rounded-lg border border-line bg-panel px-2 py-1 text-sm">
              {[0, 8, 12, 16, 20, 24].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
        </div>
      </div>

      <AIPanel title="Gemini Breakout Report" res={ai.data} loading={ai.loading} error={ai.error}>
        {(d) => <InsightBody d={d} />}
      </AIPanel>

      {res.error && <ErrorState error={res.error} onRetry={res.reload} />}
      {!res.data && !res.error && <Skeleton className="h-96" />}
      {res.data && (
        <Card className={`p-5 ${res.loading ? 'opacity-60' : ''}`}>
          <SectionTitle kicker={`Data through ${res.data.as_of} · ${res.data.eligible} eligible players`} title="Trending up" right={
            <div className="flex flex-wrap gap-2 text-[11px] text-muted">{COMPONENTS.map((c) => (
              <span key={c.key} className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: c.color }} />{c.label}</span>))}</div>} />
          <div className="space-y-2">
            {res.data.candidates.map((c, i) => <Row key={c.player_id} c={c} i={i} max={res.data!.candidates[0]?.score ?? 1} />)}
          </div>
        </Card>
      )}
    </div>
  )
}

function Row({ c, i, max }: { c: BreakoutCandidate; i: number; max: number }) {
  const positive = COMPONENTS.map((k) => ({ ...k, v: Math.max(c.components[k.key], 0) }))
  const total = positive.reduce((s, x) => s + x.v, 0) || 1
  return (
    <div className="grid items-center gap-3 rounded-xl border border-line-soft bg-ink/30 p-3 md:grid-cols-[28px_minmax(180px,240px)_1fr_220px]">
      <div className="font-display text-xl text-muted">{i + 1}</div>
      <Link to={`/compare?a=${c.player_id}`} className="flex items-center gap-2.5 hover:text-brand">
        <Headshot src={c.headshot} name={c.name} size={40} />
        <div className="min-w-0">
          <div className="truncate font-medium">{c.name}</div>
          <div className="flex items-center gap-1 text-[11px] text-muted"><TeamLogo src={c.team_logo} abbr={c.team_abbr} size={13} /> {c.team_abbr} · {c.position} · {c.recent_window}</div>
        </div>
      </Link>
      <div>
        <div className="flex items-center gap-2">
          <div className="flex h-3 flex-1 overflow-hidden rounded-full bg-line-soft" style={{ maxWidth: `${Math.max(c.score / max, 0.05) * 100}%` }} title={COMPONENTS.map((k) => `${k.label} ${signed(c.components[k.key], 2)}`).join(' · ')}>
            {positive.map((k) => <div key={k.key} style={{ width: `${(k.v / total) * 100}%`, background: k.color }} />)}
          </div>
          <span className="num font-display text-lg font-semibold text-brand">{fmt(c.score, 2)}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {c.signals.map((s) => <Pill key={s} tone="good">{s}</Pill>)}
          {c.spans_seasons && <Pill tone="warn" title={`Baseline from ${c.baseline_season}`}><TriangleAlert size={10} /> spans offseason</Pill>}
        </div>
      </div>
      <table className="text-xs">
        <thead className="text-[10px] uppercase text-muted"><tr><th /><th className="text-right font-medium">MIN</th><th className="text-right font-medium">PTS</th><th className="text-right font-medium">FGA</th><th className="text-right font-medium">Value</th></tr></thead>
        <tbody>
          <tr><td className="text-muted">Before</td><td className="num text-right">{fmt(c.baseline.min)}</td><td className="num text-right">{fmt(c.baseline.pts)}</td><td className="num text-right">{fmt(c.baseline.fga)}</td><td className="num text-right">{fmt(c.baseline.value)}</td></tr>
          <tr className="text-good"><td>Last 5</td><td className="num text-right">{fmt(c.recent.min)}</td><td className="num text-right">{fmt(c.recent.pts)}</td><td className="num text-right">{fmt(c.recent.fga)}</td><td className="num text-right">{fmt(c.recent.value)}</td></tr>
        </tbody>
      </table>
    </div>
  )
}

function InsightBody({ d }: { d: BreakoutInsight }) {
  return (
    <div className="space-y-3">
      <Headline text={d.headline} />
      <Lead text={d.overview} />
      <div className="divide-y divide-line-soft rounded-lg border border-line-soft">
        {d.players.map((p) => (
          <div key={p.player} className="grid gap-1 px-3 py-1.5 text-sm sm:grid-cols-[170px_1fr]" title={p.sustainability}>
            <span className="font-medium text-brand">{p.player}</span>
            <span className="text-fg-2"><Emph text={p.why} /></span>
          </div>
        ))}
      </div>
      <More label="Will it last?">
        <Bullets items={d.players.map((p) => <><b className="text-fg">{p.player}:</b> {p.sustainability}</>)} />
        <div className="text-xs text-warn">{d.caution}</div>
      </More>
    </div>
  )
}

