import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import { AIPanel } from '../components/AIPanel'
import { Bullets, ChipRow, Emph, Headline, Lead, More, Sub } from '../components/Insight'
import { DivergingCats, PuntPicker } from '../components/Category'
import { PlayerSearch } from '../components/PlayerSearch'
import { RosterBar, useRosters } from '../components/RosterManager'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Segmented, Skeleton, StatusChip } from '../components/ui'
import { api, type TeamRequest } from '../lib/api'
import { CATS, CAT_LABEL, fmt, fmtCat, signed, zTint } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'
import type { Basis, CatKey, TeamAnalysis, TeamInsight } from '../lib/types'

export default function TeamPage() {
  const { week } = useApp()
  const rs = useRosters()
  const [basis, setBasis] = useState<Basis>('week')
  const [punt, setPunt] = useState<CatKey[]>([])
  const roster = rs.selected
  const ids = roster?.player_ids ?? []

  const req: TeamRequest | null = useMemo(() => (roster && ids.length
    ? { player_ids: ids, roster_id: roster.id, week, basis, punt } : null), [roster, ids, week, basis, punt])
  const key = JSON.stringify(req)
  const analysis = useAsync(() => api.analyzeTeam(req!), [key], !!req)
  const ai = useAsync(() => api.teamAI(req!), [key], !!req)

  const add = (pid: number) => roster && !ids.includes(pid) && rs.save(roster.id, [...ids, pid])
  const remove = (pid: number) => roster && rs.save(roster.id, ids.filter((p) => p !== pid))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">My Team</h1>
          <p className="text-sm text-fg-2">Your roster's strengths, weaknesses and best pickups.</p>
        </div>
        <RosterBar state={rs} />
      </div>
      {rs.error && <div className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{rs.error}</div>}

      {!rs.loading && !roster && (
        <Card className="court-lines p-10 text-center">
          <div className="font-display text-2xl font-semibold">No roster yet</div>
          <p className="mx-auto mt-2 max-w-md text-sm text-fg-2">Create an empty roster and add players with search, or generate a sample team from a simulated 12-team snake draft.</p>
        </Card>
      )}

      {roster && (
        <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
          <Card className="h-fit p-4">
            <SectionTitle kicker={`${ids.length} players`} title={roster.name} />
            <PlayerSearch placeholder="Add a player…" onSelect={(p) => add(p.id)} />
            <div className="mt-3 space-y-1">
              {ids.length === 0 && <div className="py-6 text-center text-xs text-muted">Search above to add players.</div>}
              {(analysis.data?.roster ?? []).map((p) => (
                <div key={p.player_id} className="group flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-panel-2">
                  <Headshot src={p.headshot} name={p.name} size={32} />
                  <div className="min-w-0 flex-1">
                    <Link to={`/compare?a=${p.player_id}`} className="block truncate text-sm hover:text-brand">{p.name}</Link>
                    <div className="flex items-center gap-1 text-[11px] text-muted">{p.team_abbr} · {p.position} · {p.games}G {!p.status.startsWith('Active') && <StatusChip status={p.status} />}</div>
                  </div>
                  <span className="num font-display text-base font-semibold text-brand" title="Fantasy value (0 = average starter)">{fmt(p.value)}</span>
                  <button onClick={() => remove(p.player_id)} className="text-muted opacity-0 transition group-hover:opacity-100 hover:text-bad" aria-label={`Remove ${p.name}`}><X size={15} /></button>
                </div>
              ))}
              {(analysis.data?.profile.missing_player_ids ?? []).map((pid) => (
                <div key={pid} className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-xs text-muted">
                  <span className="flex-1">Player #{pid} — no current projection (not active this season)</span>
                  <button onClick={() => remove(pid)} className="hover:text-bad" aria-label="Remove player"><X size={14} /></button>
                </div>
              ))}
              {analysis.loading && !analysis.data && ids.length > 0 && <Skeleton className="h-40" />}
            </div>
          </Card>

          <div className="min-w-0 space-y-4">
            <Card className="flex flex-wrap items-center gap-3 p-3">
              <Segmented<Basis> value={basis} onChange={setBasis} options={[{ value: 'week', label: 'Projected week' }, { value: 'season', label: 'Per-game (rest of season)' }]} />
              <PuntPicker value={punt} onChange={setPunt} />
            </Card>
            {analysis.error && <ErrorState error={analysis.error} onRetry={analysis.reload} />}
            {ids.length > 0 && analysis.data && <Analysis a={analysis.data} onAdd={add} />}
            {ids.length > 0 && (
              <AIPanel title="Gemini Team Report" res={ai.data} loading={ai.loading} error={ai.error}>
                {(d) => <TeamInsightBody d={d} />}
              </AIPanel>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Analysis({ a, onAdd }: { a: TeamAnalysis; onAdd: (pid: number) => void }) {
  const p = a.profile
  const above = p.categories.filter((c) => c.z > 0).length
  const fg = p.categories.find((c) => c.key === 'fg_pct')!
  const ft = p.categories.find((c) => c.key === 'ft_pct')!
  const to = p.categories.find((c) => c.key === 'tov')!
  const unit = p.basis === 'week' ? 'projected week' : 'sum of per-game rates'
  return (
    <>
      <div className="grid gap-4 md:grid-cols-4">
        <Tile label="Categories above average" value={`${above} / 9`} sub="vs. a typical 12-team roster" accent="#ff7a1a" />
        <Tile label="Team fantasy value" value={fmt(p.total_value)} sub={p.basis === 'week' ? `${p.games} games scheduled` : 'per-game, vs average team'} />
        <Tile label="FG% / FT%" value={`${fmtCat('fg_pct', fg.value)} / ${fmtCat('ft_pct', ft.value)}`} sub={`avg ${fmtCat('fg_pct', fg.average_team)} / ${fmtCat('ft_pct', ft.average_team)} · ${fmt(p.totals.fga, 0)} FGA`} />
        <Tile label="Turnovers" value={fmt(to.value)} sub={`avg team ${fmt(to.average_team)} · ${to.z >= 0 ? 'better' : 'worse'} than average`} />
      </div>

      <div className="grid gap-4 2xl:grid-cols-2">
        <Card className="p-5">
          <SectionTitle kicker={unit} title="Category strength vs an average team" />
          <DivergingCats data={p.categories.map((c) => ({ key: c.key, label: c.label, value: c.z, dim: a.punt.includes(c.key) }))} />
          <p className="text-[11px] text-muted">0 = an average roster; right = stronger. Fewer turnovers counts as stronger.</p>
        </Card>
        <Card className="p-5">
          <SectionTitle kicker={unit} title="Expected production" />
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Cat</th><th className="text-right font-medium">Team</th><th className="text-right font-medium">Avg team</th><th className="text-right font-medium">vs avg</th><th className="text-right font-medium">Status</th></tr>
            </thead>
            <tbody>
              {p.categories.map((c) => (
                <tr key={c.key} className="border-b border-line-soft">
                  <td className="py-1.5 font-medium">{c.label}{a.punt.includes(c.key) && <span className="ml-1 text-[10px] text-bad">punt</span>}</td>
                  <td className="num text-right">{fmtCat(c.key, c.value)}</td>
                  <td className="num text-right text-muted">{fmtCat(c.key, c.average_team)}</td>
                  <td className="num text-right" style={{ background: zTint(c.z / Math.max(p.status_threshold, 1)) }}>{signed(c.z)}</td>
                  <td className="text-right"><Pill tone={c.status === 'strong' ? 'good' : c.status === 'weak' ? 'bad' : 'default'}>{c.status}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Card className="p-5">
        <SectionTitle kicker={`Free agents · excludes other saved rosters & top ${a.assume_rostered} (assumed rostered)`} title="Players who could improve the team" />
        {a.recommendations.length === 0 && <div className="text-sm text-muted">No eligible free agents.</div>}
        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Add</th><th className="text-left font-medium">Drop</th><th className="text-right font-medium">G</th><th className="text-right font-medium">Net gain</th><th className="pl-3 text-left font-medium">Helps</th><th /></tr>
            </thead>
            <tbody>
              {a.recommendations.map((r) => (
                <tr key={r.player_id} className="border-b border-line-soft">
                  <td className="py-1.5">
                    <div className="flex items-center gap-2"><Headshot src={r.headshot} name={r.name} size={28} />
                      <div><div>{r.name}</div><div className="text-[11px] text-muted">{r.team_abbr} · {r.position}</div></div></div>
                  </td>
                  <td className="text-fg-2">{r.drop_name}</td>
                  <td className="num text-right">{r.games}</td>
                  <td className={`num text-right font-semibold ${r.net_gain > 0 ? 'text-good' : 'text-bad'}`}>{signed(r.net_gain, 2)}</td>
                  <td className="pl-3"><div className="flex gap-1">{r.helps.map((k) => <Pill key={k} tone="good">{CAT_LABEL[k]} {signed(r.category_deltas[k])}</Pill>)}</div></td>
                  <td className="text-right">
                    <button onClick={() => onAdd(r.player_id)} className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-fg-2 hover:border-brand hover:text-brand" title="Add to roster (keeps your current players)"><Plus size={12} /> Add</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-muted">Net gain = how much better the free agent fits your needs than your weakest-fit player.</p>
      </Card>

      <Card className="p-5">
        <SectionTitle kicker="Who drives each category" title="Roster contribution heatmap" />
        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr className="border-b border-line"><th className="py-1.5 text-left font-medium">Player</th>{CATS.map((c) => <th key={c.key} className="text-right font-medium">{c.label}</th>)}<th className="text-right font-medium">Fit</th></tr>
            </thead>
            <tbody>
              {a.roster.map((pl) => (
                <tr key={pl.player_id} className="border-b border-line-soft">
                  <td className="py-1.5">{pl.name}</td>
                  {CATS.map((c) => <td key={c.key} className="num px-1 text-right" style={{ background: zTint(pl.z[c.key]) }}>{fmt(pl.z[c.key])}</td>)}
                  <td className="num text-right text-brand">{fmt(pl.fit_score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

function Tile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-2xl font-semibold" style={{ color: accent }}>{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </Card>
  )
}

function TeamInsightBody({ d }: { d: TeamInsight }) {
  return (
    <div className="space-y-3">
      <Headline text={d.headline} />
      <Lead text={d.assessment} />
      <ChipRow label="Strong" items={d.strengths} tone="good" labelClass="text-good" />
      <ChipRow label="Weak" items={d.weaknesses} tone="bad" labelClass="text-bad" />
      <Sub title="Do this" className="text-brand">
        <Bullets dot="bg-brand" items={d.moves.slice(0, 2).map((m) => <span title={m.reason} className="font-medium text-fg">{m.action}</span>)} />
      </Sub>
      <More>
        <Sub title="Why these moves"><Bullets items={d.moves.map((m) => <><b className="text-fg">{m.action}:</b> <Emph text={m.reason} /></>)} /></Sub>
        <Sub title="Strategy" className="text-gemini"><Lead text={d.strategy} /></Sub>
      </More>
    </div>
  )
}

