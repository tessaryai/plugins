# crew

A multi-agent development harness for Claude Code. Hand it a goal and an
**orchestrator** decides what needs doing and does it — triaging issues,
implementing fixes and features through a deliberative team, reviewing PRs,
responding to review feedback, and keeping docs and knowledge current — running
unattended **up to a review-ready PR** (it never merges; you do).

You can drive it two ways:

- **Autonomous** — `/crew:run "close out the open bugs"` lets the orchestrator
  survey your repo and advance every actionable item.
- **Direct** — invoke any single capability yourself, e.g. `/crew:review-pr 42`.

> This release is **local-first**: every capability runs inside your own Claude
> Code session against your checked-out repo. GitHub Actions packaging is planned
> for a later version.

## Install

```
/plugin marketplace add tessaryai/plugins
/plugin install crew@tessary
```

## Quick start

```
# one-time: generate a config tuned to your repo (optional but recommended)
/crew:init-config

# let the orchestrator do whatever the goal needs
/crew:run "advance all triaged issues and address any review feedback"

# or preview the plan without acting
/crew:run "fix the open bugs" --dry-run
```

## What's in the box

### The orchestrator

| Skill | What it does |
|---|---|
| `/crew:run "<goal>" [--dry-run]` | Surveys repo state (open issues by label, PRs by review state, stuck items), builds a bounded plan from the lifecycle state machine, and dispatches the primitives below — looping until the goal is met or a guardrail stops it. Never merges. |

### The primitives (also usable on their own)

| Skill | What it does |
|---|---|
| `/crew:triage-bug <issue#>` | Enriches a `bug` issue with codebase context and adds the `triaged` label |
| `/crew:triage-task <issue#>` | Same, for `task`/feature issues |
| `/crew:implement-issue <issue#>` | Assembles a deliberative team, implements the change, opens a PR (`Fixes #N`) |
| `/crew:review-pr <pr#>` | Reviews the diff against your standards and posts a structured review |
| `/crew:respond-to-review <pr#>` | Re-assembles the team to address review feedback (max iterations capped) |
| `/crew:update-docs <issue#\|pr#>` | Updates docs for a `docs` issue or after a merged PR; opens a docs PR |
| `/crew:process-backlog` | Finds triaged issues without PRs and agent PRs with unaddressed reviews |
| `/crew:manage-knowledge [pr#]` | Captures durable decisions and gotchas into your knowledge base |
| `/crew:spring-cleaning [scope]` | Proposes bounded cleanups (dead code, unused deps, stale TODOs) |
| `/crew:init-config` | Writes a `crew.config.yaml` tuned to your repo |

### The team

`implement-issue` and `respond-to-review` convene five advisory personas —
**architect**, **pragmatist**, **perf-analyst**, **visionary**, and
**product-advocate** — who analyze the change from their angle. Only the lead
writes code; the personas never do. Their deliberation is summarized in the PR.

## Configuration

crew adapts to your repo through a layered lookup (no config required to start):

1. **`crew.config.yaml`** at your repo root (run `/crew:init-config` to create one)
2. **Your `AGENTS.md` / `CLAUDE.md`** — crew reads these for your conventions and
   coding standards
3. **Built-in generic defaults** otherwise

Key knobs (`crew.config.yaml`):

```yaml
labels: { bug: bug, task: task, triaged: triaged, docs: docs,
          agent_pr: agent-generated, needs_human: needs-human }
guardrails:
  protected_paths: ["**/migrations/**", "**/*.tf", "Dockerfile*", ".env*", ".github/**"]
  max_files_per_pr: 5
  max_review_iterations: 3
commands: { install: "npm ci", lint: "npm run lint", test: "npm test" }
review_standards: { source: "AGENTS.md" }
orchestrator: { max_items: 5, concurrency: 2, auto_merge: false }
knowledge: { dir: "docs/knowledge" }
```

See `templates/crew.config.example.yaml` for the fully annotated version.

## Safety model

- **Never merges.** The autonomy ceiling is a review-ready PR; a human merges.
- **Protected paths.** crew refuses to modify `guardrails.protected_paths`
  (migrations, infra, secrets, CI, …) and escalates with the `needs-human` label.
- **Bounded.** The orchestrator acts on at most `orchestrator.max_items` per run,
  and review loops stop after `max_review_iterations`.
- **Requires `gh`.** crew uses the GitHub CLI; make sure `gh auth status` is green.

## Requirements

- Claude Code with this plugin installed
- `gh` (GitHub CLI), authenticated
- `git`
- Your project's own lint/test tooling (auto-detected, or set in `crew.config.yaml`)

## License

MIT — see [LICENSE](./LICENSE).
