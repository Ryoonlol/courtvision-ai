import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { api } from '../lib/api'
import { useDebounced } from '../lib/hooks'
import type { PlayerHit } from '../lib/types'
import { Headshot } from './ui'

/** Searchable player combobox (keyboard: arrows + enter, escape closes). */
export function PlayerSearch({ onSelect, placeholder = 'Search players…', accent }: {
  onSelect: (p: PlayerHit) => void
  placeholder?: string
  accent?: string
}) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [hits, setHits] = useState<PlayerHit[]>([])
  const [active, setActive] = useState(0)
  const [loading, setLoading] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const dq = useDebounced(q, 180)

  useEffect(() => {
    if (!open) return
    let live = true
    setLoading(true)
    api.search(dq).then((h) => { if (live) { setHits(h); setActive(0) } }).catch(() => live && setHits([]))
      .finally(() => live && setLoading(false))
    return () => { live = false }
  }, [dq, open])

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const choose = (p: PlayerHit) => { onSelect(p); setQ(''); setOpen(false) }

  return (
    <div ref={box} className="relative w-full">
      <div className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 focus-within:border-brand" style={accent ? { borderLeft: `3px solid ${accent}` } : undefined}>
        <Search size={15} className="text-muted" />
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
            if (e.key === 'Enter' && hits[active]) choose(hits[active])
            if (e.key === 'Escape') setOpen(false)
          }}
          placeholder={placeholder}
          className="w-full bg-transparent text-sm text-fg placeholder:text-muted focus:outline-none"
          aria-label={placeholder}
        />
      </div>
      {open && (
        <div className="scrollbar-thin absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-lg border border-line bg-panel-2 shadow-2xl">
          {loading && hits.length === 0 && <div className="p-3 text-xs text-muted">Searching…</div>}
          {!loading && hits.length === 0 && <div className="p-3 text-xs text-muted">No players found</div>}
          {hits.map((h, i) => (
            <button
              key={h.id}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(h)}
              className={`flex w-full items-center gap-3 px-3 py-2 text-left ${i === active ? 'bg-brand/10' : ''}`}
            >
              <Headshot src={h.headshot} name={h.name} size={30} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-fg">{h.name}</div>
                <div className="text-[11px] text-muted">{h.team_abbr} · {h.position ?? '—'}</div>
              </div>
              {h.rank && <span className="num font-mono text-[11px] text-muted">#{h.rank}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
