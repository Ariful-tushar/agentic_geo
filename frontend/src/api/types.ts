// Types mirror the Pydantic models in backend/app/schemas/api.py.
// Dates are ISO strings ("2026-10-21"); ids are UUID strings.

export interface EngineOut {
  id: string
  label: string
  web_search: boolean
  enabled: boolean
}

export interface RunOut {
  id: string
  kind: string
  mode: string
  status: string
  trigger: string
  run_date: string
  started_at: string
  finished_at: string | null
  summary: Record<string, unknown>
}

export interface CompanyListItem {
  id: string
  name: string
  onboarding_status: string
  monitoring_enabled: boolean
  last_run: RunOut | null
}

export interface CompetitorOut {
  id: string
  name: string
  aliases: string[]
  domains: string[]
  active: boolean
}

export interface QuestionOut {
  id: string
  code: string
  kind: string
  text: string
  expected_answer: string | null
  expected_value: number | null
  tolerance: number | null
  unit: string | null
  expected_source_url: string | null
}

export interface SourceOut {
  url: string
  status: string
  last_built_at: string | null
  active: boolean
}

export interface CompanyDetail {
  id: string
  name: string
  aliases: string[]
  domains: string[]
  wikipedia_title: string | null
  contact_email_count: number
  // only present when the request carried a valid admin token
  contact_emails: string[] | null
  faq_source_urls: string[]
  monitoring_enabled: boolean
  emails_enabled: boolean
  onboarding_status: string
  onboarding_error: string | null
  competitors: CompetitorOut[]
  questions: QuestionOut[]
  knowledge_sources: SourceOut[]
  last_run: RunOut | null
}

export interface TrendPoint {
  date: string
  engine: string
  accuracy: number
  simulated: boolean // seeded demo history, not a real run
}

export interface TodayItem {
  engine: string
  date: string
  accuracy: number
  n_questions: number
  previous_date: string | null
  previous_accuracy: number | null
  delta: number | null
}

export interface AlertOut {
  id: string
  run_date: string
  kind: string
  severity: string
  engine: string
  question_code: string
  question_text: string
  summary: string
  before_answer_id: string | null
  after_answer_id: string | null
}

export interface Health {
  status: string
  db: boolean
}

export interface JobStartOut {
  job: string
  company_id: string
  runner: string
  status: string
  detail: string
}

export interface SettingsOut {
  company_id: string
  monitoring_enabled: boolean
  emails_enabled: boolean
  contact_emails: string[]
}

export interface EmailLogOut {
  id: string
  kind: 'daily_report' | 'alert' | 'test'
  subject: string
  status: 'sent' | 'failed' | 'skipped'
  error: string | null
  sent_at: string | null
  created_at: string
  recipient_count: number
  recipients: string[] | null // only for the admin
}

export interface TestEmailOut {
  status: 'sent' | 'failed' | 'skipped'
  detail: string
}

export interface DetailCell {
  answer_id: string
  status: 'scored' | 'error' | 'unscored'
  verdict: string | null
  score: number | null
}

export interface DetailRow {
  question_id: string
  code: string
  text: string
  cells: Record<string, DetailCell> // key = ISO date; missing key = no answer that day
}

export interface DetailsOut {
  engine: string
  date_from: string
  date_to: string
  dates: string[]
  simulated_dates: string[] // demo history days: no answers are stored for them
  rows: DetailRow[]
}

export interface ScoreOut {
  verdict: string
  score: number
  reason: string | null
  quote: string | null
  quote_verified: boolean
  method: string
}

export interface CitationOut {
  url: string
  title: string | null
  domain: string | null
  owner: string
}

export interface WhyOut {
  source_type: string
  source_url: string | null
  evidence_quote: string | null
  explanation: string | null
  suggested_fix: string | null
}

export interface PreviousAnswer {
  answer_id: string
  run_date: string
  text: string | null
  verdict: string | null
  score: number | null
}

export interface AnswerDetail {
  id: string
  engine: string
  run_date: string
  asked_at: string
  question: QuestionOut
  text: string | null
  error: string | null
  score: ScoreOut | null
  citations: CitationOut[]
  why: WhyOut | null
  previous: PreviousAnswer | null
}

export interface CompanyCreated {
  company_id: string
  created: boolean
  questions_added: number
  questions_kept: number
  competitors_added: number
  sources_added: number
  job: JobStartOut | null
  job_error: string | null
}

// the profile JSON that POST /api/companies expects (backend ProfileIn)
export interface ProfileInput {
  id: string
  name: string
  aliases: string[]
  domains: string[]
  wikipedia_title: string | null
  contact_emails: string[]
  faq_source_urls: string[]
  competitors: { name: string; aliases: string[]; domains: string[] }[]
  knowledge_sources: string[]
  fact_questions: {
    code: string
    text: string
    expected_answer: string
    expected_value?: number
    tolerance?: number
    unit?: string
    expected_source_url?: string
  }[]
  generic_questions: { code: string; text: string }[]
}
