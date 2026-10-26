import { useEffect, useRef, useState } from 'react'
import { Bot, Send, ShieldCheck, Sparkles, User, Wrench } from 'lucide-react'
import { Bullets, Emph } from '../components/Insight'
import { OpponentPicker, RosterBar, useOpponent, useRosters } from '../components/RosterManager'
import { Card, Pill } from '../components/ui'
import { api } from '../lib/api'
import { useApp } from '../lib/hooks'
import type { ChatMessage } from '../lib/types'

const EXAMPLES = [
  'Who should I start this week?',
  'Who is better for steals and blocks, Dyson Daniels or Jalen Johnson?',
  'Which player should I pick up?',
  'Does trading Rudy Gobert for Jalen Johnson help my team?',
  'How can I increase my chances of winning 5-4?',
  'Any breakout players I should watch?',
]
const STORE = 'cv-chat'

export default function AssistantPage() {
  const { week, meta } = useApp()
  const rs = useRosters()
  const opp = useOpponent(rs.rosters, rs.selectedId)
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try { return (JSON.parse(sessionStorage.getItem(STORE) ?? '[]') as ChatMessage[]).filter((m) => m.content) } catch { return [] }
  })
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    try { sessionStorage.setItem(STORE, JSON.stringify(messages.slice(-40))) } catch { /* storage unavailable */ }
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const send = async (text: string) => {
    const msg = text.trim()
    if (!msg || busy) return
    const history = messages.filter((m) => m.content).map((m) => ({ role: m.role, content: m.content }))
    setMessages((m) => [...m, { role: 'user', content: msg }])
    setInput('')
    setBusy(true)
    try {
      const reply = await api.chat({ message: msg, history, roster_id: rs.selectedId, opponent_roster_id: opp.opponent?.id ?? null, week })
      const { answer, ...meta } = reply
      setMessages((m) => [...m, { ...meta, role: 'assistant', content: answer }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', content: `Sorry — ${(e as Error).message}`, source: 'fallback' }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-[calc(100vh-150px)] min-h-[560px] flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-wide">Ask CourtVision</h1>
          <p className="text-sm text-fg-2">Ask anything. Answers use real CourtVision data.</p>
        </div>
        {meta && (meta.gemini.available
          ? <Pill tone="gemini"><Sparkles size={11} /> {meta.gemini.label} · tool calling</Pill>
          : <Pill tone="warn" title="Install the agy CLI or set GEMINI_API_KEY to enable Gemini"><Wrench size={11} /> Rule-based mode (Gemini unavailable)</Pill>)}
      </div>
      <Card className="flex flex-wrap items-center gap-3 p-3">
        <span className="text-[11px] uppercase tracking-wider text-muted">Context</span>
        <RosterBar state={rs} />
        <OpponentPicker state={rs} opp={opp} />
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col">
        <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-5" aria-live="polite">
          {messages.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gemini/15 text-gemini"><Bot size={28} /></div>
              <div className="font-display text-2xl font-semibold">What do you want to know?</div>
              <div className="flex max-w-3xl flex-wrap justify-center gap-2">
                {EXAMPLES.map((q) => (
                  <button key={q} onClick={() => send(q)} className="rounded-full border border-line px-3 py-1.5 text-sm text-fg-2 hover:border-gemini hover:text-gemini">{q}</button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => <Bubble key={i} m={m} />)}
          {busy && <div className="flex items-center gap-2 text-sm text-gemini"><Sparkles size={14} className="animate-pulse" /> Gemini is calling CourtVision tools… (about 10–30s)</div>}
          <div ref={end} />
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send(input) }} className="flex items-center gap-2 border-t border-line p-3">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about players, your team, trades, matchups…" maxLength={2000}
            className="flex-1 rounded-lg border border-line bg-ink/40 px-3 py-2.5 text-sm focus:border-gemini focus:outline-none" aria-label="Message" />
          {messages.length > 0 && <button type="button" onClick={() => setMessages([])} className="px-2 text-xs text-muted hover:text-fg">Clear</button>}
          <button disabled={busy || !input.trim()} className="flex h-10 w-10 items-center justify-center rounded-lg bg-gemini text-ink disabled:opacity-40" aria-label="Send"><Send size={16} /></button>
        </form>
      </Card>
    </div>
  )
}

/** Assistant reply as a scannable answer: bold first line, then bullets, numbers emphasised. */
function Answer({ text }: { text: string }) {
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  const isBullet = (l: string) => /^([-•*]|\d+\.)\s+/.test(l)
  // the first line is the answer; every following line (bulleted or not) reads as a bullet
  const clean = (l: string) => l.replace(/^([-•*]|\d+\.)\s+/, '').replace(/\*\*/g, '')
  const head = lines.length && !isBullet(lines[0]) ? lines[0] : null
  const rest = head ? lines.slice(1) : lines
  return (
    <div className="space-y-1.5">
      {head && <div className="font-semibold text-fg"><Emph text={clean(head)} /></div>}
      {rest.length > 0 && <Bullets items={rest.map((l) => <Emph text={clean(l)} />)} />}
    </div>
  )
}

function Bubble({ m }: { m: ChatMessage }) {
  const mine = m.role === 'user'
  return (
    <div className={`flex gap-3 ${mine ? 'flex-row-reverse' : ''}`}>
      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${mine ? 'bg-brand/20 text-brand' : 'bg-gemini/15 text-gemini'}`}>
        {mine ? <User size={15} /> : <Bot size={15} />}
      </div>
      <div className={`max-w-[85%] space-y-2 ${mine ? 'text-right' : ''}`}>
        <div className={`inline-block rounded-2xl px-4 py-2.5 text-left text-sm leading-relaxed ${mine ? 'bg-brand/15 text-fg' : 'border border-line bg-panel-2 text-fg'}`}>
          {mine ? m.content : <Answer text={m.content} />}
        </div>
        {!mine && (
          <div className="flex flex-wrap items-center gap-1.5">
            {m.source === 'gemini' ? <Pill tone="gemini"><Sparkles size={10} /> {m.model}</Pill> : <Pill tone="warn"><Wrench size={10} /> rule-based</Pill>}
            {m.tool_calls?.map((t, i) => (
              <Pill key={i} tone={t.ok ? 'default' : 'bad'} title={t.error ?? JSON.stringify(t.args)}>⚙ {t.tool}</Pill>
            ))}
            {m.grounding && <Pill tone={m.grounding.passed ? 'good' : 'warn'} title={m.grounding.ungrounded.join(', ')}><ShieldCheck size={10} /> {m.grounding.numbers_checked} numbers checked</Pill>}
          </div>
        )}
        {m.notice && <div className="text-[11px] text-warn">{m.notice}</div>}
      </div>
    </div>
  )
}
