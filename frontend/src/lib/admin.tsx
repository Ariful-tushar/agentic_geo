import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, setAdminToken, setUnauthorizedHandler } from '@/api/client'

const STORAGE_KEY = 'answerwatch.admin'

interface AdminState {
  isAdmin: boolean
  loginOpen: boolean
  openLogin: () => void
  closeLogin: () => void
  login: (password: string) => Promise<void>
  logout: () => void
}

const AdminContext = createContext<AdminState | null>(null)

function readStored(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStored(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(STORAGE_KEY, token)
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // storage blocked: the login simply lasts until the page is reloaded
  }
}

export function AdminProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => {
    const stored = readStored()
    setAdminToken(stored)
    return stored
  })
  const [loginOpen, setLoginOpen] = useState(false)

  const logout = useCallback(() => {
    setAdminToken(null)
    writeStored(null)
    setToken(null)
  }, [])

  // Any admin request answered with 401: forget the password and ask again.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout()
      setLoginOpen(true)
    })
  }, [logout])

  const login = useCallback(async (password: string) => {
    await api.login(password) // throws ApiError(401) on a wrong password
    setAdminToken(password)
    writeStored(password)
    setToken(password)
    setLoginOpen(false)
  }, [])

  const value = useMemo<AdminState>(
    () => ({
      isAdmin: token !== null,
      loginOpen,
      openLogin: () => setLoginOpen(true),
      closeLogin: () => setLoginOpen(false),
      login,
      logout,
    }),
    [token, loginOpen, login, logout],
  )
  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAdmin(): AdminState {
  const ctx = useContext(AdminContext)
  if (!ctx) throw new Error('useAdmin must be used inside AdminProvider')
  return ctx
}
