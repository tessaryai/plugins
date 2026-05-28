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

And it works in two **modes**, chosen automatically:

- **GitHub mode** — pass an issue/PR number (or run with no task in an authed
  repo) and crew works through GitHub issues and PRs, as before.
- **Local mode** — hand it a freeform task (`/crew:run "add a --json flag to
  export"`) and crew works entirely on your checkout — no `gh`, no remote, no
  issue required. It tracks the task in a local ledger and writes code in an
  isolated git worktree, leaving a review-ready branch.

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

# GitHub: let the orchestrator do whatever the goal needs
/crew:run "advance all triaged issues and address any review feedback"

# Local: hand it a freeform task — no GitHub needed
/crew:run "add a hello command to the CLI"

# or preview the plan without acting
/crew:run "fix the open bugs" --dry-run
```

## What's in the box

### The orchestrator

| Skill | What it does |
|---|---|
| `/crew:run "<goal>" [--dry-run]` | Resolves the mode, surveys the work (GitHub issues/PRs, or the freeform task + local ledger), picks a recommended **playbook**, and dispatches the primitives below along it — looping until the goal is met or a guardrail stops it. Never merges. |

#### Playbooks

The orchestrator sequences work along a named **playbook** it infers from your
goal, instead of acting ad hoc. The headline one, `full-feature`:

```
triage → implement → [ docs ‖ self-review ] → loop{ respond → re-review } → capture knowledge
```

Others: `bugfix`, `triage-only`, `review-only`, `docs-refresh`,
`knowledge-capture`, `cleanup`, and `backlog-recovery`. Independent work can fork
to run in parallel; the review→fix loop is bounded by `max_review_iterations`. See
`reference/playbooks.md`.

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

The triage/implement/review/respond skills take a GitHub issue or PR **number**
in GitHub mode, or a **freeform description** (triage/implement) or **ledger
slug** (review/respond) in local mode.

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
mode: auto                # auto | github | local
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
ledger: { dir: ".crew" }          # local mode: per-task state
local: { isolation: auto }        # auto | kosho | git-worktree | none
```

See `templates/crew.config.example.yaml` for the fully annotated version.

### Modes and local isolation

`mode: auto` (default) picks **github** when you pass an issue/PR number (or run
with no task in an authed repo) and **local** for a freeform task. In local mode
crew tracks each task under `ledger.dir` (`.crew/`) and isolates the code it
writes in a git worktree, governed by `local.isolation`:

- **`auto`** — use `kosho` worktrees if installed, else fall back to native
  `git worktree` (zero install — works for everyone).
- **`kosho`** / **`git-worktree`** — force one mechanism.
- **`none`** — commit on a `crew/<slug>` branch in your working tree (with a
  dirty-tree guard).

crew never touches your main working tree in worktree modes, and never merges —
you review the branch and merge yourself. Add `.crew/`, `.kosho/`, and
`.crew-worktrees/` to `.gitignore` (`/crew:init-config` offers to do this).

## Safety model

- **Never merges.** The autonomy ceiling is a review-ready PR (or, locally, a
  review-ready branch); a human merges.
- **Protected paths.** crew refuses to modify `guardrails.protected_paths`
  (migrations, infra, secrets, CI, …) and escalates (github: `needs-human` label;
  local: an `ESCALATION.md` in the ledger).
- **Bounded.** The orchestrator acts on at most `orchestrator.max_items` per run,
  and review loops stop after `max_review_iterations`.
- **`gh` only in GitHub mode.** GitHub mode uses the GitHub CLI (`gh auth status`
  must be green); local mode needs neither `gh` nor a remote.

## Requirements

- Claude Code with this plugin installed
- `git`
- `gh` (GitHub CLI), authenticated — **only for GitHub mode**
- `kosho` — optional; local mode uses it when present, else native `git worktree`
- Your project's own lint/test tooling (auto-detected, or set in `crew.config.yaml`)

## License

MIT — see [LICENSE](./LICENSE).
