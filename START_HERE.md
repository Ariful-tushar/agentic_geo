# START HERE

## The files

| File | For whom | What it is |
| --- | --- | --- |
| `START_HERE.md` | You | This page: how to start and how to work every day |
| `SPEC.md` | Claude Code (and you) | What to build: agents, database, API, dashboard, deployment |
| `PLAN.md` | You and Claude Code | Day-by-day steps with checks |
| `CLAUDE.md` | Claude Code | Rules it follows in every session |
| `PROGRESS.md` | Claude Code | Checklist and log; Claude Code's memory between sessions |
| `seed/kemira.profile.yaml` | The app | Kemira's profile: 18 fact questions with correct answers, 6 generic questions, competitors, sources |
| `seed/public-questions.html` | The FAQ agent | Demo "public questions" page |

## Start (Day 0, today)

1. Do the Day 0 list in `PLAN.md` (tools, free keys, Gmail app password, repo, accounts).
2. Put all files above in the root of your empty `answerwatch` repo (keep `seed/` as a folder). Commit and push.
3. Open the folder in VS Code and start Claude Code.
4. Send:
   `Read CLAUDE.md, SPEC.md, PLAN.md and PROGRESS.md. Do step D1.1 only. Show me your plan first and wait for my OK.`

## Every step after that

1. New Claude Code session.
2. Same message with the next step ID (D1.2, D1.3, ...). PROGRESS.md tells Claude Code what is already done.
3. Read its plan, answer its questions, say OK.
4. Run the step's **Check** from PLAN.md yourself.
5. `git add -A`, `git commit -m "<ID> <name>"`, `git push`.

If something breaks: paste the full error to Claude Code and say "Fix this without changing the design in SPEC.md."

## Before you build on them

- Open 3 or 4 `expected_source_url` links in `seed/kemira.profile.yaml` and check the answers yourself.
- Check the 4 competitors against Kemira's investor material; change the list if needed.
- Put your own email in `contact_emails`.
