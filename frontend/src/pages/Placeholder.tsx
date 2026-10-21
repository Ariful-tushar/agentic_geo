// Pages that are built in later steps (see PLAN.md). They exist now so the sidebar has no dead links.
export default function Placeholder({ title, step }: { title: string; step: string }) {
  return (
    <div className="space-y-2">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="text-muted-foreground">Coming in step {step}.</p>
    </div>
  )
}
