import type {
  CompanyCreated,
  JobStartOut,
  ProfileInput,
  SettingsOut,
  TestEmailOut,
} from './types'

const BASE_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  detail: unknown // the API's `detail`: a string, or a list of field errors on a 422

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

// The admin password lives in the AdminProvider; it hands it to this module.
// It is never logged.
let adminToken: string | null = null
let onUnauthorized: () => void = () => {}

export function setAdminToken(token: string | null): void {
  adminToken = token
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

async function errorBody(res: Response): Promise<{ message: string; detail: unknown }> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return { message: body.detail, detail: body.detail }
    if (body.detail) return { message: 'The data was not accepted.', detail: body.detail }
  } catch {
    // not JSON: fall through
  }
  return { message: `${res.status} ${res.statusText}`, detail: undefined }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  const sentToken = adminToken
  if (sentToken) headers.set('X-Admin-Token', sentToken)

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers })
  if (!res.ok) {
    // An admin request refused with 401: the stored password is wrong or changed.
    if (res.status === 401 && sentToken && path !== '/api/admin/login') onUnauthorized()
    const { message, detail } = await errorBody(res)
    throw new ApiError(res.status, message, detail)
  }
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  login: (password: string) =>
    request<{ ok: boolean }>('/api/admin/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  startJob: (companyId: string, job: string) =>
    request<JobStartOut>(`/api/companies/${companyId}/jobs`, {
      method: 'POST',
      body: JSON.stringify({ job }),
    }),
  patchSettings: (
    companyId: string,
    body: { monitoring_enabled?: boolean; emails_enabled?: boolean; contact_emails?: string[] },
  ) =>
    request<SettingsOut>(`/api/companies/${companyId}/settings`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  sendTestEmail: (companyId: string) =>
    request<TestEmailOut>(`/api/companies/${companyId}/test-email`, { method: 'POST' }),
  createCompany: (profile: ProfileInput) =>
    request<CompanyCreated>('/api/companies', { method: 'POST', body: JSON.stringify(profile) }),
  importYaml: (yaml: string) =>
    request<CompanyCreated>('/api/companies/import', {
      method: 'POST',
      body: JSON.stringify({ yaml }),
    }),
}
