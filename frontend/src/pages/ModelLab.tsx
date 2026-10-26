import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CheckCircle2, FlaskConical } from 'lucide-react'
import { Card, ErrorState, Pill, SectionTitle, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { useAsync } from '../lib/hooks'

const LABELS: Record<string, string> = {
  min: 'MIN', pts: 'PTS', reb: 'REB', ast: 'AST', stl: 'STL', blk: 'BLK', fg3m: '3PM', tov: 'TO',
  fgm: 'FGM', fga: 'FGA', ftm: 'FTM', fta: 'FTA',
}
const tooltipStyle = { background: '#172033', border: '1px solid #233047', borderRadius: 10, fontSize: 12, color: '#e6eaf2' }

export default function ModelLab() {
  const m = useAsync(() => api.model(), [])
  if (m.error) return <ErrorState error={m.error} onRetry={m.reload} />
  if (!m.data) return <Skeleton className="h-96" />
  const d = m.data
  const stats = Object.keys(LABELS).filter((s) => d.metrics?.[s])
  // improvement vs naive season average, % of MAE (positive = better)
  const chart = stats.map((s) => {
    const v = d.metrics![s].validation
    return {
      stat: LABELS[s],
      'Weighted baseline': +(100 * (1 - v.mae_baseline / v.mae_season_avg)).toFixed(1),
      'Gradient boosting': +(100 * (1 - v.mae_ml / v.mae_season_avg)).toFixed(1),
    }
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-bold tracking-wide">Model Lab</h1>
        <p className="text-sm text-fg-2">How the projection model is built and tested.</p>
      </div>

      {!d.trained && (
        <Card className="p-5 text-sm text-warn">No trained model yet — projections use the explainable weighted-average baseline.</Card>
      )}

      {d.trained && (
        <div className="grid gap-4 md:grid-cols-4">
          <Info label="Algorithm" value="Gradient boosting" sub={d.algorithm} />
          <Info label="Training rows" value={d.rows?.train?.toLocaleString() ?? '—'} sub={`2024-25 + 2025-26 before ${d.split_date}`} />
          <Info label="Validation rows" value={d.rows?.validation?.toLocaleString() ?? '—'} sub={`2025-26 from ${d.split_date}`} />
          <Info label="2026-27 holdout" value={d.rows?.test?.toLocaleString() ?? '—'} sub={`games through ${d.data_through}`} />
        </div>
      )}

      {d.trained && (
        <Card className="p-5">
          <SectionTitle kicker="Validation window" title="Error reduction vs. season-average projection" right={<Pill>per-game MAE, higher is better</Pill>} />
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ left: -12, right: 8, top: 8 }} barGap={2}>
                <CartesianGrid vertical={false} stroke="#1b2638" />
                <XAxis dataKey="stat" stroke="#b4bfd1" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} unit="%" />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#ffffff08' }} formatter={(v) => `${v}%`} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar isAnimationActive={false} dataKey="Weighted baseline" fill="#e5641a" radius={[4, 4, 0, 0]} barSize={12} />
                <Bar isAnimationActive={false} dataKey="Gradient boosting" fill="#2e9bd6" radius={[4, 4, 0, 0]} barSize={12} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {d.trained && (
        <Card className="p-5">
          <SectionTitle kicker="Honest scorecard" title="Average miss per game (lower is better)" />
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 text-left font-medium">Stat</th>
                  <th className="py-2 text-right font-medium">Avg actual</th>
                  <th className="py-2 text-right font-medium">Season avg</th>
                  <th className="py-2 text-right font-medium">Weighted baseline</th>
                  <th className="py-2 text-right font-medium">Gradient boosting</th>
                  <th className="py-2 text-right font-medium">2026-27 baseline</th>
                  <th className="py-2 text-right font-medium">2026-27 ML</th>
                  <th className="py-2 text-right font-medium">Used in app</th>
                </tr>
              </thead>
              <tbody>
                {stats.map((s) => {
                  const mm = d.metrics![s]
                  const v = mm.validation
                  const best = Math.min(v.mae_baseline, v.mae_ml, v.mae_season_avg)
                  const cell = (x: number) => <span className={x === best ? 'font-semibold text-good' : ''}>{fmt(x, 3)}</span>
                  return (
                    <tr key={s} className="border-b border-line-soft">
                      <td className="py-1.5 font-medium">{LABELS[s]}</td>
                      <td className="num text-right text-muted">{fmt(v.mean_actual, 2)}</td>
                      <td className="num text-right">{cell(v.mae_season_avg)}</td>
                      <td className="num text-right">{cell(v.mae_baseline)}</td>
                      <td className="num text-right">{cell(v.mae_ml)}</td>
                      <td className="num text-right text-fg-2">{fmt(mm.test?.mae_baseline, 3)}</td>
                      <td className="num text-right text-fg-2">{fmt(mm.test?.mae_ml, 3)}</td>
                      <td className="text-right">
                        <Pill tone={mm.method?.startsWith('ml') ? 'gemini' : 'brand'}>{mm.method?.startsWith('ml') ? 'ML' : 'Baseline'}{mm.method?.includes('%') ? ' × %' : ''}</Pill>
                      </td>
                    </tr>
                  )
                })}
                {(['fg_pct', 'ft_pct'] as const).map((s) => {
                  const v = d.metrics?.[s]?.validation
                  if (!v) return null
                  return (
                    <tr key={s} className="border-b border-line-soft">
                      <td className="py-1.5 font-medium">{s === 'fg_pct' ? 'FG%' : 'FT%'}</td>
                      <td colSpan={3} className="text-right text-xs text-muted">attempt-weighted |error| · direct makes model: {(v.attempt_weighted_mae_direct * 100).toFixed(1)} pts</td>
                      <td className="num text-right font-semibold text-good">{(v.attempt_weighted_mae * 100).toFixed(1)} pts</td>
                      <td colSpan={2} />
                      <td className="text-right"><Pill tone="brand">Attempts × blended %</Pill></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 flex items-start gap-2 text-xs text-muted">
            <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-good" />
            Selection rule: for each stat the app uses the gradient-boosted model only if it beat the weighted baseline on the validation window;
            the 2026-27 columns are an untouched out-of-season holdout. Single-game stats are noisy, so improvements of a few percent are meaningful at the weekly level.
          </p>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <Method title="Weighted baseline" text={d.baseline.description} />
        <Method title="Shooting percentages" text={d.shooting} />
        <Method title="Uncertainty" text={d.uncertainty} />
      </div>
    </div>
  )
}

function Info({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-2xl font-semibold">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </Card>
  )
}

function Method({ title, text }: { title: string; text: string }) {
  return (
    <Card className="p-5">
      <div className="mb-2 flex items-center gap-2 font-display text-lg font-semibold"><FlaskConical size={16} className="text-brand" /> {title}</div>
      <p className="text-sm leading-relaxed text-fg-2">{text}</p>
    </Card>
  )
}
