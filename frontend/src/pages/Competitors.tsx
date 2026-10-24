import { useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useCompetitorEvents, useCompetitorSummary, useEngines } from '@/api/hooks'
import type { CompetitorEventOut, CompetitorSummaryPoint, EngineOut } from '@/api/types'
import { AnswerPanel } from '@/components/AnswerPanel'
import { engineColor } from '@/components/TrendChart'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useSelectedCompany } from '@/lib/company'
import { lastDays, percent, shortDate, todayHelsinki } from '@/lib/format'
import { eventHeadline } from '@/lib/verdict'

const RANGES = [7, 14, 30]
const NOTHING = 'Nothing found by the competitor monitor.'

type Row = { date: string } & Record<string, number | string | null>

// One row per calendar day; a day without data stays null, so the line is not drawn across it.
// The value is the share of generic answers that name the company; the counts go to the tooltip.
function buildRows(points: CompetitorSummaryPoint[], engineIds: string[], days: number): Row[] {
  return lastDays(days, todayHelsinki()).map((date) => {
    const row: Row = { date }
    for (const id of engineIds) row[id] = null
    for (const p of points) {
      if (p.date !== date || p.n_answers === 0) continue
      row[p.engine] = p.n_mentioned / p.n_answers
      row[`${p.engine}:counts`] = `${p.n_mentioned} of ${p.n_answers}`
    }
    return row
  })
}

function MentionChart({
  points,
  engines,
  days,
}: {
  points: CompetitorSummaryPoint[]
  engines: EngineOut[]
  days: number
}) {
  const withData = new Set(points.map((p) => p.engine))
  const shown = engines.filter((e) => withData.has(e.id))
  const labels = Object.fromEntries(shown.map((e) => [e.id, e.label]))
  const rows = buildRows(
    points,
    shown.map((e) => e.id),
    days,
  )
  if (shown.length === 0)
    return <p className="text-sm text-muted-foreground">No answers to the general questions yet.</p>
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={16} tick={{ fontSize: 12 }} />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickFormatter={percent}
            tick={{ fontSize: 12 }}
          />
          <Tooltip
            labelFormatter={(label) => shortDate(String(label))}
            formatter={(value, name, item) => [
              `${percent(Number(value))} (${item.payload[`${String(name)}:counts`]})`,
              labels[String(name)] ?? name,
            ]}
          />
          <Legend formatter={(value) => labels[String(value)] ?? value} />
          {shown.map((e, index) => (
            <Line
              key={e.id}
              dataKey={e.id}
              name={e.id}
              type="monotone"
              stroke={engineColor(e.id, index)}
              strokeWidth={2}
              dot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function ReportText({ event }: { event: CompetitorEventOut }) {
  if (event.status === 'new')
    return <span className="text-muted-foreground">Waiting for the competitor agent.</span>
  if (event.report_status === 'nothing_found')
    return <span className="text-muted-foreground">{event.report ?? NOTHING}</span>
  return <span>{event.report}</span>
}

function EventList({
  events,
  labels,
  onOpen,
}: {
  events: CompetitorEventOut[]
  labels: Record<string, string>
  onOpen: (answerId: string) => void
}) {
  if (events.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        No events in this period. An event appears when a competitor is named before the company, or the
        company is not named at all.
      </p>
    )
  return (
    <ul className="divide-y">
      {events.map((event) => (
        <li key={event.id} className="space-y-1 py-3 text-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <div className="font-medium">
              {eventHeadline(event.kind, event.competitors, event.company_rank)}
            </div>
            <div className="text-xs text-muted-foreground">
              {shortDate(event.run_date)} · {labels[event.engine] ?? event.engine}
            </div>
          </div>
          <div className="text-muted-foreground">
            {event.question_code}: {event.question_text}
          </div>
          <p>
            <ReportText event={event} />
          </p>
          <button
            type="button"
            onClick={() => onOpen(event.answer_id)}
            className="text-xs text-primary underline"
          >
            Show the AI's answer
          </button>
        </li>
      ))}
    </ul>
  )
}

export default function Competitors() {
  const { companyId, isLoading: companiesLoading } = useSelectedCompany()
  const [days, setDays] = useState(14)
  const [engine, setEngine] = useState<string | null>(null)
  const [answerId, setAnswerId] = useState<string | null>(null)
  const engines = useEngines()
  const summary = useCompetitorSummary(companyId, days)
  const events = useCompetitorEvents(companyId, days)

  if (companiesLoading || engines.isPending) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>

  const labels = Object.fromEntries((engines.data ?? []).map((e) => [e.id, e.label]))
  const engineIds = [...new Set((events.data ?? []).map((e) => e.engine))]
  const shownEvents = (events.data ?? []).filter((e) => engine === null || e.engine === engine)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Competitors</h1>
        <div className="flex gap-1">
          {RANGES.map((range) => (
            <Button
              key={range}
              size="sm"
              variant={range === days ? 'default' : 'outline'}
              onClick={() => setDays(range)}
            >
              {range} days
            </Button>
          ))}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Is the company named in the answers?</CardTitle>
          <p className="text-sm text-muted-foreground">
            Share of the general questions (no fixed answer) whose answer names the company, per day.
          </p>
        </CardHeader>
        <CardContent>
          {summary.isError ? (
            <p className="text-sm text-destructive">Could not load the chart.</p>
          ) : summary.isPending ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <MentionChart points={summary.data} engines={engines.data ?? []} days={days} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="space-y-2">
          <CardTitle>Who was ahead, and why</CardTitle>
          <div className="flex flex-wrap gap-1">
            <Button size="sm" variant={engine === null ? 'default' : 'outline'} onClick={() => setEngine(null)}>
              All engines
            </Button>
            {engineIds.map((id) => (
              <Button
                key={id}
                size="sm"
                variant={engine === id ? 'default' : 'outline'}
                onClick={() => setEngine(id)}
              >
                {labels[id] ?? id}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {events.isError ? (
            <p className="text-sm text-destructive">Could not load the events.</p>
          ) : events.isPending ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <EventList events={shownEvents} labels={labels} onOpen={setAnswerId} />
          )}
        </CardContent>
      </Card>

      <AnswerPanel answerId={answerId} onClose={() => setAnswerId(null)} />
    </div>
  )
}
