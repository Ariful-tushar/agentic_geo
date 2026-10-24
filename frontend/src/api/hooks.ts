import { useQuery } from '@tanstack/react-query'
import { useAdmin } from '@/lib/admin'
import { api } from './client'
import type {
  AlertOut,
  AnswerDetail,
  CompanyDetail,
  CompanyListItem,
  CompetitorEventOut,
  CompetitorSummaryPoint,
  DetailsOut,
  EmailLogOut,
  EngineOut,
  FaqDraftItem,
  Health,
  PublicQuestionOut,
  RunOut,
  TodayItem,
  TrendPoint,
} from './types'

export const useEngines = () =>
  useQuery({ queryKey: ['engines'], queryFn: () => api.get<EngineOut[]>('/api/engines') })

export const useCompanies = () =>
  useQuery({ queryKey: ['companies'], queryFn: () => api.get<CompanyListItem[]>('/api/companies') })

export const useCompany = (id: string | null, pollUntilOnboarded = false) => {
  // the admin token changes what the API returns (contact emails), so it is part of the key
  const { isAdmin } = useAdmin()
  return useQuery({
    queryKey: ['company', id, isAdmin],
    queryFn: () => api.get<CompanyDetail>(`/api/companies/${id}`),
    enabled: id !== null,
    // while a new profile is being built, ask again every 3 seconds until it is ready or failed
    refetchInterval: (query) =>
      pollUntilOnboarded && !['ready', 'failed'].includes(query.state.data?.onboarding_status ?? '')
        ? 3000
        : false,
  })
}

export const useTrend = (id: string | null, days: number) =>
  useQuery({
    queryKey: ['trend', id, days],
    queryFn: () => api.get<TrendPoint[]>(`/api/companies/${id}/accuracy/trend?days=${days}`),
    enabled: id !== null,
  })

export const useToday = (id: string | null) =>
  useQuery({
    queryKey: ['today', id],
    queryFn: () => api.get<TodayItem[]>(`/api/companies/${id}/accuracy/today`),
    enabled: id !== null,
  })

export const useCompetitorEvents = (id: string | null, days = 30) =>
  useQuery({
    queryKey: ['competitor-events', id, days],
    queryFn: () => api.get<CompetitorEventOut[]>(`/api/companies/${id}/competitors/events?days=${days}`),
    enabled: id !== null,
  })

export const useCompetitorSummary = (id: string | null, days = 14) =>
  useQuery({
    queryKey: ['competitor-summary', id, days],
    queryFn: () => api.get<CompetitorSummaryPoint[]>(`/api/companies/${id}/competitors/summary?days=${days}`),
    enabled: id !== null,
  })

export const useAlerts = (id: string | null, days = 30) =>
  useQuery({
    queryKey: ['alerts', id, days],
    queryFn: () => api.get<AlertOut[]>(`/api/companies/${id}/alerts?days=${days}`),
    enabled: id !== null,
  })

export const useHealth = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<Health>('/api/health'),
    retry: false,
    refetchInterval: (query) => (query.state.data?.status === 'ok' ? false : 5000),
  })

export const useDetails = (id: string | null, engine: string | null, from: string, to: string) =>
  useQuery({
    queryKey: ['details', id, engine, from, to],
    queryFn: () =>
      api.get<DetailsOut>(
        `/api/companies/${id}/accuracy/details?engine=${engine}&from=${from}&to=${to}`,
      ),
    enabled: id !== null && engine !== null,
  })

export const useAnswer = (answerId: string | null) =>
  useQuery({
    queryKey: ['answer', answerId],
    queryFn: () => api.get<AnswerDetail>(`/api/answers/${answerId}`),
    enabled: answerId !== null,
  })

export const useRuns = (id: string | null, limit = 10) =>
  useQuery({
    queryKey: ['runs', id, limit],
    queryFn: () => api.get<RunOut[]>(`/api/companies/${id}/runs?limit=${limit}`),
    enabled: id !== null,
  })

export const useEmails = (id: string | null) => {
  // recipients are only returned to the admin, so the admin state is part of the key
  const { isAdmin } = useAdmin()
  return useQuery({
    queryKey: ['emails', id, isAdmin],
    queryFn: () => api.get<EmailLogOut[]>(`/api/companies/${id}/emails?limit=20`),
    enabled: id !== null,
  })
}

export const usePublicQuestions = (id: string | null) =>
  useQuery({
    queryKey: ['faq-questions', id],
    queryFn: () => api.get<PublicQuestionOut[]>(`/api/companies/${id}/faq/questions`),
    enabled: id !== null,
  })

export const useFaqDrafts = (id: string | null) =>
  useQuery({
    queryKey: ['faq-drafts', id],
    queryFn: () => api.get<FaqDraftItem[]>(`/api/companies/${id}/faq/drafts`),
    enabled: id !== null,
  })
