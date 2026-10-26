import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CATS } from '../lib/format'
import type { CatKey } from '../lib/types'

export const POS = '#2e9bd6'
export const NEG = '#ef5b5b'
export const tooltipStyle = { background: '#172033', border: '1px solid #233047', borderRadius: 10, fontSize: 12, color: '#e6eaf2' }

/** Toggle chips for punted categories (excluded from need weighting). */
export function PuntPicker({ value, onChange }: { value: CatKey[]; onChange: (v: CatKey[]) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="mr-1 text-[11px] uppercase tracking-wider text-muted">Punt</span>
      {CATS.map((c) => {
        const on = value.includes(c.key)
        return (
          <button key={c.key} onClick={() => onChange(on ? value.filter((k) => k !== c.key) : [...value, c.key])}
            title={on ? `Stop punting ${c.label}` : `Punt ${c.label} (ignore it in recommendations)`}
            className={`rounded-md border px-2 py-0.5 text-xs transition ${on ? 'border-bad/50 bg-bad/15 text-bad line-through' : 'border-line text-fg-2 hover:text-fg'}`}>
            {c.label}
          </button>
        )
      })}
    </div>
  )
}

/** Diverging horizontal bars for one value per category (blue = helps, red = hurts). */
export function DivergingCats({ data, height = 300, valueLabel = 'vs avg', format = (v: number) => v.toFixed(2) }: {
  data: { key: CatKey; label: string; value: number; dim?: boolean }[]
  height?: number
  valueLabel?: string
  format?: (v: number) => string
}) {
  const max = Math.max(1, ...data.map((d) => Math.abs(d.value)))
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 0, right: 16, top: 4, bottom: 0 }}>
          <CartesianGrid horizontal={false} stroke="#1b2638" />
          <XAxis type="number" domain={[-max * 1.1, max * 1.1]} stroke="#7d8aa2" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => Number(v).toFixed(0)} />
          <YAxis type="category" dataKey="label" stroke="#b4bfd1" fontSize={11} width={38} tickLine={false} axisLine={false} />
          <ReferenceLine x={0} stroke="#7d8aa2" />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#ffffff08' }} formatter={(v) => [format(Number(v)), valueLabel]} />
          <Bar isAnimationActive={false} dataKey="value" radius={4} barSize={14}>
            {data.map((d) => <Cell key={d.key} fill={d.value >= 0 ? POS : NEG} fillOpacity={d.dim ? 0.3 : 1} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
