import { useState } from 'react'
import { useAlerts, useEngines } from '@/api/hooks'
import type { AlertOut } from '@/api/types'
import { AlertCompare } from '@/components/AlertCompare'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useSelectedCompany } from '@/lib/company'
import { longDate } from '@/lib/format'
import { alertLabel } from '@/lib/verdict'

const RANGES = [30, 90]

export default function Alerts() {
  const { companyId, isLoading: companiesLoading } = useSelectedCompany()
  const [days, setDays] = useState(30)
  const [warningsOnly, setWarningsOnly] = useState(false)
  const [open, setOpen] = useState<AlertOut | null>(null)
  const engines = useEngines()
  const alerts = useAlerts(companyId, days)

  if (companiesLoading) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>

  const labels = Object.fromEntries((engines.data ?? []).map((e) => [e.id, e.label]))
  const shown = (alerts.data ?? []).filter((a) => !warningsOnly || a.severity === 'warning')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Alerts</h1>
        <div className="flex flex-wrap gap-1">
          <Button size="sm" variant={warningsOnly ? 'default' : 'outline'} onClick={() => setWarningsOnly(!warningsOnly)}>
            Warnings only
          </Button>
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
        <CardContent className="pt-4">
          {alerts.isError ? (
            <p className="text-sm text-destructive">Could not load the alerts.</p>
          ) : alerts.isPending ? (
            <Skeleton className="h-48 w-full" />
          ) : shown.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No alerts in this period. An alert appears when an answer changes between two daily runs.
            </p>
          ) : (
            <ul className="divide-y">
              {shown.map((alert) => (
                <li key={alert.id}>
                  <button
                    type="button"
                    onClick={() => setOpen(alert)}
                    className="flex w-full items-start gap-3 py-3 text-left text-sm hover:bg-muted/50"
                  >
                    <Badge variant={alert.severity === 'warning' ? 'destructive' : 'secondary'}>
                      {alert.severity}
                    </Badge>
                    <div className="min-w-0 space-y-0.5">
                      <div className="font-medium">{alertLabel(alert.kind)}</div>
                      <div>{alert.summary}</div>
                      <div className="text-xs text-muted-foreground">
                        {longDate(alert.run_date)} · {labels[alert.engine] ?? alert.engine} ·{' '}
                        {alert.question_code}: {alert.question_text}
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <AlertCompare alert={open} onClose={() => setOpen(null)} />
    </div>
  )
}
