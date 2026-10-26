import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, CalendarDays } from 'lucide-react'
import { Card, ErrorState, Headshot, Pill, SectionTitle, Skeleton, TeamLogo } from '../components/ui'
import { api } from '../lib/api'
import { CAT_LABEL, CATS, fmt, fmtCat, shortDate } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'

const tooltipStyle = { background: '#172033', border: '1px solid #233047', borderRadius: 10, fontSize: 12, color: '#e6eaf2' }

export default function Dashboard() {
  const { week, meta } = useApp()
  const rankings = useAsync(() => api.rankings({ week, limit: 10 }), [week])
  const schedule = useAsync(() => api.schedule(week), [week])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-bold tracking-wide">Week Overview</h1>
        <p className="text-sm text-fg-2">{meta?.windows[week]?.label}: top players, schedule and category leaders.</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <SectionTitle kicker={meta?.windows[week]?.label} title="Top projected performers" right={<Link to="/rankings" className="inline-flex items-center gap-1 text-xs text-brand hover:underline">Full board <ArrowRight size={12} /></Link>} />
          {rankings.error && <ErrorState error={rankings.error} onRetry={rankings.reload} />}
          {!rankings.data && !rankings.error && <div className="space-y-2">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12" />)}</div>}
          <div className="grid gap-2 md:grid-cols-2">
            {rankings.data?.rows.map((r) => (
              <Link key={r.player_id} to={`/compare?a=${r.player_id}`} className="flex items-center gap-3 rounded-xl border border-line-soft bg-ink/30 p-2.5 transition hover:border-brand/50">
                <span className="w-6 text-center font-display text-xl font-bold text-muted">{r.rank}</span>
                <Headshot src={r.headshot} name={r.name} size={42} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{r.name}</div>
                  <div className="flex items-center gap-1 text-[11px] text-muted">
                    <TeamLogo src={r.team_logo} abbr={r.team_abbr} size={13} /> {r.team_abbr} · {r.games}G · {r.strengths.map((s) => CAT_LABEL[s]).join(' ')}
                  </div>
                </div>
                <div className="text-right">
                  <div className="num font-display text-xl font-semibold text-brand">{fmt(r.value)}</div>
                  <div className="num text-[10px] text-muted">{fmt(r.value_lo)}–{fmt(r.value_hi)}</div>
                </div>
              </Link>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <SectionTitle kicker="Schedule" title="Games per day" right={<CalendarDays size={16} className="text-muted" />} />
          {!schedule.data && <Skeleton className="h-52" />}
          {schedule.data && (
            <>
              <div className="h-52">
                <ResponsiveContainer>
                  <BarChart data={schedule.data.games_by_day} margin={{ left: -24, right: 4, top: 8 }}>
                    <CartesianGrid vertical={false} stroke="#1b2638" />
                    <XAxis dataKey="weekday" stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis allowDecimals={false} stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#ffffff08' }} labelFormatter={(_, p) => p?.[0] ? shortDate(p[0].payload.date) : ''} />
                    <Bar isAnimationActive={false} dataKey="games" radius={[4, 4, 0, 0]} barSize={22}>
                      {schedule.data.games_by_day.map((d) => <Cell key={d.date} fill={d.games <= 5 ? '#34c38f' : '#2e9bd6'} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 flex items-center gap-3 text-[11px] text-muted">
                <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-good" /> light day (≤5 games) — easier to start streamers</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {schedule.data.games_by_team.slice(0, 8).map((t) => (
                  <Pill key={t.abbr}><TeamLogo src={t.logo} abbr={t.abbr} size={12} /> {t.abbr} {t.games}G</Pill>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-3">
          <SectionTitle kicker="Projected week" title="Category leaders" />
          {!rankings.data && <Skeleton className="h-40" />}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
            {rankings.data && CATS.map((c) => {
              const l = rankings.data!.leaders[c.key][0]
              return (
                <div key={c.key} className="flex items-center gap-2.5 rounded-xl border border-line-soft bg-ink/30 p-2.5">
                  <Headshot src={l?.headshot} name={l?.name ?? '?'} size={36} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[10px] uppercase tracking-wider text-muted">{c.label}{c.lowerBetter ? ' (fewest)' : ''}</div>
                    <div className="truncate text-sm">{l?.name}</div>
                  </div>
                  <div className="num font-display text-lg font-semibold">{fmtCat(c.key, l?.value)}</div>
                </div>
              )
            })}
          </div>
        </Card>

      </div>
    </div>
  )
}

