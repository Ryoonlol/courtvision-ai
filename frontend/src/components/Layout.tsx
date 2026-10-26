import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  ArrowLeftRight, Bot, BrainCircuit, CalendarDays, Database, Info, Dices, FlaskConical, Flame, GitCompareArrows, History, LayoutDashboard,
  Menu, Radar, RefreshCw, Sparkles, Target, Trophy, Users, Waves,
} from 'lucide-react'
import { api } from '../lib/api'
import { useApp } from '../lib/hooks'
import { timeAgo } from '../lib/format'
import type { WeekKey } from '../lib/types'
import { Pill, Segmented } from './ui'

const NAV = [
  { section: 'Analyze', items: [
    { to: '/', label: 'Today', icon: CalendarDays },
    { to: '/overview', label: 'Week Overview', icon: LayoutDashboard },
    { to: '/compare', label: 'Player Compare', icon: GitCompareArrows },
    { to: '/rankings', label: 'Weekly Rankings', icon: Trophy },
    { to: '/breakouts', label: 'Breakouts', icon: Flame },
    { to: '/history', label: 'Past Weeks', icon: History },
  ] },
  { section: 'Manage', items: [
    { to: '/team', label: 'My Team', icon: Users },
    { to: '/trade', label: 'Trade Analyzer', icon: ArrowLeftRight },
    { to: '/streaming', label: 'Streaming', icon: Waves },
  ] },
  { section: 'Simulate', items: [
    { to: '/matchup', label: 'Matchup Simulator', icon: Dices },
    { to: '/whatif', label: 'What-If Lab', icon: FlaskConical },
  ] },
  { section: 'AI & Model', items: [
    { to: '/assistant', label: 'Ask CourtVision', icon: Bot },
    { to: '/forecast', label: 'Gemini Forecast', icon: Sparkles },
    { to: '/model', label: 'Model Lab', icon: BrainCircuit },
    { to: '/accuracy', label: 'Accuracy Tracker', icon: Target },
    { to: '/about', label: 'About', icon: Info },
  ] },
]

export function Layout({ children }: { children: ReactNode }) {
  const { meta, week, setWeek, reloadMeta } = useApp()
  const [menu, setMenu] = useState(false)
  const { pathname } = useLocation()
  const weekless = ['/', '/about', '/history', '/breakouts', '/model', '/accuracy'].includes(pathname)
  const [refreshing, setRefreshing] = useState(false)

  const refresh = async () => {
    setRefreshing(true)
    try { await api.refresh() } catch { /* surfaced through meta status */ }
    setTimeout(() => { reloadMeta(); setRefreshing(false) }, 4000)
  }

  const sidebar = (
    <nav className="flex h-full flex-col gap-5 p-4">
      <div className="flex items-center gap-2.5 px-1">
        <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-brand shadow-[0_0_24px_#ff7a1a55]">
          <Radar size={20} className="text-ink" />
        </div>
        <div>
          <div className="font-display text-xl font-bold leading-none tracking-wide">CourtVision<span className="text-brand"> AI</span></div>
          <div className="text-[10px] uppercase tracking-[0.2em] text-muted">9-cat intelligence</div>
        </div>
      </div>
      <div className="scrollbar-thin -mx-1 flex-1 space-y-4 overflow-y-auto px-1">
        {NAV.map(({ section, items }) => (
          <div key={section}>
            <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-muted">{section}</div>
            <div className="space-y-0.5">
              {items.map(({ to, label, icon: Icon }) => (
                <NavLink key={to} to={to} end={to === '/'} onClick={() => setMenu(false)}
                  className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-1.5 text-sm transition ${isActive ? 'bg-brand/12 text-brand shadow-[inset_2px_0_0_#ff7a1a]' : 'text-fg-2 hover:bg-panel-2 hover:text-fg'}`}>
                  <Icon size={16} /> {label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="space-y-2 rounded-xl border border-line bg-panel/70 p-3 text-[11px] text-muted">
        <div className="flex items-center gap-1.5 text-fg-2"><Database size={12} /> Data</div>
        <div>{meta?.data.source_label ?? 'Loading…'}</div>
        {meta && !meta.data.is_demo && (
          <button onClick={refresh} disabled={refreshing} className="flex items-center gap-1 text-brand hover:underline disabled:opacity-50">
            <RefreshCw size={11} className={refreshing ? 'animate-spin' : ''} /> Refresh now · {timeAgo(meta.data.last_refresh_utc)}
          </button>
        )}
      </div>
    </nav>
  )

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-line-soft bg-ink/60 backdrop-blur lg:block">{sidebar}</aside>
      {menu && (
        <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={() => setMenu(false)}>
          <aside className="h-full w-64 border-r border-line bg-ink" onClick={(e) => e.stopPropagation()}>{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {meta?.data.is_demo && (
          <div className="bg-warn px-4 py-1.5 text-center text-xs font-semibold text-ink">
            OFFLINE DEMO DATA — fictional players and simulated stats. Not real NBA statistics.
          </div>
        )}
        <header className="sticky top-0 z-20 flex flex-wrap items-center gap-3 border-b border-line-soft bg-ink/80 px-4 py-3 backdrop-blur md:px-8">
          <button className="text-fg-2 lg:hidden" onClick={() => setMenu(true)} aria-label="Open menu"><Menu size={20} /></button>
          {!weekless && (
            <>
              <Segmented<WeekKey> value={week} onChange={setWeek} options={[
                { value: 'current', label: 'This week' }, { value: 'next', label: 'Next week' },
              ]} />
              <span className="hidden text-xs text-muted sm:inline">{meta?.windows[week]?.label}</span>
            </>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {meta && (
              <Pill tone={meta.data.is_demo ? 'warn' : 'good'} title={meta.data.source_label}>
                <span className={`h-1.5 w-1.5 rounded-full ${meta.data.is_demo ? 'bg-warn' : 'bg-good'}`} />
                {meta.data.is_demo ? 'Demo data' : `Live NBA ${meta.data.current_season}`}
              </Pill>
            )}
            {meta && (
              meta.gemini.available
                ? <Pill tone="gemini" title={meta.gemini.provider === 'agy' ? 'Gemini via the local agy CLI' : 'Gemini via the google-genai SDK'}><Sparkles size={11} /> {meta.gemini.label}</Pill>
                : <Pill tone="warn" title="Install/sign in to the agy CLI or set GEMINI_API_KEY to enable Gemini; rule-based explanations are shown meanwhile"><Sparkles size={11} /> Gemini not configured</Pill>
            )}
            {meta?.model.trained && <Pill tone="brand" title={meta.model.algorithm}><BrainCircuit size={11} /> Model trained</Pill>}
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8">{children}</main>
        <footer className="border-t border-line-soft px-8 py-4 text-[11px] text-muted">
          CourtVision AI · statistics computed in Python from {meta?.data.is_demo ? 'a simulated demo league' : 'real NBA box scores (ESPN public API)'} · explanations by Google Gemini · not affiliated with the NBA or ESPN
        </footer>
      </div>
    </div>
  )
}
