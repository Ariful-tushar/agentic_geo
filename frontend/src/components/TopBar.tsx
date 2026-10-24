import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Lock, LogOut, Menu, Play } from 'lucide-react'
import { toast } from 'sonner'
import { ApiError, api } from '@/api/client'
import { useCompany } from '@/api/hooks'
import { Brand, SidebarNav } from '@/components/Sidebar'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { useAdmin } from '@/lib/admin'
import { useSelectedCompany } from '@/lib/company'

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Could not reach the API.'
}

function MonitoringSwitch({ companyId }: { companyId: string }) {
  const { data } = useCompany(companyId)
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (enabled: boolean) => api.patchSettings(companyId, { monitoring_enabled: enabled }),
    onSuccess: (result) => {
      toast.success(result.monitoring_enabled ? 'Monitoring is on.' : 'Monitoring is off.')
      void queryClient.invalidateQueries({ queryKey: ['company', companyId] })
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
    },
    onError: (err) => toast.error(errorText(err)),
  })
  return (
    <label className="flex items-center gap-2 text-sm">
      <Switch
        checked={data?.monitoring_enabled ?? false}
        disabled={data === undefined || mutation.isPending}
        onCheckedChange={(checked) => mutation.mutate(checked)}
      />
      <span className="hidden sm:inline">Monitoring</span>
    </label>
  )
}

// "Run now" starts the `daily` job: Ax, then the alert email and the daily report.
function RunNowButton({ companyId }: { companyId: string }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => api.startJob(companyId, 'daily'),
    onSuccess: () => {
      toast.success('Daily run started. New data appears when it finishes.')
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
      void queryClient.invalidateQueries({ queryKey: ['company', companyId] })
    },
    onError: (err) => toast.error(errorText(err)),
  })
  return (
    <Button size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
      <Play />
      <span className="hidden sm:inline">Run now</span>
    </Button>
  )
}

export function TopBar() {
  const { companies, companyId, setCompanyId } = useSelectedCompany()
  const { isAdmin, openLogin, logout } = useAdmin()
  const [menuOpen, setMenuOpen] = useState(false)
  const items = companies.map((c) => ({ value: c.id, label: c.name }))

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur-xl">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Open menu"
          onClick={() => setMenuOpen(true)}
        >
          <Menu />
        </Button>
        <div className="md:hidden">
          <Brand />
        </div>

        <Select
          items={items}
          value={companyId}
          onValueChange={(value) => value && setCompanyId(value)}
          disabled={items.length === 0}
        >
          <SelectTrigger className="min-w-36 border-border bg-card shadow-sm" aria-label="Company">
            <SelectValue placeholder="Company" />
          </SelectTrigger>
          <SelectContent>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="ml-auto flex items-center gap-3">
          {isAdmin && companyId && <MonitoringSwitch companyId={companyId} />}
          {isAdmin && companyId && <RunNowButton companyId={companyId} />}
          {isAdmin ? (
            <Button variant="outline" size="sm" onClick={logout} className="border-border bg-card text-foreground hover:bg-muted">
              <LogOut />
              <span className="hidden sm:inline">Log out</span>
            </Button>
          ) : (
            <Button size="sm" onClick={openLogin}>
              <Lock />
              <span className="hidden sm:inline">Admin login</span>
            </Button>
          )}
        </div>
      </div>
      <p className="border-t border-border bg-muted/50 px-4 py-1 text-xs text-muted-foreground">
        Independent demo, not affiliated with the selected company.
      </p>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-64 border-sidebar-border bg-sidebar text-sidebar-foreground">
          <SheetHeader>
            <SheetTitle>
              <Brand />
            </SheetTitle>
          </SheetHeader>
          <div className="px-4">
            <SidebarNav onNavigate={() => setMenuOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
    </header>
  )
}
