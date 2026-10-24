import { Outlet } from 'react-router-dom'
import { LoginDialog } from '@/components/LoginDialog'
import { Brand, SidebarNav } from '@/components/Sidebar'
import { TopBar } from '@/components/TopBar'
import { WakingBanner } from '@/components/WakingBanner'
import { Toaster } from '@/components/ui/sonner'

export function AppLayout() {
  return (
    <div className="min-h-screen bg-transparent text-foreground">
      <div className="mx-auto flex min-h-screen max-w-[1800px]">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-sidebar-border bg-sidebar p-4 shadow-[12px_0_40px_rgba(0,0,0,0.12)] md:block">
          <div className="mb-6 rounded-2xl border border-white/10 bg-white/5 px-3 py-3 shadow-inner shadow-white/5">
            <Brand className="text-white" />
          </div>
          <SidebarNav />
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="mx-auto w-full max-w-[1600px]">
            <WakingBanner />
            <TopBar />
            <main className="flex-1 p-4 md:p-6">
              <Outlet />
            </main>
          </div>
        </div>
      </div>
      <LoginDialog />
      <Toaster position="top-right" />
    </div>
  )
}
