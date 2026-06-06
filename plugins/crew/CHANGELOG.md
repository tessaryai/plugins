# Changelog

All notable changes to the `crew` plugin are documented here. This project
follows [semantic versioning](https://semver.org/).

## [0.7.0] — 2026-06-06

### Added

- **jj (Jujutsu) is now the preferred local-mode isolation.** `local.isolation: auto`
  resolves **jj → kosho → git-worktree** (was kosho → git-worktree). jj gives crew
  first-class **stacked changes** so it can carry a large task across many changes over a long
  run. A new explicit `local.isolation: jj` is also accepted. (work-model.md §4 / §4.1.)
- **jj workspaces + stacking (work-model.md §4.1).** In a jj workspace crew always starts as a
  **stack** and adds **one bookmark per logical feature set**, stacked on the previous one —
  it still commits separately per change, but only opens a new bookmark when a new logical
  feature set begins. crew lets jj own history (no `git rebase`/`amend`) and recovers stale
  working copies with `jj workspace update-stale`. Submit the stack with a tool like `jst`.
- **Auto-colocation.** When jj is installed but the repo isn't colocated, crew runs
  `jj git init --colocate` at the repo root and adds `.jj/` to the user's **global** git
  excludes; git stays the source of truth. If colocation fails, crew falls back to kosho →
  git-worktree rather than stopping.

### Changed

- **Scale-out honors jj.** The orchestrator passes the resolved `isolation` into
  `workflows/scale-out.js`. Under jj, each unit-agent creates its own jj workspace (a harness
  `git worktree add` fails on colocated jj — detached HEAD) and runs `jj workspace
  update-stale` defensively; git-native isolation still uses the harness worktree. Units must
  stay disjoint in files so concurrent workspaces never stale each other.
- The local ledger now also holds jj workspaces under `.crew/workspaces/`; `task.md` records
  the resolved `isolation` mechanism and (for jj) the bookmark `stack`.
- **Migration-path guardrail is tool-aware.** The default `protected_paths` still ships
  `**/migrations/**`, but `/crew:init-config` now detects the repo's actual DB-migration
  mechanism and protects its real directory (Liquibase `changelog/`, Flyway `db/migration/`,
  etc.) — without over-matching a docs `CHANGELOG.md`. Config comments call out the variance.

## [0.6.1] — 2026-06-04

### Changed

- **Tighter review calibration.** `review-rigor` now tells reviewers to **reject** unrealistic
  edge cases, speculative "what if" risks with no concrete trigger, and findings whose only fix is
  a broad rewrite — these are noise, not findings. Security review is calibrated the same way: flag
  only a concrete, actionable risk or a removed safety check, never to look thorough, and never in
  a way that cripples legitimate functionality.
- **Confirm contracts before flagging.** When a finding hinges on a library or external API's
  behavior, reviewers must confirm it against that dependency's docs, types, or source rather than
  guessing at a contract they can verify.
- **Smallest fix at the right boundary.** Every finding now carries the minimal constructive fix at
  the correct ownership boundary — no refactor unless it clearly eliminates the bug class — so the
  review→fix loop isn't handed a worse change to make.
- **Sweep the bug class.** When a confirmed finding reveals a repeated pattern, `review-pr` scans
  the rest of the diff for sibling instances and flags them together as one finding with every
  `file:line`, instead of leaving the fix loop to rediscover them one round at a time.

## [0.6.0] — 2026-06-03

### Added

- **Adversarial multi-lens review.** For a substantial or risky diff, `review-pr` now convenes
  the advisory panel (architect, pragmatist, perf-analyst, product-advocate, visionary) to each
  **attack the finished change from their lens** — instead of a single standards pass. The lead
  dedups, reconciles divergence, and verifies before posting. Routine diffs still get a fast
  single-pass review, so the rigor is right-sized the way `implement-issue` already right-sizes
  team deliberation.
- **Verify-before-flag.** crew now re-reads the cited code to confirm a **blocker** is real
  before posting it, and the orchestrator treats an unverified concern as a question rather than
  burning review→fix iterations on it — so a false positive doesn't request changes on a human's
  PR or send the fix loop chasing a non-bug. `respond-to-review` likewise sanity-checks a finding
  against the code before changing anything, and may answer a false positive with a refutation.
- **`reference/review-rigor.md`** — a shared review posture read by `review-pr`:
  adversarial-but-grounded, evidence-cited (`file:line` + quote, no speculation), tough-grader
  severities, an explicit overall **verdict** (`approve` / `changes-requested`), and how to
  reconcile a divided panel. It's the *review* counterpart to the personas' advise-not-block
  posture during `implement-issue`, which is unchanged.

## [0.5.0] — 2026-05-29

### Removed

- **The `max_files_per_pr` cap is gone.** crew no longer bounds a change by file
  count or escalates large diffs on that basis. `implement-issue` drops its
  size-based "request human review" brake, and `spring-cleaning` is now bounded by
  evidence, scope, and the test suite rather than a hard file count. The
  `protected_paths` guardrail and the never-merge ceiling are unchanged. The
  `guardrails.max_files_per_pr` config knob is removed (any leftover value in your
  `crew.config.yaml` is simply ignored).

## [0.4.0] — 2026-05-29

### Added

- **Scale-out.** When triage or analysis reveals a task is too big for the serial
  loop — a module-by-module rewrite, a repo-wide cleanup spanning dozens of files —
  a primitive now reports a **decomposition plan** flagged `scale-out-recommended`.
  Above the `orchestrator.scale_out` floor (default 8 units), `/crew:run` proposes
  the split, **asks you to confirm** (with an agent-count/cost estimate), and only
  then fans the work out across a single Claude **Workflow** — a shipped,
  parameterized script (`workflows/scale-out.js`) that runs one implement→review
  pipeline per unit in an isolated worktree. One branch/PR per unit; crew still
  never merges, and never spawns a Workflow without your OK. New config knob
  `orchestrator.scale_out` (set `0` to disable). See `reference/scale-out.md`.

## [0.3.1] — 2026-05-29

### Changed

- Local-mode git worktrees now live under the ledger dir at
  `<ledger.dir>/worktrees/<slug>` (default `.crew/worktrees/`) instead of a
  separate `.crew-worktrees/`. One gitignore entry (`.crew/`) now covers
  everything crew writes locally.

## [0.3.0] — 2026-05-29

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

## [0.2.0] — 2026-05-28

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

## [0.1.0] — 2026-05-28

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
