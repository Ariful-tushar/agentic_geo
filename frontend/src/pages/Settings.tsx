import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, api } from '@/api/client'
import { useCompany, useEmails, useRuns } from '@/api/hooks'
import type { CompanyDetail } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useAdmin } from '@/lib/admin'
import { useSelectedCompany } from '@/lib/company'
import { dateTime } from '@/lib/format'

// Simple on purpose: something@something.something. The backend checks again.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function lines(text: string): string[] {
  return text.split('\n').map((line) => line.trim()).filter(Boolean)
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-2 sm:grid-cols-[10rem_1fr]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

function List({ items }: { items: string[] }) {
  return items.length === 0 ? <span className="text-muted-foreground">none</span> : <>{items.join(', ')}</>
}

function Link({ href }: { href: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="break-all text-primary underline">
      {href}
    </a>
  )
}

function ProfileCard({ company }: { company: CompanyDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="divide-y text-sm">
          <Row label="Name">
            {company.name} <span className="text-muted-foreground">({company.id})</span>
          </Row>
          <Row label="Aliases">
            <List items={company.aliases} />
          </Row>
          <Row label="Domains">
            <List items={company.domains} />
          </Row>
          <Row label="Wikipedia title">{company.wikipedia_title ?? 'none'}</Row>
          <Row label="FAQ source URLs">
            {company.faq_source_urls.length === 0 ? (
              <span className="text-muted-foreground">none</span>
            ) : (
              <ul className="space-y-1">
                {company.faq_source_urls.map((url) => (
                  <li key={url}>
                    <Link href={url} />
                  </li>
                ))}
              </ul>
            )}
          </Row>
          <Row label="Onboarding">
            <Badge variant={company.onboarding_status === 'ready' ? 'secondary' : 'outline'}>
              {company.onboarding_status}
            </Badge>
            {company.onboarding_error && (
              <span className="ml-2 text-destructive">{company.onboarding_error}</span>
            )}
          </Row>
        </dl>
      </CardContent>
    </Card>
  )
}

function ContactEmailsEditor({ company }: { company: CompanyDetail }) {
  const queryClient = useQueryClient()
  const saved = company.contact_emails ?? []
  const [text, setText] = useState(saved.join('\n'))
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (emails: string[]) => api.patchSettings(company.id, { contact_emails: emails }),
    onSuccess: () => {
      toast.success('Contact emails saved.')
      void queryClient.invalidateQueries({ queryKey: ['company', company.id] })
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not reach the API.'),
  })

  function save() {
    const emails = lines(text)
    const bad = emails.find((email) => !EMAIL_RE.test(email))
    if (bad) {
      setError(`"${bad}" is not a valid email address.`)
      return
    }
    setError(null)
    mutation.mutate(emails)
  }

  return (
    <div className="space-y-2">
      <Textarea
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label="Contact emails, one per line"
      />
      <p className="text-xs text-muted-foreground">One address per line. The daily report and alerts go here.</p>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button size="sm" onClick={save} disabled={mutation.isPending}>
        Save emails
      </Button>
    </div>
  )
}

function SettingSwitch({
  company,
  field,
  label,
}: {
  company: CompanyDetail
  field: 'monitoring_enabled' | 'emails_enabled'
  label: string
}) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (value: boolean) => api.patchSettings(company.id, { [field]: value }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['company', company.id] })
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not reach the API.'),
  })
  return (
    <label className="flex items-center gap-3 py-1">
      <Switch
        checked={company[field]}
        disabled={mutation.isPending}
        onCheckedChange={(checked) => mutation.mutate(checked)}
      />
      {label}
    </label>
  )
}

function SwitchesCard({ company }: { company: CompanyDetail }) {
  const { isAdmin, openLogin } = useAdmin()
  return (
    <Card>
      <CardHeader>
        <CardTitle>Monitoring and emails</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {isAdmin ? (
          <>
            <SettingSwitch company={company} field="monitoring_enabled" label="Daily monitoring" />
            <SettingSwitch company={company} field="emails_enabled" label="Report and alert emails" />
            <div className="pt-2">
              <div className="mb-1 font-medium">Contact emails</div>
              {/* the key re-creates the editor when the saved list changes, so the text box resets */}
              <ContactEmailsEditor key={(company.contact_emails ?? []).join('\n')} company={company} />
            </div>
          </>
        ) : (
          <>
            <p>
              Daily monitoring: <b>{company.monitoring_enabled ? 'on' : 'off'}</b>
            </p>
            <p>
              Report and alert emails: <b>{company.emails_enabled ? 'on' : 'off'}</b>
            </p>
            <p>
              Contact emails: {company.contact_email_count} (addresses are only shown to the admin)
            </p>
            <Button variant="outline" size="sm" onClick={openLogin}>
              Admin login to change settings
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function CompetitorsCard({ company }: { company: CompanyDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Competitors</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Aliases</TableHead>
              <TableHead>Domains</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {company.competitors.map((c) => (
              <TableRow key={c.id} className={c.active ? '' : 'opacity-50'}>
                <TableCell className="font-medium">
                  {c.name}
                  {!c.active && <span className="ml-2 text-xs">(inactive)</span>}
                </TableCell>
                <TableCell className="whitespace-normal">
                  <List items={c.aliases} />
                </TableCell>
                <TableCell className="whitespace-normal">
                  <List items={c.domains} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function QuestionsCard({ company }: { company: CompanyDetail }) {
  const fact = company.questions.filter((q) => q.kind === 'fact')
  const generic = company.questions.filter((q) => q.kind === 'generic')
  return (
    <Card>
      <CardHeader>
        <CardTitle>Questions (fixed after the profile is created)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div>
          <h3 className="mb-2 text-sm font-medium">Fact questions ({fact.length})</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Question</TableHead>
                <TableHead>Expected answer</TableHead>
                <TableHead>Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {fact.map((q) => (
                <TableRow key={q.id}>
                  <TableCell className="font-medium">{q.code}</TableCell>
                  <TableCell className="whitespace-normal">{q.text}</TableCell>
                  <TableCell className="whitespace-normal">
                    {q.expected_answer}
                    {q.expected_value !== null && (
                      <div className="text-xs text-muted-foreground">
                        number {q.expected_value}
                        {q.unit ? ` ${q.unit}` : ''}
                        {q.tolerance !== null ? `, tolerance ${q.tolerance}` : ''}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    {q.expected_source_url ? <Link href={q.expected_source_url} /> : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-medium">Generic questions ({generic.length})</h3>
          <ul className="space-y-1 text-sm">
            {generic.map((q) => (
              <li key={q.id}>
                <span className="font-medium">{q.code}</span> {q.text}
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}

function SourcesCard({ company }: { company: CompanyDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Knowledge sources</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>URL</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last built</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {company.knowledge_sources.map((s) => (
              <TableRow key={s.url} className={s.active ? '' : 'opacity-50'}>
                <TableCell className="whitespace-normal">
                  <Link href={s.url} />
                </TableCell>
                <TableCell>
                  <Badge variant={s.status === 'ok' ? 'secondary' : 'outline'}>
                    {s.status}
                  </Badge>
                </TableCell>
                <TableCell>{s.last_built_at ? dateTime(s.last_built_at) : 'never'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function RunsCard({ companyId }: { companyId: string }) {
  const runs = useRuns(companyId, 10)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent runs</CardTitle>
      </CardHeader>
      <CardContent>
        {runs.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : runs.data?.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Trigger</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.data?.map((run) => (
                <TableRow key={run.id}>
                  <TableCell>{dateTime(run.started_at)}</TableCell>
                  <TableCell>{run.kind}</TableCell>
                  <TableCell>
                    <Badge variant={run.status === 'completed' ? 'secondary' : 'outline'}>{run.status}</Badge>
                  </TableCell>
                  <TableCell>{run.trigger}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

const KIND_LABEL: Record<string, string> = {
  daily_report: 'Daily report',
  alert: 'Alert',
  test: 'Test',
}

function TestEmailButton({ companyId }: { companyId: string }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => api.sendTestEmail(companyId),
    onSuccess: (result) => {
      if (result.status === 'sent') toast.success('Test email sent. Check the inbox.')
      else if (result.status === 'skipped') toast.error(`Not sent: ${result.detail}.`)
      else toast.error(`Sending failed: ${result.detail}`)
      void queryClient.invalidateQueries({ queryKey: ['emails', companyId] })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not send the test email.'),
  })
  return (
    <Button variant="outline" size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
      {mutation.isPending ? 'Sending...' : 'Send test email'}
    </Button>
  )
}

function EmailsCard({ companyId }: { companyId: string }) {
  const { isAdmin } = useAdmin()
  const emails = useEmails(companyId)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Emails</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {isAdmin && (
          <div className="space-y-1">
            <TestEmailButton companyId={companyId} />
            <p className="text-xs text-muted-foreground">Sends to the contact emails, even if emails are switched off.</p>
          </div>
        )}
        {emails.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : emails.data?.length === 0 ? (
          <p className="text-muted-foreground">No emails yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>To</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {emails.data?.map((mail) => (
                <TableRow key={mail.id}>
                  <TableCell>{dateTime(mail.sent_at ?? mail.created_at)}</TableCell>
                  <TableCell>{KIND_LABEL[mail.kind] ?? mail.kind}</TableCell>
                  <TableCell>
                    <Badge variant={mail.status === 'sent' ? 'secondary' : 'outline'}>{mail.status}</Badge>
                    {mail.error && <div className="mt-1 break-words text-xs text-muted-foreground">{mail.error}</div>}
                  </TableCell>
                  <TableCell className="break-words">
                    {mail.recipients ? mail.recipients.join(', ') : `${mail.recipient_count} address(es)`}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

export default function Settings() {
  const { companyId, isLoading } = useSelectedCompany()
  const company = useCompany(companyId)

  if (isLoading || (companyId && company.isPending)) return <Skeleton className="h-72 w-full" />
  if (!companyId) return <p className="text-muted-foreground">No company profile yet.</p>
  if (company.isError || !company.data) return <p className="text-destructive">Could not load the profile.</p>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{company.data.name}: settings</h1>
      <div className="grid gap-4 lg:grid-cols-2">
        <ProfileCard company={company.data} />
        <SwitchesCard company={company.data} />
      </div>
      <CompetitorsCard company={company.data} />
      <QuestionsCard company={company.data} />
      <SourcesCard company={company.data} />
      <div className="grid gap-4 lg:grid-cols-2">
        <RunsCard companyId={companyId} />
        <EmailsCard companyId={companyId} />
      </div>
    </div>
  )
}
