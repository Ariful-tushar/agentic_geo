import { useState } from 'react'
import type { FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/api/client'
import { useAdmin } from '@/lib/admin'

export function LoginDialog() {
  const { loginOpen, closeLogin, login } = useAdmin()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function onOpenChange(open: boolean) {
    if (open) return
    setPassword('')
    setError(null)
    closeLogin()
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(password)
      setPassword('')
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? 'Wrong password.' : 'Login failed. Is the API running?')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={loginOpen} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Admin login</DialogTitle>
            <DialogDescription>
              Needed to run jobs, switch monitoring and create profiles.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="admin-password">Password</Label>
            <Input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button type="submit" disabled={busy || password === ''}>
              {busy ? 'Checking…' : 'Log in'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
