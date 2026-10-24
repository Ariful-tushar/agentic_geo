import {
  Activity,
  BarChart3,
  Bell,
  FileQuestion,
  Info,
  LayoutDashboard,
  PlusCircle,
  ScanSearch,
  Settings,
  Swords,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'

export const NAV_ITEMS = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/accuracy', label: 'Accuracy details', icon: BarChart3 },
  { to: '/competitors', label: 'Competitors', icon: Swords },
  { to: '/alerts', label: 'Alerts', icon: Bell },
  { to: '/faq', label: 'FAQ', icon: FileQuestion },
  { to: '/readiness', label: 'AI-readiness', icon: ScanSearch },
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/setup', label: 'Setup', icon: PlusCircle },
  { to: '/about', label: 'About', icon: Info },
]

export function Brand({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center gap-3 font-semibold tracking-tight text-foreground', className)}>
      <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 via-indigo-500 to-cyan-400 shadow-lg shadow-violet-500/30">
        <Activity className="size-5 text-white" />
      </div>
      <span className="text-base">AnswerWatch</span>
    </div>
  )
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="grid gap-2">
      {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200',
              isActive
                ? 'bg-sidebar-primary/15 text-sidebar-primary ring-1 ring-sidebar-primary/20'
                : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground',
            )
          }
        >
          <Icon className="size-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
