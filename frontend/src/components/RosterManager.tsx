import { useCallback, useEffect, useState } from 'react'
import { Plus, Shuffle, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import type { Roster } from '../lib/types'

const KEY = 'cv-roster'

/** Saved rosters + the currently selected one (remembered per browser). */
export function useRosters() {
  const [rosters, setRosters] = useState<Roster[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    try { return Number(localStorage.getItem(KEY)) || null } catch { return null }
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const list = await api.rosters()
      setRosters(list)
      setError(null)
      setSelectedId((cur) => (cur && list.some((r) => r.id === cur) ? cur : list[0]?.id ?? null))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { reload() }, [reload])
  useEffect(() => {
    try { if (selectedId) localStorage.setItem(KEY, String(selectedId)) } catch { /* storage unavailable */ }
  }, [selectedId])

  const selected = rosters.find((r) => r.id === selectedId) ?? null

  const save = async (id: number, player_ids: number[]) => {
    setRosters((rs) => rs.map((r) => (r.id === id ? { ...r, player_ids } : r)))  // optimistic
    try {
      const updated = await api.updateRoster(id, { player_ids })
      setRosters((rs) => rs.map((r) => (r.id === id ? updated : r)))
    } catch (e) {
      setError((e as Error).message)
      reload()
    }
  }

  return { rosters, selected, selectedId, setSelectedId, reload, save, loading, error, setError }
}

export function RosterBar({ state }: { state: ReturnType<typeof useRosters> }) {
  const { rosters, selectedId, setSelectedId, reload, setError } = state
  const [mode, setMode] = useState<'idle' | 'new' | 'sample'>('idle')
  const [name, setName] = useState('')
  const [slot, setSlot] = useState(5)
  const [busy, setBusy] = useState(false)

  const run = async (fn: () => Promise<Roster>) => {
    setBusy(true)
    try {
      const r = await fn()
      await reload()
      setSelectedId(r.id)
      setMode('idle')
      setName('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!selectedId) return
    const r = rosters.find((x) => x.id === selectedId)
    if (!window.confirm(`Delete roster "${r?.name}"? This cannot be undone.`)) return
    await api.deleteRoster(selectedId)
    await reload()
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={selectedId ?? ''}
        onChange={(e) => setSelectedId(Number(e.target.value))}
        className="min-w-[180px] rounded-lg border border-line bg-panel px-3 py-2 text-sm text-fg"
        aria-label="Select roster"
      >
        {rosters.length === 0 && <option value="">No saved rosters</option>}
        {rosters.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.player_ids.length}){r.kind !== 'mine' ? ` · ${r.kind}` : ''}</option>)}
      </select>
      {mode === 'idle' && (
        <>
          <button onClick={() => setMode('new')} className="inline-flex items-center gap-1 rounded-lg border border-line px-3 py-2 text-sm text-fg-2 hover:border-brand hover:text-brand"><Plus size={14} /> New roster</button>
          <button onClick={() => { setMode('sample'); setName('Sample Team') }} className="inline-flex items-center gap-1 rounded-lg border border-line px-3 py-2 text-sm text-fg-2 hover:border-brand hover:text-brand"><Shuffle size={14} /> Sample draft</button>
          {selectedId && <button onClick={remove} className="inline-flex items-center gap-1 rounded-lg px-2 py-2 text-sm text-muted hover:text-bad" title="Delete roster"><Trash2 size={14} /></button>}
        </>
      )}
      {mode !== 'idle' && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) return
            run(() => (mode === 'new' ? api.createRoster(name.trim()) : api.sampleRoster(name.trim(), slot)))
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Roster name" maxLength={60}
            className="rounded-lg border border-line bg-panel px-3 py-2 text-sm focus:border-brand focus:outline-none" />
          {mode === 'sample' && (
            <label className="flex items-center gap-1 text-xs text-muted">
              Pick
              <select value={slot} onChange={(e) => setSlot(Number(e.target.value))} className="rounded border border-line bg-panel px-1 py-1 text-sm text-fg">
                {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
              </select>
              of 12 (snake, by per-game value)
            </label>
          )}
          <button disabled={busy} className="rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-ink disabled:opacity-50">{busy ? 'Saving…' : 'Create'}</button>
          <button type="button" onClick={() => setMode('idle')} className="px-2 text-sm text-muted hover:text-fg">Cancel</button>
        </form>
      )}
    </div>
  )
}

const OPP_KEY = 'cv-opponent'

/** Opponent roster selection (any saved roster other than the user's selected one). */
export function useOpponent(rosters: Roster[], mineId: number | null) {
  const [oppId, setOppId] = useState<number | null>(() => {
    try { return Number(localStorage.getItem(OPP_KEY)) || null } catch { return null }
  })
  const choices = rosters.filter((r) => r.id !== mineId)
  const current = choices.find((r) => r.id === oppId) ?? choices.find((r) => r.kind === 'opponent') ?? choices[0] ?? null
  const select = (id: number) => {
    setOppId(id)
    try { localStorage.setItem(OPP_KEY, String(id)) } catch { /* storage unavailable */ }
  }
  return { opponent: current, choices, select }
}

export function OpponentPicker({ state, opp }: { state: ReturnType<typeof useRosters>; opp: ReturnType<typeof useOpponent> }) {
  const [slot, setSlot] = useState(8)
  const [busy, setBusy] = useState(false)
  const create = async () => {
    setBusy(true)
    try {
      const r = await api.sampleRoster(`Opponent (pick ${slot})`, slot)
      await api.updateRoster(r.id, { kind: 'opponent' })
      await state.reload()
      opp.select(r.id)
    } catch (e) {
      state.setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[11px] uppercase tracking-wider text-muted">vs</span>
      <select value={opp.opponent?.id ?? ''} onChange={(e) => opp.select(Number(e.target.value))}
        className="min-w-[180px] rounded-lg border border-line bg-panel px-3 py-2 text-sm text-fg" aria-label="Select opponent roster">
        {opp.choices.length === 0 && <option value="">No opponent roster</option>}
        {opp.choices.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.player_ids.length})</option>)}
      </select>
      <label className="flex items-center gap-1 text-xs text-muted">
        <select value={slot} onChange={(e) => setSlot(Number(e.target.value))} className="rounded border border-line bg-panel px-1 py-1 text-sm text-fg" aria-label="Opponent draft slot">
          {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
        </select>
      </label>
      <button onClick={create} disabled={busy} className="inline-flex items-center gap-1 rounded-lg border border-line px-3 py-2 text-sm text-fg-2 hover:border-brand hover:text-brand disabled:opacity-50">
        <Shuffle size={14} /> {busy ? 'Drafting…' : 'Sample opponent'}
      </button>
    </div>
  )
}
