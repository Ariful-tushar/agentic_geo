const TIMEZONE = 'Europe/Helsinki' // the backend's run_date uses this zone

/** Today's date as "YYYY-MM-DD" in Helsinki time. */
export function todayHelsinki(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIMEZONE }).format(new Date())
}

/** The last `days` calendar days ending at `end`, oldest first, as "YYYY-MM-DD". */
export function lastDays(days: number, end: string): string[] {
  const [y, m, d] = end.split('-').map(Number)
  return Array.from({ length: days }, (_, i) => {
    const date = new Date(Date.UTC(y, m - 1, d - (days - 1 - i)))
    return date.toISOString().slice(0, 10)
  })
}

/** "2026-10-21" -> "21 Oct". */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(
    new Date(Date.UTC(y, m - 1, d)),
  )
}

export function dateTime(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: TIMEZONE,
  }).format(new Date(iso))
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}
