import type { ProfileInput } from '@/api/types'

// The Setup form keeps everything as plain text. This file turns that text into the JSON the
// API expects, and turns the API's validation errors back into messages per field.

export interface FactRow {
  text: string
  expected_answer: string
  expected_value: string
  tolerance: string
  unit: string
  expected_source_url: string
}

export interface FormState {
  id: string
  name: string
  aliases: string
  domains: string
  wikipedia_title: string
  contact_emails: string
  competitors: string // one per line: Name | alias, alias | domain, domain
  knowledge_sources: string
  faq_source_urls: string
  fact_questions: FactRow[]
  generic_questions: string
}

export const EMPTY_FACT_ROW: FactRow = {
  text: '',
  expected_answer: '',
  expected_value: '',
  tolerance: '',
  unit: '',
  expected_source_url: '',
}

export const EMPTY_FORM: FormState = {
  id: '',
  name: '',
  aliases: '',
  domains: '',
  wikipedia_title: '',
  contact_emails: '',
  competitors: '',
  knowledge_sources: '',
  faq_source_urls: '',
  fact_questions: [{ ...EMPTY_FACT_ROW }],
  generic_questions: '',
}

export function lines(text: string): string[] {
  return text.split('\n').map((line) => line.trim()).filter(Boolean)
}

function commaList(text: string): string[] {
  return text.split(',').map((item) => item.trim()).filter(Boolean)
}

/** "Kemira Oyj" -> "kemira-oyj" (the backend wants a lowercase slug). */
export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

function code(prefix: string, index: number): string {
  return `${prefix}${String(index + 1).padStart(2, '0')}`
}

export type FieldErrors = Record<string, string[]>

function addError(errors: FieldErrors, path: string, message: string): void {
  ;(errors[path] ??= []).push(message)
}

function parseNumber(errors: FieldErrors, path: string, text: string): number | undefined {
  if (text.trim() === '') return undefined
  const value = Number(text.replace(',', '.'))
  if (Number.isNaN(value)) {
    addError(errors, path, 'Must be a number.')
    return undefined
  }
  return value
}

function parseFactRows(rows: FactRow[], errors: FieldErrors): ProfileInput['fact_questions'] {
  const used = rows.filter((row) => Object.values(row).some((value) => value.trim() !== ''))
  return used.map((row, i) => {
    const base = `fact_questions.${i}`
    const fact: ProfileInput['fact_questions'][number] = {
      code: code('Q', i),
      text: row.text.trim(),
      expected_answer: row.expected_answer.trim(),
    }
    const value = parseNumber(errors, `${base}.expected_value`, row.expected_value)
    const tolerance = parseNumber(errors, `${base}.tolerance`, row.tolerance)
    if (value !== undefined) fact.expected_value = value
    if (tolerance !== undefined) fact.tolerance = tolerance
    if (row.unit.trim()) fact.unit = row.unit.trim()
    if (row.expected_source_url.trim()) fact.expected_source_url = row.expected_source_url.trim()
    return fact
  })
}

/** Builds the API body. Checks only what cannot be sent as JSON (numbers); the backend schema does the rest. */
export function buildProfile(form: FormState): { profile: ProfileInput; errors: FieldErrors } {
  const errors: FieldErrors = {}
  const competitors = lines(form.competitors).map((line) => {
    const [name = '', aliases = '', domains = ''] = line.split('|')
    return { name: name.trim(), aliases: commaList(aliases), domains: commaList(domains) }
  })
  const profile: ProfileInput = {
    id: form.id.trim() || slugify(form.name),
    name: form.name.trim(),
    aliases: lines(form.aliases),
    domains: lines(form.domains),
    wikipedia_title: form.wikipedia_title.trim() || null,
    contact_emails: lines(form.contact_emails),
    faq_source_urls: lines(form.faq_source_urls),
    competitors,
    knowledge_sources: lines(form.knowledge_sources),
    fact_questions: parseFactRows(form.fact_questions, errors),
    generic_questions: lines(form.generic_questions).map((text, i) => ({ code: code('G', i), text })),
  }
  return { profile, errors }
}

interface ApiFieldError {
  loc: (string | number)[]
  msg: string
}

function isFieldErrorList(detail: unknown): detail is ApiFieldError[] {
  return Array.isArray(detail) && detail.every((e) => e && Array.isArray(e.loc) && typeof e.msg === 'string')
}

/** FastAPI 422 `detail` -> { "fact_questions.0.text": ["..."], "": ["model-level message"] }. */
export function apiErrors(detail: unknown): FieldErrors {
  const errors: FieldErrors = {}
  if (!isFieldErrorList(detail)) return errors
  for (const err of detail) {
    const path = err.loc.slice(1).join('.') // drop the leading "body"
    const message = err.msg.replace(/^Value error, /, '')
    const empty = message === 'Field required' || message.startsWith('String should have at least 1')
    const noItems = message.startsWith('List should have at least 1 item')
    addError(errors, path, empty ? 'Required.' : noItems ? 'Add at least one.' : message)
  }
  return errors
}

/** Messages for a field, including its list items ("aliases" also matches "aliases.1"). */
export function errorsFor(errors: FieldErrors, field: string): string[] {
  return Object.entries(errors).flatMap(([path, messages]) => {
    if (path === field) return messages
    if (!path.startsWith(`${field}.`)) return []
    const [first, ...rest] = path.slice(field.length + 1).split('.')
    const index = Number(first)
    const where = Number.isInteger(index)
      ? `line ${index + 1}${rest.length ? ` (${rest.join('.')})` : ''}: `
      : `${[first, ...rest].join('.')}: `
    return messages.map((message) => `${where}${message}`)
  })
}
