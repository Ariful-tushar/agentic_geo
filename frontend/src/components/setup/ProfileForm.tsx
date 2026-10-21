import { useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '@/api/client'
import type { CompanyCreated } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  EMPTY_FACT_ROW,
  EMPTY_FORM,
  apiErrors,
  buildProfile,
  errorsFor,
  slugify,
} from '@/lib/profileForm'
import type { FactRow, FieldErrors, FormState } from '@/lib/profileForm'

function Field({
  id,
  label,
  hint,
  errors,
  children,
}: {
  id: string
  label: string
  hint?: string
  errors: string[]
  children: ReactNode
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {errors.map((message) => (
        <p key={message} className="text-xs text-destructive">
          {message}
        </p>
      ))}
    </div>
  )
}

function FactRowFields({
  row,
  index,
  errors,
  canRemove,
  onChange,
  onRemove,
}: {
  row: FactRow
  index: number
  errors: FieldErrors
  canRemove: boolean
  onChange: (changes: Partial<FactRow>) => void
  onRemove: () => void
}) {
  const path = `fact_questions.${index}`
  const err = (field: string) => errorsFor(errors, `${path}.${field}`)
  const id = (field: string) => `fact-${index}-${field}`
  return (
    <fieldset className="space-y-3 rounded-lg border p-3">
      <legend className="px-1 text-sm font-medium">Fact question {index + 1}</legend>
      <Field id={id('text')} label="Question" errors={err('text')}>
        <Input id={id('text')} value={row.text} onChange={(e) => onChange({ text: e.target.value })} />
      </Field>
      <Field id={id('answer')} label="Expected answer" errors={err('expected_answer')}>
        <Input
          id={id('answer')}
          value={row.expected_answer}
          onChange={(e) => onChange({ expected_answer: e.target.value })}
        />
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field id={id('value')} label="Number (optional)" errors={err('expected_value')}>
          <Input
            id={id('value')}
            inputMode="decimal"
            value={row.expected_value}
            onChange={(e) => onChange({ expected_value: e.target.value })}
          />
        </Field>
        <Field id={id('tolerance')} label="Tolerance (optional)" errors={err('tolerance')}>
          <Input
            id={id('tolerance')}
            inputMode="decimal"
            value={row.tolerance}
            onChange={(e) => onChange({ tolerance: e.target.value })}
          />
        </Field>
        <Field id={id('unit')} label="Unit (optional)" errors={err('unit')}>
          <Input id={id('unit')} value={row.unit} onChange={(e) => onChange({ unit: e.target.value })} />
        </Field>
      </div>
      <Field id={id('source')} label="Source URL (optional)" errors={err('expected_source_url')}>
        <Input
          id={id('source')}
          value={row.expected_source_url}
          onChange={(e) => onChange({ expected_source_url: e.target.value })}
        />
      </Field>
      {(errors[path] ?? []).map((m) => (
        <p key={m} className="text-xs text-destructive">
          {m}
        </p>
      ))}
      {canRemove && (
        <Button type="button" variant="outline" size="sm" onClick={onRemove}>
          Remove
        </Button>
      )}
    </fieldset>
  )
}

export function ProfileForm({ onSaved }: { onSaved: (result: CompanyCreated) => void }) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [message, setMessage] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => {
      const { profile, errors: localErrors } = buildProfile(form)
      if (Object.keys(localErrors).length > 0) {
        setErrors(localErrors)
        throw new ApiError(0, 'Please fix the fields marked below.')
      }
      return api.createCompany(profile)
    },
    onSuccess: (result) => {
      setErrors({})
      setMessage(null)
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
      onSaved(result)
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 422) {
        const found = apiErrors(err.detail)
        setErrors(found)
        setMessage(
          Object.keys(found).length > 0
            ? 'The profile was not accepted. Fix the fields marked below.'
            : 'The profile was not accepted.',
        )
      } else if (err instanceof ApiError && err.status === 0) {
        setMessage(err.message) // local number errors are already in `errors`
      } else {
        setMessage(err instanceof ApiError ? err.message : 'Could not reach the API.')
      }
    },
  })

  const set = (changes: Partial<FormState>) => setForm((current) => ({ ...current, ...changes }))
  const setRow = (index: number, changes: Partial<FactRow>) =>
    set({ fact_questions: form.fact_questions.map((row, i) => (i === index ? { ...row, ...changes } : row)) })
  const err = (field: string) => errorsFor(errors, field)
  const modelErrors = errors[''] ?? []

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault()
        setErrors({})
        mutation.mutate()
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="name" label="Company name" errors={err('name')}>
          <Input id="name" value={form.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field
          id="id"
          label="Company id"
          hint={`Lowercase slug. Empty = "${slugify(form.name) || 'from the name'}".`}
          errors={form.name.trim() ? err('id') : []}
        >
          <Input id="id" value={form.id} onChange={(e) => set({ id: e.target.value })} />
        </Field>
      </div>

      <Field id="aliases" label="Aliases" hint="One per line, for example “Kemira Oyj”." errors={err('aliases')}>
        <Textarea id="aliases" rows={2} value={form.aliases} onChange={(e) => set({ aliases: e.target.value })} />
      </Field>
      <Field id="domains" label="Domains" hint="One per line, for example kemira.com." errors={err('domains')}>
        <Textarea id="domains" rows={2} value={form.domains} onChange={(e) => set({ domains: e.target.value })} />
      </Field>
      <Field id="wikipedia" label="Wikipedia title" errors={err('wikipedia_title')}>
        <Input
          id="wikipedia"
          value={form.wikipedia_title}
          onChange={(e) => set({ wikipedia_title: e.target.value })}
        />
      </Field>
      <Field
        id="emails"
        label="Contact emails"
        hint="One per line. The daily report and alerts go here."
        errors={err('contact_emails')}
      >
        <Textarea
          id="emails"
          rows={2}
          value={form.contact_emails}
          onChange={(e) => set({ contact_emails: e.target.value })}
        />
      </Field>
      <Field
        id="competitors"
        label="Competitors (at least one)"
        hint="One per line: Name | alias, alias | domain, domain. Example: Ecolab | Nalco Water | ecolab.com"
        errors={err('competitors')}
      >
        <Textarea
          id="competitors"
          rows={4}
          value={form.competitors}
          onChange={(e) => set({ competitors: e.target.value })}
        />
      </Field>
      <Field
        id="sources"
        label="Knowledge source URLs"
        hint="One per line: public pages on the company's site. The knowledge base is built from them."
        errors={err('knowledge_sources')}
      >
        <Textarea
          id="sources"
          rows={4}
          value={form.knowledge_sources}
          onChange={(e) => set({ knowledge_sources: e.target.value })}
        />
      </Field>

      <div className="space-y-3">
        <h3 className="text-sm font-medium">Fact questions (at least one)</h3>
        <p className="text-xs text-muted-foreground">
          Questions have a correct answer and are scored every day. They cannot be changed after saving.
        </p>
        {(errors['fact_questions'] ?? []).map((m) => (
          <p key={m} className="text-xs text-destructive">
            {m}
          </p>
        ))}
        {form.fact_questions.map((row, index) => (
          <FactRowFields
            key={index}
            row={row}
            index={index}
            errors={errors}
            canRemove={form.fact_questions.length > 1}
            onChange={(changes) => setRow(index, changes)}
            onRemove={() => set({ fact_questions: form.fact_questions.filter((_, i) => i !== index) })}
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => set({ fact_questions: [...form.fact_questions, { ...EMPTY_FACT_ROW }] })}
        >
          Add fact question
        </Button>
      </div>

      <Field
        id="generic"
        label="Generic questions"
        hint="One per line. No correct answer; used to watch which companies the AIs name."
        errors={err('generic_questions')}
      >
        <Textarea
          id="generic"
          rows={4}
          value={form.generic_questions}
          onChange={(e) => set({ generic_questions: e.target.value })}
        />
      </Field>
      <Field
        id="faq"
        label="FAQ source URLs"
        hint="One per line: pages with public questions."
        errors={err('faq_source_urls')}
      >
        <Textarea
          id="faq"
          rows={2}
          value={form.faq_source_urls}
          onChange={(e) => set({ faq_source_urls: e.target.value })}
        />
      </Field>

      {modelErrors.map((m) => (
        <p key={m} className="text-sm text-destructive">
          {m}
        </p>
      ))}
      {message && <p className="text-sm text-destructive">{message}</p>}
      <Button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? 'Saving…' : 'Create profile'}
      </Button>
    </form>
  )
}
