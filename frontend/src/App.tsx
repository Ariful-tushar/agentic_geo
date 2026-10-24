import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/AppLayout'
import { AdminProvider } from '@/lib/admin'
import { CompanyProvider } from '@/lib/company'
import About from '@/pages/About'
import Accuracy from '@/pages/Accuracy'
import Alerts from '@/pages/Alerts'
import AddQuestion from '@/pages/AddQuestion'
import Competitors from '@/pages/Competitors'
import Faq from '@/pages/Faq'
import Overview from '@/pages/Overview'
import Placeholder from '@/pages/Placeholder'
import Readiness from '@/pages/Readiness'
import Settings from '@/pages/Settings'
import Setup from '@/pages/Setup'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
})

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
                <Route path="competitors" element={<Competitors />} />
                <Route path="alerts" element={<Alerts />} />
                <Route path="faq" element={<Faq />} />
                <Route path="add-question" element={<AddQuestion />} />
                <Route path="readiness" element={<Readiness />} />
                <Route path="settings" element={<Settings />} />
                <Route path="setup" element={<Setup />} />
                <Route path="*" element={<Placeholder title="Page not found" step="?" />} />
              </Route>
            </Routes>
          </CompanyProvider>
        </BrowserRouter>
      </AdminProvider>
    </QueryClientProvider>
  )
}
