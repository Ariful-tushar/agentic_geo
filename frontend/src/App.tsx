import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/AppLayout'
import { AdminProvider } from '@/lib/admin'
import { CompanyProvider } from '@/lib/company'
import About from '@/pages/About'
import Accuracy from '@/pages/Accuracy'
import Overview from '@/pages/Overview'
import Placeholder from '@/pages/Placeholder'
import Settings from '@/pages/Settings'
import Setup from '@/pages/Setup'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
})

const LATER_PAGES = [
  { path: 'competitors', title: 'Competitors', step: 'D4.2' },
  { path: 'alerts', title: 'Alerts', step: 'D4.2' },
  { path: 'faq', title: 'FAQ', step: 'D5.1' },
  { path: 'readiness', title: 'AI-readiness', step: 'D5.2' },
]

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AdminProvider>
        <BrowserRouter>
          <CompanyProvider>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<Overview />} />
                <Route path="about" element={<About />} />
                <Route path="accuracy" element={<Accuracy />} />
                <Route path="settings" element={<Settings />} />
                <Route path="setup" element={<Setup />} />
                {LATER_PAGES.map(({ path, title, step }) => (
                  <Route key={path} path={path} element={<Placeholder title={title} step={step} />} />
                ))}
                <Route path="*" element={<Placeholder title="Page not found" step="?" />} />
              </Route>
            </Routes>
          </CompanyProvider>
        </BrowserRouter>
      </AdminProvider>
    </QueryClientProvider>
  )
}
