import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const AGENTS = [
  ['Ax', 'Every morning asks the AI engines the company\'s fixed questions, scores each answer against the correct answers, finds why wrong answers are wrong, and saves daily accuracy.'],
  ['Competitor agent', 'When a competitor is named before the company, or the company is not named at all, finds out why from the sources the AI cited and writes a 2 to 3 line report.'],
  ['FAQ agent', 'Collects new public questions about the company\'s niche and writes draft FAQ answers using only the company\'s own information.'],
  ['Support agent', 'For one page URL, checks how many of the company\'s questions an AI could answer from that page, and gives 3 concrete suggestions.'],
]

const LIMITS = [
  'The tested engines are free engines. Real ChatGPT, Perplexity or Gemini with search need paid keys and can be added as engines later.',
  'Only engines with web search give sources. For memory-only engines the "why" can only say "model memory".',
  'API answers can differ from what people see in the consumer apps.',
  'The judge is an AI. Its reason and quote are shown so a person can check it.',
  'Root causes are likely causes, not proof.',
  'Facts come from the company\'s public publications and were not reviewed by the company.',
  'Days marked "simulated" are seeded demo history that only fills the charts. No answers are stored for them, and they are never used for alerts or emails. Real monitoring starts with the first real run.',
]

export default function About() {
  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-xl font-semibold">About AnswerWatch</h1>
      <p className="text-muted-foreground">
        AnswerWatch monitors what AI assistants say about a company, every day, automatically.
        Nothing is published to the company's website: drafts and suggestions are shown here and a
        human decides what to use.
      </p>

      <Card>
        <CardHeader>
          <CardTitle>How it works: four agents</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="space-y-3 text-sm">
            {AGENTS.map(([name, text]) => (
              <div key={name}>
                <dt className="font-medium">{name}</dt>
                <dd className="text-muted-foreground">{text}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>How accuracy is scored</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            Each engine is asked the company's fixed fact questions once per day. A judge compares
            the answer with the correct answer: correct = 1, partly correct = 0.5, wrong = 0,
            no answer = 0. Accuracy is the average score of the fact questions.
          </p>
          <p>
            Number questions are checked by code against a tolerance, not by the judge. The "RAG"
            line is our own assistant answering only from the company's public pages.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Web search or memory?</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Engines marked "with web search" look at live pages and give sources. "Memory only"
          engines answer from what the model learned in training. The engine list on the Overview
          chart uses the same names.
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Limits</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {LIMITS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <p className="text-sm font-medium">Independent demo, not affiliated with the selected company.</p>
    </div>
  )
}
