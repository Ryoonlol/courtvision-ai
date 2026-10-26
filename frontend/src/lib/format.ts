import type { CatKey } from './types'

export const CATS: { key: CatKey; label: string; pct?: boolean; lowerBetter?: boolean }[] = [
  { key: 'pts', label: 'PTS' },
  { key: 'reb', label: 'REB' },
  { key: 'ast', label: 'AST' },
  { key: 'stl', label: 'STL' },
  { key: 'blk', label: 'BLK' },
  { key: 'fg3m', label: '3PM' },
  { key: 'fg_pct', label: 'FG%', pct: true },
  { key: 'ft_pct', label: 'FT%', pct: true },
  { key: 'tov', label: 'TO', lowerBetter: true },
]
export const CAT_LABEL: Record<string, string> = Object.fromEntries(CATS.map((c) => [c.key, c.label]))

export function fmt(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(digits)
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function fmtCat(key: string, v: number | null | undefined, digits = 1): string {
  return key === 'fg_pct' || key === 'ft_pct' ? fmtPct(v) : fmt(v, digits)
}

export function signed(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}

export function shortDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** Diverging tint for a z-score cell: blue = helps, red = hurts, transparent near 0. */
export function zTint(z: number | null | undefined): string {
  if (z === null || z === undefined || Number.isNaN(z)) return 'transparent'
  const a = Math.min(Math.abs(z) / 2.5, 1) * 0.42
  if (Math.abs(z) < 0.25) return 'transparent'
  return z > 0 ? `rgba(46,155,214,${a})` : `rgba(239,91,91,${a})`
}
