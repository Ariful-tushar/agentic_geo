import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '@/api/client'
import type { CompanyCreated } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export function ImportYaml({ onSaved }: { onSaved: (result: CompanyCreated) => void }) {
  const [yaml, setYaml] = useState('')
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => api.importYaml(yaml),
    onSuccess: (result) => {
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
      void queryClient.invalidateQueries({ queryKey: ['company', result.company_id] })
      onSaved(result)
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not reach the API.'),
  })

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) setYaml(await file.text())
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Same format as <code>seed/kemira.profile.yaml</code>. Importing a profile that already exists
        updates it; its questions are never changed or duplicated.
      </p>
      <div className="grid gap-2">
        <Label htmlFor="yaml-file">YAML file</Label>
        <Input id="yaml-file" type="file" accept=".yaml,.yml,text/yaml" onChange={onFile} />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="yaml-text">or paste the YAML</Label>
        <Textarea
          id="yaml-text"
          rows={14}
          className="font-mono text-xs"
          value={yaml}
          onChange={(e) => setYaml(e.target.value)}
        />
      </div>
      {error && <pre className="whitespace-pre-wrap rounded-lg bg-destructive/10 p-3 text-xs text-destructive">{error}</pre>}
      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || yaml.trim() === ''}>
        {mutation.isPending ? 'Importing…' : 'Import profile'}
      </Button>
    </div>
  )
}
