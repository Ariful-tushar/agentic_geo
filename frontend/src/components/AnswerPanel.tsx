import { AlertTriangle } from 'lucide-react'
import { useAnswer } from '@/api/hooks'
import type { AnswerDetail } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { shortDate } from '@/lib/format'
import { ownerLabel, verdictStyle, whyLabel } from '@/lib/verdict'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  )
}

function Link({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="break-all text-primary underline">
      {children}
    </a>
  )
}

function VerdictBadge({ verdict }: { verdict: string | null }) {
  const style = verdictStyle(verdict)
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${style.className}`}>{style.label}</span>
}

function SideBySide({ answer }: { answer: AnswerDetail }) {
  const { previous } = answer
  if (!previous) {
    return <p className="text-muted-foreground">No earlier answer from this engine for this question.</p>
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1 rounded-lg border p-3">
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>Previous: {shortDate(previous.run_date)}</span>
          <VerdictBadge verdict={previous.verdict} />
        </div>
        <p className="whitespace-pre-wrap">{previous.text ?? 'No answer stored.'}</p>
      </div>
      <div className="space-y-1 rounded-lg border border-primary/40 p-3">
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>This day: {shortDate(answer.run_date)}</span>
          <VerdictBadge verdict={answer.score?.verdict ?? null} />
        </div>
        <p className="whitespace-pre-wrap">{answer.text ?? 'No answer stored.'}</p>
      </div>
    </div>
  )
}

function Body({ answer }: { answer: AnswerDetail }) {
  const { question, score, why } = answer
  return (
    <div className="space-y-5 overflow-y-auto px-4 pb-6 text-sm">
      <Section title="Question">
        <p className="font-medium">
          {question.code}: {question.text}
        </p>
      </Section>

      <Section title="Expected answer">
        <p>{question.expected_answer ?? 'None (generic question).'}</p>
        {question.expected_source_url && (
          <p className="text-xs">
            Source: <Link href={question.expected_source_url}>{question.expected_source_url}</Link>
          </p>
        )}
      </Section>

      <Section title={`The AI's answer (${shortDate(answer.run_date)})`}>
        {answer.error ? (
          <p className="text-destructive">The engine returned an error: {answer.error}</p>
        ) : (
          <p className="whitespace-pre-wrap">{answer.text}</p>
        )}
      </Section>

      <Section title="Verdict">
        {score ? (
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <VerdictBadge verdict={score.verdict} />
              <span className="text-xs text-muted-foreground">
                score {score.score}, checked by {score.method === 'numeric' ? 'number rule' : 'the AI judge'}
              </span>
            </div>
            {score.reason && <p>{score.reason}</p>}
            {score.quote && (
              <blockquote className="border-l-2 pl-3 italic text-muted-foreground">
                "{score.quote}"
                {!score.quote_verified && (
                  <span className="ml-2 inline-flex items-center gap-1 not-italic text-amber-700">
                    <AlertTriangle className="size-3.5" />
                    quote not found word for word in the answer
                  </span>
                )}
              </blockquote>
            )}
          </div>
        ) : (
          <p className="text-muted-foreground">Not scored.</p>
        )}
      </Section>

      <Section title="Citations">
        {answer.citations.length === 0 ? (
          <p className="text-muted-foreground">No sources were given with this answer.</p>
        ) : (
          <ul className="space-y-1">
            {answer.citations.map((c) => (
              <li key={c.url} className="flex items-start gap-2">
                <Badge variant="outline">{ownerLabel(c.owner)}</Badge>
                <Link href={c.url}>{c.title || c.url}</Link>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {why && (
        <Section title="Why was it wrong?">
          <p>
            <span className="font-medium">{whyLabel(why.source_type)}.</span> {why.explanation}
          </p>
          {why.source_url && (
            <p className="text-xs">
              Source: <Link href={why.source_url}>{why.source_url}</Link>
            </p>
          )}
          {why.evidence_quote && (
            <blockquote className="border-l-2 pl-3 italic text-muted-foreground">"{why.evidence_quote}"</blockquote>
          )}
          {why.suggested_fix && (
            <p className="rounded-lg bg-primary/5 p-2">
              <span className="font-medium">Suggested fix: </span>
              {why.suggested_fix}
            </p>
          )}
          <p className="text-xs text-muted-foreground">Likely cause, not proof.</p>
        </Section>
      )}

      <Section title="Compared with the previous answer">
        <SideBySide answer={answer} />
      </Section>
    </div>
  )
}

interface Props {
  answerId: string | null
  onClose: () => void
}

export function AnswerPanel({ answerId, onClose }: Props) {
  const { data, isPending, isError } = useAnswer(answerId)
  return (
    <Sheet open={answerId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{data ? `${data.question.code} · ${data.engine}` : 'Answer'}</SheetTitle>
          <SheetDescription>One answer, with its verdict and the reason behind it.</SheetDescription>
        </SheetHeader>
        {isError ? (
          <p className="px-4 text-sm text-destructive">Could not load this answer.</p>
        ) : isPending ? (
          <div className="space-y-3 px-4">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <Body answer={data} />
        )}
      </SheetContent>
    </Sheet>
  )
}
