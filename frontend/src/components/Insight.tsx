import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

// numbers (optionally signed, %, or 'a -> b'), but not digits inside words like 3PM
const NUM = /((?<![A-Za-z])[+-]?\d+(?:\.\d+)?%?(?:\s?->\s?[+-]?\d+(?:\.\d+)?%?)?(?![A-Za-z]))/g

/** Text with every number emphasised, so the eye lands on the data first. */
export function Emph({ text }: { text: string }) {
  const parts = text.split(NUM)
  return <>{parts.map((p, i) => (i % 2 === 1 ? <b key={i} className="num font-semibold text-fg">{p.replace('->', '→')}</b> : p))}</>
}

/** One-line verdict at the top of every AI panel. */
export function Headline({ text, color, children }: { text: string; color?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="font-display text-xl font-semibold leading-tight md:text-2xl" style={{ color }}>{text}</div>
      {children}
    </div>
  )
}

export function Lead({ text }: { text: string }) {
  return <p className="text-sm text-fg-2"><Emph text={text} /></p>
}

const TONES = {
  good: 'border-good/40 bg-good/10',
  bad: 'border-bad/40 bg-bad/10',
  warn: 'border-warn/40 bg-warn/10',
  neutral: 'border-line bg-panel-2',
}

/** A labelled row of compact chips (e.g. "Secure: BLK 100% · REB 99%"). */
export function ChipRow({ label, items, tone = 'neutral', labelClass = 'text-muted' }: {
  label: string; items: string[]; tone?: keyof typeof TONES; labelClass?: string
}) {
  if (!items.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className={`w-16 shrink-0 text-[11px] font-semibold uppercase tracking-wider ${labelClass}`}>{label}</span>
      {items.map((x) => <span key={x} className={`rounded-md border px-2 py-0.5 text-xs text-fg-2 ${TONES[tone]}`}><Emph text={x} /></span>)}
    </div>
  )
}

/** Short bullet list; each item is meant to fit on one line. */
export function Bullets({ items, dot = 'bg-gemini' }: { items: ReactNode[]; dot?: string }) {
  if (!items.length) return null
  return (
    <ul className="space-y-1">
      {items.map((x, i) => (
        <li key={i} className="flex gap-2 text-sm text-fg-2"><span className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} /><span>{x}</span></li>
      ))}
    </ul>
  )
}

/** Collapsed details: the full reasoning stays one click away instead of on screen. */
export function More({ children, label = 'More details' }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-xs text-gemini hover:underline" aria-expanded={open}>
        {open ? 'Hide details' : label} <ChevronDown size={13} className={`transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && <div className="mt-2 space-y-3 border-l-2 border-gemini/30 pl-3">{children}</div>}
    </div>
  )
}

export function Sub({ title, children, className = 'text-muted' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div>
      <div className={`mb-1 text-[11px] font-semibold uppercase tracking-wider ${className}`}>{title}</div>
      {children}
    </div>
  )
}
