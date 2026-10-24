import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '@/api/client'
import { useReadinessCheck, useReadinessHistory } from '@/api/hooks'
import type { ReadinessCheckOut, ReadinessFactResult } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useSelectedCompany } from '@/lib/company'
import { useAdmin } from '@/lib/admin'
import { dateTime } from '@/lib/format'

function verdictLabel(verdict: ReadinessFactResult['verdict']): string {
  return verdict.replace('_', ' ')
}

function verdictVariant(verdict: ReadinessFactResult['verdict']) {
  if (verdict === 'correct') return 'default'
  if (verdict === 'partial') return 'secondary'
  return 'destructive'
}

function statusVariant(status: ReadinessCheckOut['status']) {
  if (status === 'done') return 'default'
  if (status === 'failed') return 'destructive'
  return 'secondary'
}

function CheckResults({ check }: { check: ReadinessCheckOut }) {
  if (check.status === 'queued' || check.status === 'running')
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          {check.status === 'queued' ? 'Your check is queued…' : 'Checking the page…'} This page will
          update automatically when the check finishes.
        </CardContent>
      </Card>
    )

  if (check.status === 'failed')
    return (
      <Card>
        <CardHeader>
          <CardTitle>Check could not be completed</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-destructive">
          {check.error ?? 'The check failed without an error message.'}
        </CardContent>
      </Card>
    )

  const results = check.results ?? []
  const missing = check.missing ?? []
  const suggestions = check.suggestions ?? []

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle>AI-readiness result</CardTitle>
            <a
              className="break-all text-sm text-primary underline-offset-2 hover:underline"
              href={check.url}
              target="_blank"
              rel="noreferrer"
            >
              {check.url}
            </a>
          </div>
          <Badge variant="default">Completed</Badge>
        </CardHeader>
        <CardContent>
          <p className="text-lg font-semibold">
            {check.n_answered ?? 0} of {check.n_questions ?? 0} fact questions fully answered
          </p>
          <p className="text-sm text-muted-foreground">
            {check.n_partial ?? 0} partly answered. Wrong or unsupported answers count as missing.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Question-by-question results</CardTitle>
        </CardHeader>
        <CardContent>
          {results.length === 0 ? (
            <p className="text-sm text-muted-foreground">No question results were saved.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Question</TableHead>
                  <TableHead>Page answer</TableHead>
                  <TableHead>Assessment</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((result) => (
                  <TableRow key={result.code}>
                    <TableCell className="min-w-52 whitespace-normal font-medium">
                      {result.question}
                    </TableCell>
                    <TableCell className="min-w-64 whitespace-normal">
                      {result.answer}
                      {result.reason && (
                        <p className="mt-1 text-xs text-muted-foreground">{result.reason}</p>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={verdictVariant(result.verdict)}>
                        {verdictLabel(result.verdict)}
                      </Badge>
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
          <CardTitle>Facts to add or clarify</CardTitle>
        </CardHeader>
        <CardContent>
          {missing.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              The page answered every fact question correctly or partly.
            </p>
          ) : (
            <ul className="space-y-3">
              {missing.map((fact) => (
                <li className="rounded-lg border border-border p-3" key={fact.code}>
                  <p className="font-medium">{fact.question}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Expected fact: {fact.expected_answer || 'Not specified'}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Suggestions</CardTitle>
        </CardHeader>
        <CardContent>
          {suggestions.length !== 3 ? (
            <p className="text-sm text-muted-foreground">No suggestions were saved.</p>
          ) : (
            <ol className="list-decimal space-y-2 pl-5 text-sm">
              {suggestions.map((suggestion, index) => (
                <li key={`${index}-${suggestion}`}>{suggestion}</li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default function Readiness() {
  const { companyId, isLoading: companiesLoading } = useSelectedCompany()
  const { isAdmin, openLogin } = useAdmin()
  const [url, setUrl] = useState('')
  const [checkId, setCheckId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const history = useReadinessHistory(companyId)
  const activeCheck = useReadinessCheck(checkId)
  const startCheck = useMutation({
    mutationFn: () => {
      if (!companyId) throw new Error('Select a company before starting a check.')
      return api.startReadinessCheck(companyId, { url: url.trim() })
    },
    onSuccess: async (check) => {
      setCheckId(check.id)
      await queryClient.invalidateQueries({ queryKey: ['readiness-history', companyId] })
      toast.success('AI-readiness check started.')
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Could not start the check.'
      toast.error(message)
    },
  })

  useEffect(() => {
    if (activeCheck.data && ['done', 'failed'].includes(activeCheck.data.status)) {
      void queryClient.invalidateQueries({ queryKey: ['readiness-history', companyId] })
    }
  }, [activeCheck.data?.status, companyId, queryClient])

  if (companiesLoading) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">AI-readiness</h1>
        <p className="text-sm text-muted-foreground">
          Check whether one public page contains the facts AI systems need to answer questions
          about this company. The page is fetched fresh for each check.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Check a page</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              startCheck.mutate()
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="readiness-url">Page URL</Label>
              <Input
                id="readiness-url"
                type="url"
                required
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://www.kemira.com/company/"
                disabled={!isAdmin || startCheck.isPending}
              />
              <p className="text-xs text-muted-foreground">
                The check uses only the text found on this page, not the company knowledge base.
              </p>
            </div>
            {isAdmin ? (
              <Button type="submit" disabled={startCheck.isPending || !url.trim()}>
                {startCheck.isPending ? 'Starting…' : 'Check AI-readiness'}
              </Button>
            ) : (
              <Button type="button" variant="outline" onClick={openLogin}>
                Admin login to run a check
              </Button>
            )}
          </form>
        </CardContent>
      </Card>

      {activeCheck.isError && (
        <p className="text-sm text-destructive">Could not load the readiness check status.</p>
      )}
      {activeCheck.isPending && checkId && <Skeleton className="h-24 w-full" />}
      {activeCheck.data && <CheckResults check={activeCheck.data} />}

      <Card>
        <CardHeader>
          <CardTitle>Recent checks</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {history.isError ? (
            <p className="text-sm text-destructive">Could not load readiness history.</p>
          ) : history.isPending ? (
            <Skeleton className="h-20 w-full" />
          ) : history.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">No checks have been run yet.</p>
          ) : (
            history.data.map((check) => (
              <button
                className="flex w-full flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3 text-left text-sm hover:bg-muted/50"
                key={check.id}
                type="button"
                onClick={() => setCheckId(check.id)}
              >
                <span className="min-w-0 flex-1 break-all">{check.url}</span>
                <span className="flex items-center gap-2">
                  {check.status === 'done' && (
                    <span className="text-muted-foreground">
                      {check.n_answered}/{check.n_questions} fully answered
                    </span>
                  )}
                  <Badge variant={statusVariant(check.status)}>{check.status}</Badge>
                  <span className="text-xs text-muted-foreground">{dateTime(check.created_at)}</span>
                </span>
              </button>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}
