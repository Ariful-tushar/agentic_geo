import { toast } from 'sonner'
import { useFaqDrafts, usePublicQuestions } from '@/api/hooks'
import type { FaqDraftItem } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useSelectedCompany } from '@/lib/company'
import { dateTime } from '@/lib/format'

/** The text a person pastes into their own FAQ: the question, the answer, then the sources. */
function draftText(draft: FaqDraftItem): string {
  const sources = draft.source_urls.map((url) => `- ${url}`).join('\n')
  return `${draft.question}\n\n${draft.answer}\n\nSources:\n${sources}`
}

async function copyDraft(draft: FaqDraftItem) {
  try {
    await navigator.clipboard.writeText(draftText(draft))
    toast.success('Copied to the clipboard.')
  } catch {
    // the clipboard is blocked in some browsers (for example on plain http pages)
    toast.error('Could not copy. Select the text and copy it by hand.')
  }
}

function host(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

export default function Faq() {
  const { companyId, isLoading: companiesLoading } = useSelectedCompany()
  const questions = usePublicQuestions(companyId)
  const drafts = useFaqDrafts(companyId)

  if (companiesLoading) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">FAQ</h1>
      <p className="text-sm text-muted-foreground">
        The FAQ agent reads public questions about the company's field and drafts answers from the
        company's own pages. Nothing is published: copy a draft if you want to use it.
      </p>

      <Card>
        <CardHeader>
          <CardTitle>Public questions found</CardTitle>
        </CardHeader>
        <CardContent>
          {questions.isError ? (
            <p className="text-sm text-destructive">Could not load the questions.</p>
          ) : questions.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : questions.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No public questions yet. They appear after the FAQ agent has run.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Found</TableHead>
                  <TableHead>Question</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Relevant</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {questions.data.map((q) => (
                  <TableRow key={q.id}>
                    <TableCell className="whitespace-nowrap">{dateTime(q.first_seen_at)}</TableCell>
                    <TableCell className="min-w-56 whitespace-normal">{q.text}</TableCell>
                    <TableCell>
                      <a
                        href={q.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        {host(q.source_url)}
                      </a>
                    </TableCell>
                    <TableCell>
                      {q.relevant === null ? (
                        '–'
                      ) : (
                        <Badge variant={q.relevant ? 'default' : 'secondary'}>
                          {q.relevant ? 'Yes' : 'No'}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="min-w-48 whitespace-normal text-muted-foreground">
                      {q.relevance_reason ?? ''}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>FAQ drafts</CardTitle>
        </CardHeader>
        <CardContent>
          {drafts.isError ? (
            <p className="text-sm text-destructive">Could not load the drafts.</p>
          ) : drafts.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : drafts.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No drafts yet. A draft is written for a relevant question when the company's own pages
              contain the answer.
            </p>
          ) : (
            <ul className="divide-y">
              {drafts.data.map((draft) => (
                <li key={draft.id} className="space-y-2 py-4 first:pt-0 last:pb-0">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-medium">{draft.question}</h3>
                    <Button size="sm" variant="outline" onClick={() => copyDraft(draft)}>
                      Copy
                    </Button>
                  </div>
                  <p className="text-sm">{draft.answer}</p>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span>Sources:</span>
                    {draft.source_urls.map((url) => (
                      <a
                        key={url}
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        className="break-all text-primary underline-offset-2 hover:underline"
                      >
                        {url}
                      </a>
                    ))}
                    <span>· drafted {dateTime(draft.created_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
