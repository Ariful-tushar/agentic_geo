import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useCompanies } from '@/api/hooks'
import type { CompanyListItem } from '@/api/types'

const STORAGE_KEY = 'answerwatch.company'

interface CompanyState {
  companies: CompanyListItem[]
  companyId: string | null
  setCompanyId: (id: string) => void
  isLoading: boolean
}

const CompanyContext = createContext<CompanyState | null>(null)

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function CompanyProvider({ children }: { children: ReactNode }) {
  const { data, isLoading } = useCompanies()
  const [chosen, setChosen] = useState<string | null>(readStored)
  const companies = useMemo(() => data ?? [], [data])

  // use the stored choice if it still exists, otherwise the first company
  const companyId = companies.find((c) => c.id === chosen)?.id ?? companies[0]?.id ?? null

  useEffect(() => {
    try {
      if (companyId) localStorage.setItem(STORAGE_KEY, companyId)
    } catch {
      // storage blocked: the choice just is not remembered
    }
  }, [companyId])

  const value = useMemo(
    () => ({ companies, companyId, setCompanyId: setChosen, isLoading }),
    [companies, companyId, isLoading],
  )
  return <CompanyContext.Provider value={value}>{children}</CompanyContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSelectedCompany(): CompanyState {
  const ctx = useContext(CompanyContext)
  if (!ctx) throw new Error('useSelectedCompany must be used inside CompanyProvider')
  return ctx
}
