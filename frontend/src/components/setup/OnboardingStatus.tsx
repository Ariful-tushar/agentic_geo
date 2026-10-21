import { useCompany } from '@/api/hooks'
import type { CompanyCreated } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useSelectedCompany } from '@/lib/company'
import { useNavigate } from 'react-router-dom'

// Shown after a profile was saved: what was stored, and the onboarding status (polled every 3 s).
export function OnboardingStatus({ result }: { result: CompanyCreated }) {
  const company = useCompany(result.company_id, true)
  const { setCompanyId } = useSelectedCompany()
  const navigate = useNavigate()
  const status = company.data?.onboarding_status ?? 'pending'

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {result.created ? 'Profile created' : 'Profile updated'}: {result.company_id}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>
          Questions added: {result.questions_added}, kept as they were: {result.questions_kept}.
          Competitors added: {result.competitors_added}. Knowledge sources added: {result.sources_added}.
        </p>
        <div className="flex items-center gap-2">
          <span>Knowledge base:</span>
          {status === 'ready' ? (
            <Badge>Ready</Badge>
          ) : status === 'failed' ? (
            <Badge variant="destructive">Failed</Badge>
          ) : result.job_error && status === 'pending' ? (
            <Badge variant="outline">Not started</Badge>
          ) : (
            <Badge variant="outline">Building knowledge base…</Badge>
          )}
        </div>
        {status === 'failed' && company.data?.onboarding_error && (
          <p className="text-destructive">{company.data.onboarding_error}</p>
        )}
        {result.job_error && (
          <p className="text-destructive">
            The profile is saved, but the onboarding job did not start: {result.job_error}
          </p>
        )}
        <Button
          size="sm"
          onClick={() => {
            setCompanyId(result.company_id)
            navigate('/')
          }}
        >
          Open this company
        </Button>
      </CardContent>
    </Card>
  )
}
