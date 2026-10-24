import { toast } from 'sonner'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '@/api/client'
import { useFaqDrafts, usePublicQuestions } from '@/api/hooks'
import type { FaqDraftItem } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useSelectedCompany } from '@/lib/company'
import { dateTime } from '@/lib/format'
import { useAdmin } from '@/lib/admin'

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
  const { isAdmin } = useAdmin()
  const questions = usePublicQuestions(companyId)
  const drafts = useFaqDrafts(companyId)
  const queryClient = useQueryClient()
  const deleteQuestion = useMutation({
    mutationFn: (questionId: string) => {
      if (!companyId) throw new Error('Select a company before deleting a question.')
      return api.deleteFaqQuestion(companyId, questionId)
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['faq-questions', companyId] }),
        queryClient.invalidateQueries({ queryKey: ['faq-drafts', companyId] }),
      ])
      toast.success('Question and its draft were removed.')
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Could not reach the API.'
      toast.error(message)
    },
  })
  const checkQuestions = useMutation({
    mutationFn: () => {
      if (!companyId) throw new Error('Select a company before checking for new questions.')
      return api.startJob(companyId, 'faq')
    },
    onSuccess: () => {
      toast.success('FAQ scan started. New questions will appear after the scan finishes.')
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Could not start the FAQ scan.'
      toast.error(message)
    },
  })

  if (companiesLoading) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">FAQ</h1>
      <p className="text-sm text-muted-foreground">
        The FAQ agent checks configured live FAQ pages hourly and drafts answers from the company's
        own pages. Use “Check for new questions” to scan now, or “Refresh” to reload saved results.
        Nothing is published: copy a draft if you want to use it.
      </p>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <CardTitle>Public questions found</CardTitle>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={questions.isFetching || drafts.isFetching}
              onClick={() => {
                void Promise.all([questions.refetch(), drafts.refetch()])
              }}
            >
              Refresh
            </Button>
            {isAdmin && (
              <Button
                type="button"
                size="sm"
                disabled={checkQuestions.isPending}
                onClick={() => checkQuestions.mutate()}
              >
                {checkQuestions.isPending ? 'Starting scan...' : 'Check for new questions'}
              </Button>
            )}
          </div>
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
                  {isAdmin && <TableHead><span className="sr-only">Actions</span></TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {questions.data.map((q) => (
                  <TableRow key={q.id}>
                    <TableCell className="whitespace-nowrap">{dateTime(q.first_seen_at)}</TableCell>
                    <TableCell className="min-w-56 whitespace-normal">{q.text}</TableCell>
                    <TableCell>
                      {q.source_url === 'Added from dashboard' ? (
                        <span className="text-muted-foreground">{q.source_url}</span>
                      ) : (
                        <a
                          href={q.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-primary underline-offset-2 hover:underline"
                        >
                          {host(q.source_url)}
                        </a>
                      )}
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
                    {isAdmin && (
                      <TableCell>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={deleteQuestion.isPending}
                          onClick={() => {
                            if (
                              window.confirm(
                                `Remove this question and its draft?\n\n${q.text}\n\nIf it remains on a scanned source page, the FAQ agent may find it again.`,
                              )
                            ) {
                              deleteQuestion.mutate(q.id)
                            }
                          }}
                        >
                          Remove
                        </Button>
                      </TableCell>
                    )}
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
