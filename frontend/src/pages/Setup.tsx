import { useState } from 'react'
import type { CompanyCreated } from '@/api/types'
import { ImportYaml } from '@/components/setup/ImportYaml'
import { OnboardingStatus } from '@/components/setup/OnboardingStatus'
import { ProfileForm } from '@/components/setup/ProfileForm'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAdmin } from '@/lib/admin'

export default function Setup() {
  const { isAdmin, openLogin } = useAdmin()
  const [result, setResult] = useState<CompanyCreated | null>(null)

  if (!isAdmin) {
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-semibold">Setup</h1>
        <p className="text-muted-foreground">Log in as admin to create a profile.</p>
        <Button onClick={openLogin}>Admin login</Button>
      </div>
    )
  }

  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Setup: add a company</h1>
      {result && <OnboardingStatus key={result.company_id} result={result} />}
      <Card>
        <CardHeader>
          <CardTitle>Create a profile</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="import">
            <TabsList>
              <TabsTrigger value="import">Import YAML</TabsTrigger>
              <TabsTrigger value="form">Form</TabsTrigger>
            </TabsList>
            <TabsContent value="import" className="pt-3">
              <ImportYaml onSaved={setResult} />
            </TabsContent>
            <TabsContent value="form" className="pt-3">
              <ProfileForm onSaved={setResult} />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}
