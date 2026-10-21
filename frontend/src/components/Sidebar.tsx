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

export function Brand() {
  return (
    <div className="flex items-center gap-2 font-semibold">
      <Activity className="size-5 text-primary" />
      AnswerWatch
    </div>
  )
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="grid gap-1">
      {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors',
              isActive
                ? 'bg-primary/10 font-medium text-primary'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
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
