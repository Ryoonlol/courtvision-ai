import type { ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>
}

export function SectionTitle({ title, kicker, right }: { title: ReactNode; kicker?: string; right?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <div>
        {kicker && <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-brand">{kicker}</div>}
        <h2 className="font-display text-xl font-semibold tracking-wide text-fg">{title}</h2>
      </div>
      {right}
    </div>
  )
}

export function Pill({ children, tone = 'default', title }: { children: ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad' | 'brand' | 'gemini'; title?: string }) {
  const tones: Record<string, string> = {
    default: 'border-line bg-panel-2 text-fg-2',
    good: 'border-good/40 bg-good/10 text-good',
    warn: 'border-warn/40 bg-warn/10 text-warn',
    bad: 'border-bad/40 bg-bad/10 text-bad',
    brand: 'border-brand/40 bg-brand/10 text-brand',
    gemini: 'border-gemini/40 bg-gemini/10 text-gemini',
  }
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} />
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <Card className="flex flex-col items-center gap-3 p-8 text-center">
      <AlertTriangle className="text-bad" size={28} />
      <div className="text-sm text-fg-2">{error.message}</div>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-fg-2 hover:border-brand hover:text-brand">
          <RefreshCw size={14} /> Retry
        </button>
      )}
    </Card>
  )
}

export function Headshot({ src, name, size = 48, ring }: { src?: string | null; name: string; size?: number; ring?: string }) {
  const initials = name.split(' ').map((p) => p[0]).slice(0, 2).join('')
  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-full bg-panel-2"
      style={{ width: size, height: size, boxShadow: ring ? `0 0 0 2px ${ring}` : undefined }}
    >
      <span className="absolute inset-0 flex items-center justify-center font-display text-sm text-muted">{initials}</span>
      {src ? (
        <img src={src} alt={name} loading="lazy" className="absolute inset-0 h-full w-full object-cover object-top"
          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
      ) : null}
    </div>
  )
}

export function TeamLogo({ src, abbr, size = 20 }: { src?: string | null; abbr?: string | null; size?: number }) {
  if (!src) return <span className="font-mono text-[10px] text-muted">{abbr}</span>
  return <img src={src} alt={abbr ?? ''} width={size} height={size} className="inline-block object-contain" loading="lazy" />
}

export function StatusChip({ status }: { status?: string | null }) {
  if (!status || status.startsWith('Active')) return <Pill tone="good">Active</Pill>
  if (status.startsWith('Out') || status === 'Suspended') return <Pill tone="bad">{status}</Pill>
  return <Pill tone="warn">{status}</Pill>
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="num font-display text-2xl font-semibold" style={{ color: accent }}>{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  )
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-panel p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1 text-xs font-medium transition ${value === o.value ? 'bg-brand text-ink' : 'text-fg-2 hover:text-fg'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
