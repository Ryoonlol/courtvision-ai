import { Link } from 'react-router-dom'
import { ArrowRight, BrainCircuit, Database, Sparkles } from 'lucide-react'
import { Card, SectionTitle, Stat } from '../components/ui'
import { api } from '../lib/api'
import { timeAgo } from '../lib/format'
import { useApp, useAsync } from '../lib/hooks'

/** What CourtVision is and how it works: the pitch and system stats moved off the main pages. */
export default function About() {
  const { meta } = useApp()
  const model = useAsync(() => api.model(), [])
  const mlCount = Object.values(meta?.model.use_ml ?? {}).filter(Boolean).length
  const cur = meta?.data.seasons.find((s) => s.season === meta.data.current_season)
  return (
    <div className="space-y-6">
      <Card className="court-lines relative overflow-hidden p-6 md:p-8">
        <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full border-[18px] border-brand/10" />
        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-brand">H2H 9-category · {meta?.data.current_season} season</div>
          <h1 className="mt-1 font-display text-4xl font-bold leading-tight tracking-wide md:text-5xl">
            Win your week with <span className="text-brand">projections</span>, not hunches.
          </h1>
          <p className="mt-3 max-w-2xl text-sm text-fg-2">
            CourtVision projects every player from real box scores, schedules and injury reports, and uses Google Gemini to explain the numbers — never to invent them.
          </p>
        </div>
        <div className="relative mt-7 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Box scores" value={meta ? meta.data.seasons.reduce((s, x) => s + x.player_games, 0).toLocaleString() : '—'} sub={`${meta?.data.seasons.length ?? 0} seasons · ${cur?.games ?? 0} games this season`} />
          <Stat label="Injury reports" value={meta?.data.injuries.count ?? '—'} sub={`refreshed ${timeAgo(meta?.data.last_refresh_utc)}`} />
          <Stat label="Model" value={meta?.model.trained ? `${mlCount}/12` : 'Baseline'} sub={meta?.model.trained ? 'stats using ML (validated)' : 'weighted average'} accent="#ff7a1a" />
          <Stat label="Training rows" value={model.data?.rows?.final_fit?.toLocaleString() ?? '—'} sub={meta?.model.split_date ? `validated after ${meta.model.split_date}` : ''} />
        </div>
      </Card>

      <Card className="p-5">
        <SectionTitle title="System status" />
        <div className="grid gap-4 text-sm md:grid-cols-3">
          <Row icon={<Database size={15} />} label="Data" value={meta?.data.is_demo ? 'Offline demo' : 'ESPN · real NBA'} sub={meta?.data.source_label} />
          <Row icon={<BrainCircuit size={15} />} label="Projections" value={meta?.model.trained ? 'Trained model + weighted baseline' : 'Weighted baseline'} sub="See Model Lab and Accuracy Tracker" />
          <Row icon={<Sparkles size={15} />} label="Gemini" value={meta?.gemini.available ? meta.gemini.label : 'Not configured'}
            sub={meta?.gemini.available ? 'Explanations are number-checked against the data' : 'Sign in to the agy CLI or add GEMINI_API_KEY'} />
        </div>
        <div className="mt-4 flex gap-4 text-xs">
          <Link to="/model" className="inline-flex items-center gap-1 text-brand hover:underline">Model Lab <ArrowRight size={12} /></Link>
          <Link to="/accuracy" className="inline-flex items-center gap-1 text-brand hover:underline">Accuracy Tracker <ArrowRight size={12} /></Link>
        </div>
      </Card>
    </div>
  )
}

function Row({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 text-brand">{icon}</span>
      <div>
        <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
        <div className="text-fg">{value}</div>
        {sub && <div className="text-xs text-muted">{sub}</div>}
      </div>
    </div>
  )
}
