# Changelog

All notable changes to the `crew` plugin are documented here. This project
follows [semantic versioning](https://semver.org/).

## [0.3.1] — unreleased

### Changed

- Local-mode git worktrees now live under the ledger dir at
  `<ledger.dir>/worktrees/<slug>` (default `.crew/worktrees/`) instead of a
  separate `.crew-worktrees/`. One gitignore entry (`.crew/`) now covers
  everything crew writes locally.

## [0.3.0] — unreleased

### Changed

- **`/crew:run` is now the sole entry point** and **auto-activates on ordinary
  development requests** — you no longer have to say "crew" or type the command.
  The primitives (`triage-bug`, `implement-issue`, `review-pr`, …) are internal and
  only dispatched by the orchestrator, so a request like "triage this bug" flows
  through the full workflow instead of stopping after one step.
  `/crew:init-config` remains directly runnable for setup.
- **Free-flowing workflow composition.** The fixed menu of named playbooks is
  replaced by a reasoning framework (`reference/workflow.md`): the orchestrator
  assesses each request against one mission — best-in-class implementation, coding
  standards, and project health — and composes the right sequence of primitives,
  right-sizing the effort (a typo stays light; a feature gets the full team,
  review loop, and docs/knowledge). The former playbooks remain as illustrative
  patterns, not a closed list.
- **New default with no goal:** `/crew:run` (no argument) inspects the current
  branch's changes and composes a polish-the-branch workflow on them
  (review → fix loop), falling back to the GitHub backlog only when the branch is
  clean.

## [0.2.0] — unreleased

### Added

- **Local mode** — crew now serves any freeform task with no GitHub dependency.
  A new `mode` knob (`auto` | `github` | `local`, default `auto`) decides per
  invocation: a freeform goal runs locally, an issue/PR number runs against
  GitHub. Local tasks are tracked in a durable ledger (`ledger.dir`, default
  `.crew/`), and code is written in an isolated git worktree — `kosho` when
  installed, else native `git worktree` (`local.isolation`). GitHub mode is
  unchanged. The shared contract lives in `reference/work-model.md`.
- **Playbooks** — the orchestrator now sequences work along named, recommended
  workflows it auto-infers from the goal (`full-feature`, `bugfix`, `triage-only`,
  `review-only`, `docs-refresh`, `knowledge-capture`, `cleanup`,
  `backlog-recovery`) instead of an implicit hardcoded order. Supports parallel
  forks and a bounded review→fix loop. Defined in `reference/playbooks.md`.

### Changed

- `gh` is now required **only in GitHub mode**; mode is resolved before any `gh`
  call, so a local goal is never rejected for missing GitHub auth.
- All primitives accept either a GitHub issue/PR number or a local task/slug, and
  persist results to GitHub or the local ledger/branch accordingly.

## [0.1.0] — unreleased

Initial local-first release.

### Added

- **Orchestrator** (`/crew:run`) — goal-driven conductor that surveys repo state,
  plans a bounded sequence of primitives via the lifecycle state machine, dispatches
  them, and loops until the goal is met or a guardrail stops it. Runs unattended,
  supports `--dry-run`, and never merges (ceiling = review-ready PR).
- **Triage** — `/crew:triage-bug` and `/crew:triage-task` enrich issues with
  codebase context and apply the `triaged` label.
- **Implementation** — `/crew:implement-issue` convenes a deliberative team
  (architect, pragmatist, perf-analyst, visionary, product-advocate) and opens a PR.
- **Review** — `/crew:review-pr` posts a structured review; `/crew:respond-to-review`
  addresses feedback with a capped iteration loop.
- **Docs & knowledge** — `/crew:update-docs` and `/crew:manage-knowledge`.
- **Maintenance** — `/crew:process-backlog` and `/crew:spring-cleaning`.
- **Configuration** — `/crew:init-config`, layered `crew.config.yaml` →
  `AGENTS.md`/`CLAUDE.md` → built-in defaults, resolved by `lib/load_config.py`.

### Not yet included

- GitHub Actions packaging (workflow templates + `/crew:install-ci`) — planned for
  a later release. This version is local-only.
