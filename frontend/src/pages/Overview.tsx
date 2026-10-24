import { useState } from 'react'
import { useAlerts, useCompany, useEngines, useToday, useTrend } from '@/api/hooks'
import type { AlertOut, RunOut, TodayItem } from '@/api/types'
import { engineColor, TrendChart } from '@/components/TrendChart'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useSelectedCompany } from '@/lib/company'
import { dateTime, percent, shortDate } from '@/lib/format'

const RANGES = [7, 14, 30]

function DeltaText({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="text-muted-foreground">no earlier day yet</span>
  const points = Math.round(delta * 100)
  if (points === 0) return <span className="text-muted-foreground">no change</span>
  return (
    <span className={points > 0 ? 'text-emerald-300' : 'text-red-300'}>
      {points > 0 ? '+' : ''}
      {points} pts vs previous day
    </span>
  )
}

function TodayCards({ items, labels }: { items: TodayItem[]; labels: Record<string, string> }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No accuracy data yet.</p>
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item, index) => (
        <Card key={item.engine} size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <span
                className="size-3 shrink-0 rounded-full"
                style={{ backgroundColor: engineColor(item.engine, index) }}
              />
              {labels[item.engine] ?? item.engine}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold">{percent(item.accuracy)}</div>
            <div className="mt-1 text-xs">
              <DeltaText delta={item.delta} />
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {shortDate(item.date)} · {item.n_questions} questions
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function AlertList({ alerts }: { alerts: AlertOut[] }) {
  if (alerts.length === 0)
    return <p className="text-sm text-muted-foreground">No alerts yet. Alerts appear when an answer changes.</p>
  return (
    <ul className="divide-y">
      {alerts.map((alert) => (
        <li key={alert.id} className="flex items-start gap-3 py-2 text-sm">
          <Badge variant={alert.severity === 'warning' ? 'destructive' : 'secondary'}>
            {alert.severity}
          </Badge>
          <div className="min-w-0">
            <div>{alert.summary}</div>
            <div className="text-xs text-muted-foreground">
              {shortDate(alert.run_date)} · {alert.engine} · {alert.question_code}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

function LastRun({ run }: { run: RunOut | null | undefined }) {
  if (!run) return <p className="text-sm text-muted-foreground">No run yet.</p>
  return (
    <div className="space-y-1 text-sm">
      <div className="flex items-center gap-2">
        <Badge variant={run.status === 'completed' ? 'secondary' : 'outline'}>{run.status}</Badge>
        <span className="text-muted-foreground">{run.kind}</span>
      </div>
      <div>{dateTime(run.started_at)}</div>
      <div className="text-xs text-muted-foreground">{run.trigger} run</div>
    </div>
  )
}

export default function Overview() {
  const { companyId, isLoading: companiesLoading } = useSelectedCompany()
  const [days, setDays] = useState(7)
  const engines = useEngines()
  const trend = useTrend(companyId, days)
  const today = useToday(companyId)
  const alerts = useAlerts(companyId)
  const company = useCompany(companyId)

  if (companiesLoading) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet. Create one on the Setup page.</p>

  const labels = Object.fromEntries((engines.data ?? []).map((e) => [e.id, e.label]))
  // only real days count: simulated demo history does not make a trend of real runs
  const dataDays = new Set((trend.data ?? []).filter((p) => !p.simulated).map((p) => p.date)).size
  const latestAlerts = [...(alerts.data ?? [])]
    .sort((a, b) => b.run_date.localeCompare(a.run_date))
    .slice(0, 5)

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{company.data?.name ?? 'Overview'}: overview</h1>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>Accuracy per day</CardTitle>
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
        </CardHeader>
        <CardContent>
          {trend.isError ? (
            <p className="text-sm text-destructive">Could not load the trend.</p>
          ) : trend.isPending || engines.isPending ? (
            <Skeleton className="h-72 w-full" />
          ) : (
            <>
              <TrendChart points={trend.data} engines={engines.data ?? []} days={days} />
              {dataDays < 2 && (
                <p className="mt-2 text-sm text-muted-foreground">
                  Trend appears after the second daily run.
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h2 className="font-medium">Today's accuracy</h2>
        {today.isError ? (
          <p className="text-sm text-destructive">Could not load today's accuracy.</p>
        ) : today.isPending ? (
          <Skeleton className="h-28 w-full" />
        ) : (
          <TodayCards items={today.data} labels={labels} />
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Latest alerts</CardTitle>
          </CardHeader>
          <CardContent>
            {alerts.isPending ? <Skeleton className="h-16 w-full" /> : <AlertList alerts={latestAlerts} />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Last run</CardTitle>
          </CardHeader>
          <CardContent>
            {company.isPending ? <Skeleton className="h-16 w-full" /> : <LastRun run={company.data?.last_run} />}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
