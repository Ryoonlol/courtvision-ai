import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Loader2, Radar } from 'lucide-react'
import { Layout } from './components/Layout'
import { api } from './lib/api'
import { AppContext } from './lib/hooks'
import type { Meta, WeekKey } from './lib/types'
import Dashboard from './pages/Dashboard'
import Compare from './pages/Compare'
import RankingsPage from './pages/Rankings'
import ModelLab from './pages/ModelLab'
import TeamPage from './pages/Team'
import TradePage from './pages/Trade'
import HistoryPage from './pages/History'
import MatchupPage from './pages/Matchup'
import WhatIfPage from './pages/WhatIf'
import StreamingPage from './pages/Streaming'
import BreakoutsPage from './pages/Breakouts'
import AccuracyPage from './pages/Accuracy'
import AssistantPage from './pages/Assistant'
import GeminiForecastPage from './pages/GeminiForecast'
import TodayPage from './pages/Today'
import About from './pages/About'

function readWeek(): WeekKey {
  try { return (localStorage.getItem('cv-week') as WeekKey) || 'next' } catch { return 'next' }
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [metaError, setMetaError] = useState<string | null>(null)
  const [week, setWeekState] = useState<WeekKey>(readWeek)

  const loadMeta = useCallback(() => {
    api.meta().then((m) => { setMeta(m); setMetaError(null) }).catch((e: Error) => setMetaError(e.message))
  }, [])

  useEffect(loadMeta, [loadMeta])
  // Poll while the backend is still downloading data / training the model.
  const ready = meta?.bootstrap.status === 'ready' || (meta && meta.data.seasons.length > 0 && meta.bootstrap.status !== 'loading')
  useEffect(() => {
    if (ready && !metaError) return
    const t = setInterval(loadMeta, 3000)
    return () => clearInterval(t)
  }, [ready, metaError, loadMeta])

  const setWeek = (w: WeekKey) => {
    setWeekState(w)
    try { localStorage.setItem('cv-week', w) } catch { /* storage unavailable */ }
  }

  if (!ready) {
    return (
      <div className="court-lines flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand shadow-[0_0_40px_#ff7a1a66]"><Radar className="text-ink" /></div>
        <div className="font-display text-3xl font-bold">CourtVision<span className="text-brand"> AI</span></div>
        {metaError ? (
          <div className="max-w-md text-sm text-bad">{metaError}<div className="mt-2 text-muted">Start the backend with <code className="text-fg-2">./scripts/start_backend.sh</code></div></div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-fg-2">
            <Loader2 size={16} className="animate-spin text-brand" /> {meta?.bootstrap.message ?? 'Connecting to backend…'}
          </div>
        )}
      </div>
    )
  }

  return (
    <AppContext.Provider value={{ meta, week, setWeek, reloadMeta: loadMeta }}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<TodayPage />} />
            <Route path="/overview" element={<Dashboard />} />
            <Route path="/about" element={<About />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/rankings" element={<RankingsPage />} />
            <Route path="/model" element={<ModelLab />} />
            <Route path="/team" element={<TeamPage />} />
            <Route path="/trade" element={<TradePage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/matchup" element={<MatchupPage />} />
            <Route path="/whatif" element={<WhatIfPage />} />
            <Route path="/streaming" element={<StreamingPage />} />
            <Route path="/breakouts" element={<BreakoutsPage />} />
            <Route path="/accuracy" element={<AccuracyPage />} />
            <Route path="/assistant" element={<AssistantPage />} />
            <Route path="/forecast" element={<GeminiForecastPage />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </AppContext.Provider>
  )
}
