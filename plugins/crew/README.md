# crew

A multi-agent development harness for Claude Code. Hand it a goal and an
**orchestrator** decides what needs doing and does it — triaging issues,
implementing fixes and features through a deliberative team, reviewing PRs,
responding to review feedback, and keeping docs and knowledge current — running
unattended **up to a review-ready PR** (it never merges; you do).

**Just describe the development work you want — you don't have to say "crew" or
type a command.** crew is the team's single entry point and activates on ordinary
dev requests ("add a `--json` flag", "fix the failing test", "review PR 42",
"make this production-ready", "clean up dead code"), or run `/crew:run` with no
goal to polish the current branch. It assesses the request and runs the whole
workflow, scaling its rigor to the task. The individual capabilities below
(triage, implement, review, …) are **internal primitives the orchestrator
dispatches** — you don't pick them yourself, because a single primitive only does
its one step (a triage on its own won't go on to fix the bug; the orchestrator is
what carries it through). You can still type `/crew:run "<goal>"` explicitly when
you want to be precise.

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

# No goal: review and polish the changes on your current branch
/crew:run

# or preview the plan without acting
/crew:run "fix the open bugs" --dry-run
```

## What's in the box

### The orchestrator

| Skill | What it does |
|---|---|
| `/crew:run "<goal>" [--dry-run]` | Resolves the mode, surveys the work (GitHub issues/PRs, or the freeform task + local ledger), **assesses what the request needs and composes the right workflow**, then dispatches the primitives below along it — looping until the goal is met or a guardrail stops it. Never merges. |

#### How it decides

There's no fixed menu of workflows. The orchestrator reasons about each request
the way a tech lead would — what outcome you want, the current state of the repo,
and what "done well" actually requires — then composes a sequence of primitives to
get there. It works backwards from one mission: **best-in-class implementation,
coding standards, and project health.**

It also **right-sizes the effort**: a typo gets implemented and quickly reviewed;
a real feature gets the full advisory team, thorough review, a review→fix loop,
and doc/knowledge updates. Independent work can fork to run in parallel; review
loops are bounded by `max_review_iterations`. The reasoning framework,
effort-scaling guidance, and illustrative patterns live in `reference/workflow.md`.

#### When the job is too big — scale-out

Some requests are bigger than the serial loop should handle — a module-by-module
rewrite, a repo-wide cleanup spanning dozens of files. When triage or analysis
reveals that, the primitive reports a **decomposition plan** (independent units of
work). If it has more units than the `orchestrator.scale_out` floor (default 8),
crew proposes the split, **asks you to confirm** — showing an estimated agent count
and rough cost — and only then fans the work out across a single Claude
**Workflow**: one implement→review pipeline per unit, each in its own isolated
worktree, **one branch/PR per unit**. crew never spawns a Workflow without your OK,
and still never merges. Set `orchestrator.scale_out: 0` to turn it off. Details in
`reference/scale-out.md`.

### The primitives (internal — dispatched by the orchestrator)

You don't invoke these directly; `/crew:run` selects and sequences them. They're
listed here so you know what the orchestrator has at its disposal.

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
| `/crew:init-config` | Writes a `crew.config.yaml` tuned to your repo (this one *is* meant to be run directly, as one-time setup) |

The orchestrator dispatches each primitive with a GitHub issue/PR **number** in
GitHub mode, or a **freeform description / ledger slug** in local mode.

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
orchestrator: { max_items: 5, concurrency: 2, auto_merge: false, scale_out: 8 }
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
you review the branch and merge yourself. Add `.crew/` (the ledger, which also
holds local worktrees) and `.kosho/` to `.gitignore` (`/crew:init-config` offers
to do this).

## Safety model

- **Never merges.** The autonomy ceiling is a review-ready PR (or, locally, a
  review-ready branch); a human merges.
- **Protected paths.** crew refuses to modify `guardrails.protected_paths`
  (migrations, infra, secrets, CI, …) and escalates (github: `needs-human` label;
  local: an `ESCALATION.md` in the ledger).
- **Bounded.** The orchestrator acts on at most `orchestrator.max_items` per run,
  and review loops stop after `max_review_iterations`.
- **Scale-out always asks first.** crew never spawns a Claude Workflow for
  huge-scope work without an explicit confirmation (shown with an agent-count/cost
  estimate); below `orchestrator.scale_out` units it stays on the serial loop.
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
