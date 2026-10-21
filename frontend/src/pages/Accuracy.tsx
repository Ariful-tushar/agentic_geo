import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useDetails, useEngines } from '@/api/hooks'
import type { DetailRow } from '@/api/types'
import { AnswerPanel } from '@/components/AnswerPanel'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useSelectedCompany } from '@/lib/company'
import { lastDays, shortDate, todayHelsinki } from '@/lib/format'
import { cellStyle } from '@/lib/verdict'

const RANGES = [7, 14, 30]

function Legend() {
  const items = [
    ['bg-emerald-100 text-emerald-900', '1', 'correct'],
    ['bg-amber-100 text-amber-900', '½', 'partly correct'],
    ['bg-red-100 text-red-900', '0', 'wrong'],
    ['bg-muted text-muted-foreground', '–', 'no answer, error or not scored'],
  ]
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map(([cls, symbol, label]) => (
        <li key={label} className="flex items-center gap-1.5">
          <span className={`inline-flex size-5 items-center justify-center rounded ${cls}`}>{symbol}</span>
          {label}
        </li>
      ))}
    </ul>
  )
}

interface MatrixProps {
  rows: DetailRow[]
  dates: string[]
  onOpen: (answerId: string) => void
}

function Matrix({ rows, dates, onOpen }: MatrixProps) {
  // on a phone the newest day (the right-hand end) is the interesting one
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scroller.current) scroller.current.scrollLeft = scroller.current.scrollWidth
  }, [rows, dates.length])

  return (
    <div ref={scroller} className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 min-w-36 bg-card p-2 text-left font-medium sm:min-w-48">Question</th>
            {dates.map((date) => (
              <th key={date} className="px-1 py-2 text-center text-xs font-normal text-muted-foreground">
                {shortDate(date)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.question_id}>
              <th
                scope="row"
                className="sticky left-0 z-10 max-w-64 border-t bg-card p-2 text-left font-normal"
              >
                <span className="font-medium">{row.code}</span> {row.text}
              </th>
              {dates.map((date) => {
                const cell = row.cells[date]
                if (!cell) {
                  return (
                    <td key={date} className="border-t p-1 text-center text-muted-foreground/50">
                      ·
                    </td>
                  )
                }
                const style = cellStyle(cell.status, cell.verdict)
                return (
                  <td key={date} className="border-t p-1 text-center">
                    <button
                      type="button"
                      title={`${row.code}, ${shortDate(date)}: ${style.label}`}
                      aria-label={`${row.code}, ${shortDate(date)}: ${style.label}`}
                      onClick={() => onOpen(cell.answer_id)}
                      className={`size-8 min-w-8 rounded font-medium transition-colors ${style.className}`}
                    >
                      {style.symbol}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Accuracy() {
  const { companyId, isLoading: companiesLoading } = useSelectedCompany()
  const engines = useEngines()
  const [params, setParams] = useSearchParams()

  const enabled = (engines.data ?? []).filter((e) => e.enabled)
  const engine = enabled.find((e) => e.id === params.get('engine'))?.id ?? enabled[0]?.id ?? null
  const days = RANGES.includes(Number(params.get('days'))) ? Number(params.get('days')) : 14
  const answerId = params.get('answer')

  const dates = lastDays(days, todayHelsinki())
  const details = useDetails(companyId, engine, dates[0], dates[dates.length - 1])

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  if (companiesLoading || engines.isPending) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Accuracy details</h1>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>Fact questions by day</CardTitle>
          <div className="flex gap-1">
            {RANGES.map((range) => (
              <Button
                key={range}
                size="sm"
                variant={range === days ? 'default' : 'outline'}
                onClick={() => update({ days: String(range) })}
              >
                {range} days
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <Tabs value={engine} onValueChange={(value) => update({ engine: String(value), answer: null })}>
            <TabsList className="h-auto! flex-wrap justify-start">
              {enabled.map((e) => (
                <TabsTrigger key={e.id} value={e.id}>
                  {e.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <Legend />
          {details.isError ? (
            <p className="text-sm text-destructive">Could not load the details.</p>
          ) : details.isPending ? (
            <Skeleton className="h-72 w-full" />
          ) : details.data.rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">This company has no fact questions.</p>
          ) : (
            <Matrix
              rows={details.data.rows}
              dates={dates}
              onOpen={(id) => update({ answer: id })}
            />
          )}
          <p className="text-xs text-muted-foreground">
            Click a cell to see the answer, the reason and the previous day. A dot means no run that day.
          </p>
        </CardContent>
      </Card>

      <AnswerPanel answerId={answerId} onClose={() => update({ answer: null })} />
    </div>
  )
}
