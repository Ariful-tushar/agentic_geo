import { useAnswer } from '@/api/hooks'
import type { AlertOut } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { shortDate } from '@/lib/format'
import { alertLabel, verdictStyle } from '@/lib/verdict'

function Side({ title, answerId, highlight }: { title: string; answerId: string | null; highlight?: boolean }) {
  const { data, isPending, isError } = useAnswer(answerId)
  const verdict = data?.score?.verdict ?? null
  return (
    <div className={`space-y-2 rounded-lg border p-3 ${highlight ? 'border-primary/40' : ''}`}>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {title}
          {data && `: ${shortDate(data.run_date)}`}
        </span>
        {verdict && (
          <span className={`rounded px-2 py-0.5 font-medium ${verdictStyle(verdict).className}`}>
            {verdictStyle(verdict).label}
          </span>
        )}
      </div>
      {answerId === null ? (
        <p className="text-sm text-muted-foreground">No earlier answer.</p>
      ) : isError ? (
        <p className="text-sm text-destructive">Could not load this answer.</p>
      ) : isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <p className="whitespace-pre-wrap text-sm">{data.error ? `Error: ${data.error}` : data.text}</p>
      )}
    </div>
  )
}

export function AlertCompare({ alert, onClose }: { alert: AlertOut | null; onClose: () => void }) {
  return (
    <Sheet open={alert !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="data-[side=right]:w-full data-[side=right]:sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>{alert ? `${alertLabel(alert.kind)} · ${alert.question_code}` : 'Alert'}</SheetTitle>
          <SheetDescription>{alert?.summary}</SheetDescription>
        </SheetHeader>
        {alert && (
          <div className="space-y-3 overflow-y-auto px-4 pb-6">
            <p className="text-sm font-medium">{alert.question_text}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Side title="Before" answerId={alert.before_answer_id} />
              <Side title="Now" answerId={alert.after_answer_id} highlight />
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
