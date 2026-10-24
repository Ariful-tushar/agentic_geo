import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ArrowRight, Check, ExternalLink, LockKeyhole, Waves } from 'lucide-react'
import { toast } from 'sonner'
import { ApiError, api } from '@/api/client'
import { LoginDialog } from '@/components/LoginDialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Toaster } from '@/components/ui/sonner'
import { useSelectedCompany } from '@/lib/company'
import { useAdmin } from '@/lib/admin'

const SOURCE_PAGE_URL = 'https://answerwatch-jade.vercel.app/demo/public-questions.html'

export default function AddQuestion() {
  const { companies, companyId, isLoading: companiesLoading } = useSelectedCompany()
  const { isAdmin, openLogin } = useAdmin()
  const [questionText, setQuestionText] = useState('')
  const companyName = companies.find((company) => company.id === companyId)?.name ?? 'your company'

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
    <div className="min-h-screen overflow-hidden bg-[#f3f0e7] text-[#153b35]">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[34rem] bg-[radial-gradient(ellipse_at_75%_0%,rgba(196,225,202,0.8),transparent_60%)]" />
      <div className="relative mx-auto flex min-h-screen max-w-7xl flex-col px-5 sm:px-8 lg:px-12">
        <header className="flex items-center justify-between border-b border-[#153b35]/15 py-5">
          <a href="/" className="group flex items-center gap-3" aria-label="AnswerWatch home">
            <span className="flex size-10 items-center justify-center rounded-full bg-[#153b35] text-[#d8e9d4]">
              <Waves size={21} strokeWidth={1.8} />
            </span>
            <span>
              <span className="block text-sm font-semibold tracking-[0.16em]">ANSWERWATCH</span>
              <span className="block text-[10px] uppercase tracking-[0.22em] text-[#526c60]">
                Public question desk
              </span>
            </span>
          </a>
          <button
            type="button"
            onClick={isAdmin ? undefined : openLogin}
            className="inline-flex min-h-10 items-center gap-2 rounded-full border border-[#153b35]/20 px-4 text-xs font-medium transition hover:bg-white/70"
          >
            <LockKeyhole size={14} />
            {isAdmin ? 'Admin session active' : 'Admin access'}
          </button>
        </header>

        <main className="grid flex-1 content-center gap-10 py-10 md:py-16 lg:grid-cols-[1.1fr_0.9fr] lg:gap-16">
          <section className="max-w-2xl">
            <div className="mb-6 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#537363]">
              <span className="size-2 rounded-full bg-[#d97858]" />
              Community question intake
            </div>
            <h1 className="max-w-xl font-serif text-5xl leading-[0.98] tracking-[-0.045em] sm:text-6xl lg:text-7xl">
              Good questions
              <span className="block italic text-[#c56548]">move water forward.</span>
            </h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-[#4d6259]">
              Add a question people are asking about water, chemistry, or the industries
              {` ${companyName} `}serves. We’ll put it on the public question page first.
            </p>

            <div className="mt-10 rounded-[1.75rem] border border-[#153b35]/10 bg-[#fffdf7] p-5 shadow-[0_24px_70px_rgba(21,59,53,0.08)] sm:p-8">
              <div className="mb-6 flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#71877a]">
                    New submission
                  </p>
                  <h2 className="mt-2 font-serif text-2xl tracking-tight">What should we ask?</h2>
                </div>
                <span className="rounded-full bg-[#e6eee2] px-3 py-1 text-xs font-medium text-[#315d48]">
                  {companyName}
                </span>
              </div>

              <form
                className="space-y-5"
                onSubmit={(event) => {
                  event.preventDefault()
                  addQuestion.mutate()
                }}
              >
                <div>
                  <label
                    htmlFor="new-faq-question"
                    className="mb-2 block text-sm font-semibold text-[#29483c]"
                  >
                    Your question
                  </label>
                  <textarea
                    id="new-faq-question"
                    value={questionText}
                    onChange={(event) => {
                      setQuestionText(event.target.value)
                      if (addQuestion.isSuccess) addQuestion.reset()
                    }}
                    minLength={10}
                    maxLength={300}
                    rows={4}
                    placeholder="For example: How can cities reduce water loss in their distribution networks?"
                    disabled={!isAdmin || addQuestion.isPending}
                    className="w-full resize-y rounded-2xl border border-[#153b35]/20 bg-white px-4 py-4 text-base leading-6 text-[#153b35] outline-none transition placeholder:text-[#87988e] focus:border-[#397354] focus:ring-4 focus:ring-[#397354]/10 disabled:bg-[#f2f3ef]"
                  />
                  <div className="mt-2 flex items-center justify-between gap-4 text-xs text-[#718077]">
                    <span>Write 10–300 characters. Keep it clear and specific.</span>
                    <span className="shrink-0 tabular-nums">{questionText.length}/300</span>
                  </div>
                </div>

                {addQuestion.isSuccess && (
                  <div
                    role="status"
                    className="flex gap-3 rounded-2xl border border-[#b9d6b7] bg-[#edf5e9] p-4 text-sm leading-6 text-[#315d48]"
                  >
                    <Check className="mt-1 size-4 shrink-0" />
                    <p>{addQuestion.data.detail}</p>
                  </div>
                )}

                {isAdmin ? (
                  <button
                    type="submit"
                    disabled={addQuestion.isPending || questionText.trim().length < 10}
                    className="flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-[#153b35] px-6 text-sm font-semibold text-[#fffdf7] transition hover:bg-[#245448] disabled:cursor-not-allowed disabled:opacity-45 sm:w-auto"
                  >
                    {addQuestion.isPending ? 'Sending to the public page…' : 'Submit question'}
                    {!addQuestion.isPending && <ArrowRight size={17} />}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={openLogin}
                    className="flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-[#153b35] px-6 text-sm font-semibold text-[#fffdf7] transition hover:bg-[#245448] sm:w-auto"
                  >
                    <LockKeyhole size={16} />
                    Log in to submit
                  </button>
                )}
              </form>
              {addQuestion.isError && (
                <p role="alert" className="mt-4 text-sm text-[#a43f31]">
                  {addQuestion.error instanceof ApiError
                    ? addQuestion.error.message
                    : 'Could not reach the API. Please try again.'}
                </p>
              )}
            </div>
          </section>

          <aside className="relative self-center overflow-hidden rounded-[2rem] bg-[#153b35] p-7 text-[#f3f0e7] shadow-[0_30px_90px_rgba(21,59,53,0.18)] sm:p-10">
            <div className="pointer-events-none absolute -right-20 -top-20 size-64 rounded-full border border-white/10" />
            <div className="pointer-events-none absolute -right-10 -top-10 size-44 rounded-full border border-white/10" />
            <div className="relative">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#b6cbb8]">
                What happens next
              </p>
              <h2 className="mt-4 max-w-sm font-serif text-3xl leading-tight tracking-tight sm:text-4xl">
                A question takes the scenic route.
              </h2>

              <ol className="mt-9 space-y-7">
                <li className="flex gap-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#d7e8d2] text-sm font-semibold text-[#153b35]">
                    01
                  </span>
                  <div>
                    <h3 className="font-semibold">Published to the question page</h3>
                    <p className="mt-1 text-sm leading-6 text-[#c3d2c5]">
                      Your submission is added to the public source page—not to the FAQ results.
                    </p>
                  </div>
                </li>
                <li className="flex gap-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#d7e8d2] text-sm font-semibold text-[#153b35]">
                    02
                  </span>
                  <div>
                    <h3 className="font-semibold">Reviewed on the hourly scan</h3>
                    <p className="mt-1 text-sm leading-6 text-[#c3d2c5]">
                      The FAQ agent checks new questions for relevance before they appear in FAQ.
                    </p>
                  </div>
                </li>
                <li className="flex gap-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#d7e8d2] text-sm font-semibold text-[#153b35]">
                    03
                  </span>
                  <div>
                    <h3 className="font-semibold">Drafted only with reliable sources</h3>
                    <p className="mt-1 text-sm leading-6 text-[#c3d2c5]">
                      Relevant questions get a draft only when company information supports an
                      answer.
                    </p>
                  </div>
                </li>
              </ol>

              <a
                href={SOURCE_PAGE_URL}
                target="_blank"
                rel="noreferrer"
                className="mt-9 inline-flex items-center gap-2 text-sm font-medium text-[#d7e8d2] underline decoration-white/35 underline-offset-4 transition hover:text-white"
              >
                Visit the public question page
                <ExternalLink size={15} />
              </a>
            </div>
          </aside>
        </main>

        <footer className="flex flex-col gap-2 border-t border-[#153b35]/15 py-5 text-xs text-[#65776d] sm:flex-row sm:items-center sm:justify-between">
          <span>Independent demo, not affiliated with {companyName}.</span>
          <a href="/" className="inline-flex items-center gap-1.5 hover:text-[#153b35]">
            Back to AnswerWatch <ArrowRight size={13} />
          </a>
        </footer>
      </div>
      <LoginDialog />
      <Toaster position="top-right" />
    </div>
  )
}
