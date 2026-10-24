import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { EngineOut, TrendPoint } from '@/api/types'
import { lastDays, longDate, percent, shortDate, todayHelsinki } from '@/lib/format'

// One fixed colour per engine id, so a line keeps its colour on every page.
const ENGINE_COLORS: Record<string, string> = {
  groq_web: '#4f46e5',
  gemini_memory: '#ea580c',
  rag: '#059669',
  openrouter_memory: '#9333ea',
}
const FALLBACK_COLORS = ['#0891b2', '#be185d', '#65a30d']

export function engineColor(engineId: string, index = 0): string {
  return ENGINE_COLORS[engineId] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

type Row = { date: string } & Record<string, number | string | boolean | null>

// One row per calendar day of the range. A day without data has no value (null), so the
// x-axis keeps the gap; the lines use connectNulls={false}, so they are not drawn across it.
function buildRows(points: TrendPoint[], engineIds: string[], days: number): Row[] {
  return lastDays(days, todayHelsinki()).map((date) => {
    const row: Row = { date, simulated: false }
    for (const id of engineIds) row[id] = null
    for (const p of points) {
      if (p.date !== date) continue
      row[p.engine] = p.accuracy
      if (p.simulated) row.simulated = true
    }
    return row
  })
}

interface Props {
  points: TrendPoint[]
  engines: EngineOut[]
  days: number
}

export function TrendChart({ points, engines, days }: Props) {
  // a disabled engine (for example OpenRouter) only shows up if it has data in this range
  const hasData = new Set(points.map((p) => p.engine))
  const shown = engines.filter((e) => e.enabled || hasData.has(e.id))
  const engineIds = shown.map((e) => e.id)
  const labels = Object.fromEntries(shown.map((e) => [e.id, e.label]))
  const rows = buildRows(points, engineIds, days)

  // Simulated demo days are drawn as a grey band with hollow points (see the caption below).
  const simulatedDays = rows.filter((r) => r.simulated).map((r) => r.date)
  const firstReal = points.filter((p) => !p.simulated).map((p) => p.date).sort()[0]

  return (
    <div>
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            minTickGap={16}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
          />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickFormatter={percent}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
          />
          <Tooltip
            labelFormatter={(label) => shortDate(String(label))}
            formatter={(value, name) => [percent(Number(value)), labels[String(name)] ?? name]}
            contentStyle={{
              backgroundColor: 'var(--popover)',
              borderColor: 'var(--border)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--popover-foreground)',
            }}
            labelStyle={{ color: 'var(--popover-foreground)' }}
          />
          {simulatedDays.length > 0 && (
            <ReferenceArea
              x1={simulatedDays[0]}
              x2={simulatedDays[simulatedDays.length - 1]}
              fill="#9ca3af"
              fillOpacity={0.2}
              stroke="none"
              ifOverflow="visible"
            />
          )}
          <Legend
            formatter={(value) => labels[String(value)] ?? value}
            wrapperStyle={{ color: 'var(--muted-foreground)', fontSize: 12 }}
          />
          {engineIds.map((id, index) => (
            <Line
              key={id}
              dataKey={id}
              name={id}
              type="monotone"
              stroke={engineColor(id, index)}
              strokeWidth={2}
              dot={(props) => {
                const { cx, cy, payload, key } = props
                if (cx == null || cy == null) return <g key={key} />
                const color = engineColor(id, index)
                const simulated = Boolean(payload?.simulated)
                return (
                  <circle
                    key={key}
                    cx={cx}
                    cy={cy}
                    r={4}
                    fill={simulated ? 'var(--card)' : color}
                    stroke={color}
                    strokeWidth={simulated ? 2 : 0}
                  />
                )
              }}
              activeDot={{ r: 6 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
    {simulatedDays.length > 0 && (
      <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span aria-hidden className="inline-block h-3 w-5 rounded-sm bg-muted/50" />
        Simulated history (demo), real monitoring since{' '}
        {firstReal ? longDate(firstReal) : '22 Oct 2026'}
      </p>
    )}
    </div>
  )
}
