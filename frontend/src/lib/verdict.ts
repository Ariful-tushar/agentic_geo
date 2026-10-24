// How a verdict looks. Colour is never the only signal: every cell also has a symbol and a label.
export interface VerdictStyle {
  label: string
  symbol: string
  className: string
}

const STYLES: Record<string, VerdictStyle> = {
  correct: { label: 'Correct', symbol: '1', className: 'bg-emerald-100 text-emerald-900 hover:bg-emerald-200' },
  partial: { label: 'Partly correct', symbol: '½', className: 'bg-amber-100 text-amber-900 hover:bg-amber-200' },
  wrong: { label: 'Wrong', symbol: '0', className: 'bg-red-100 text-red-900 hover:bg-red-200' },
  no_answer: { label: 'No answer', symbol: '–', className: 'bg-muted text-muted-foreground hover:bg-muted/70' },
}

const ERROR_STYLE: VerdictStyle = {
  label: 'Error, no answer stored',
  symbol: '!',
  className: 'bg-muted text-muted-foreground hover:bg-muted/70',
}

const UNSCORED_STYLE: VerdictStyle = {
  label: 'Not scored yet',
  symbol: '?',
  className: 'bg-muted text-muted-foreground hover:bg-muted/70',
}

export function verdictStyle(verdict: string | null): VerdictStyle {
  return (verdict && STYLES[verdict]) || UNSCORED_STYLE
}

export function cellStyle(status: 'scored' | 'error' | 'unscored', verdict: string | null): VerdictStyle {
  if (status === 'error') return ERROR_STYLE
  if (status === 'unscored') return UNSCORED_STYLE
  return verdictStyle(verdict)
}

const WHY_LABELS: Record<string, string> = {
  cited_page: 'A page the AI cited',
  wikipedia: 'Wikipedia',
  own_site: "The company's own site",
  model_memory: 'Model memory (no sources)',
  not_answered: 'Not answered',
  unknown: 'Unknown',
}

export function whyLabel(sourceType: string): string {
  return WHY_LABELS[sourceType] ?? sourceType
}

const OWNER_LABELS: Record<string, string> = {
  company: 'company',
  competitor: 'competitor',
  third_party: 'third party',
}

export function ownerLabel(owner: string): string {
  return OWNER_LABELS[owner] ?? owner
}

const ALERT_LABELS: Record<string, string> = {
  score_drop: 'Score dropped',
  score_improved: 'Score improved',
  company_dropped: 'Company dropped out of the answer',
  competitor_overtook: 'Competitor overtook the company',
}

export function alertLabel(kind: string): string {
  return ALERT_LABELS[kind] ?? kind
}

/** The "who was ahead" text of a competitor event. */
export function eventHeadline(
  kind: string,
  competitors: { name: string; rank: number }[],
  companyRank: number | null,
): string {
  if (kind === 'company_missing') {
    const names = competitors.map((c) => c.name).join(', ')
    return names ? `Company not mentioned (named: ${names})` : 'Company not mentioned'
  }
  const ahead = competitors.filter((c) => companyRank === null || c.rank < companyRank)
  return `Ahead of the company: ${ahead.map((c) => c.name).join(', ') || 'a competitor'}`
}
