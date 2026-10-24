import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useSelectedCompany } from '@/lib/company'
import { useAdmin } from '@/lib/admin'

export default function AddQuestion() {
  const { companyId, isLoading: companiesLoading } = useSelectedCompany()
  const { isAdmin, openLogin } = useAdmin()
  const [questionText, setQuestionText] = useState('')

  const addQuestion = useMutation({
    mutationFn: () => {
      if (!companyId) throw new Error('Select a company before adding a question.')
      return api.addFaqQuestion(companyId, { text: questionText })
    },
    onSuccess: (result) => {
      setQuestionText('')
      toast.success(result.detail)
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Could not reach the API.'
      toast.error(message)
    },
  })

  if (companiesLoading) return <Skeleton className="h-48 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Add a question</h1>
        <p className="text-sm text-muted-foreground">
          Submit a question to the public source page. It will appear in FAQ results only after the
          hourly scan finds it and the FAQ agent checks whether it is relevant.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>New FAQ question</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              addQuestion.mutate()
            }}
          >
            <div className="grid gap-2">
              <Label htmlFor="new-faq-question">Question</Label>
              <Input
                id="new-faq-question"
                value={questionText}
                onChange={(event) => setQuestionText(event.target.value)}
                minLength={10}
                maxLength={300}
                placeholder="Enter a water-industry question…"
                disabled={!isAdmin || addQuestion.isPending}
              />
              <p className="text-xs text-muted-foreground">
                Use 10–300 characters. The source page update is queued through GitHub Actions;
                FAQ results update after a later scan, not immediately.
              </p>
            </div>
            {isAdmin ? (
              <Button
                type="submit"
                disabled={addQuestion.isPending || questionText.trim().length < 10}
              >
                {addQuestion.isPending ? 'Adding…' : 'Add question'}
              </Button>
            ) : (
              <Button type="button" variant="outline" onClick={openLogin}>
                Admin login to add
              </Button>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
