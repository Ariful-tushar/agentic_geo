import { Outlet } from 'react-router-dom'
import { LoginDialog } from '@/components/LoginDialog'
import { Brand, SidebarNav } from '@/components/Sidebar'
import { TopBar } from '@/components/TopBar'
import { WakingBanner } from '@/components/WakingBanner'
import { Toaster } from '@/components/ui/sonner'

export function AppLayout() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 border-r p-4 md:block">
        <div className="mb-6 px-3">
          <Brand />
        </div>
        <SidebarNav />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <WakingBanner />
        <TopBar />
        <main className="flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <LoginDialog />
      <Toaster position="top-right" />
    </div>
  )
}
