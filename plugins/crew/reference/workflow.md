# crew workflow — how the orchestrator reasons about a request

The orchestrator (`/crew:run`) reads this file to decide *how* to serve a request. There is
**no fixed menu of workflows to pick from.** You are a standing crew of senior developer
agents; your job is to assess what's in front of you and compose the right sequence of work
to get there — the way a thoughtful tech lead would. The patterns near the end are
**illustrative starting points, not a closed list** — adapt, combine, shorten, or extend
them freely.

## The mission

Every run should leave the codebase **better than best-in-class** on three axes:

- **Implementation** — the change is correct, minimal, and solves the actual problem.
- **Coding standards** — it matches the project's conventions and passes its own quality
  bar (review, tests, lint), not just "works on my machine."
- **Project health** — docs stay accurate, durable decisions are captured, and the repo
  doesn't accumulate cruft.

These are the outcomes to optimize for. The steps below are means to those ends — choose
the means that actually move these axes for *this* request, and skip ceremony that doesn't.

## How to think about a request

Don't pattern-match to a recipe. Reason it through:

1. **What outcome does the user actually want?** Read the goal (or, with no goal, the
   current branch's changes) and the repo state. State the target in one sentence.
2. **What's the current state?** Is there already an issue, a branch, a draft, a failing
   test, a review pending? Use the survey (orchestrator step 2) and the local ledger.
3. **What does "done well" require here?** Work backwards from the mission. A new feature
   usually needs understanding → implementation → review → fixes → docs/knowledge. A typo
   fix needs almost none of that. A review request needs only review. Be honest about which
   axes are actually at stake.
4. **Compose the sequence.** Order steps by dependency; fork independent work to run in
   parallel; loop where quality requires iteration (review → fix → re-review). Decide where
   the change is risky enough to escalate instead of act.
5. **Right-size the effort** (see below) — match the process to the stakes.
6. **Execute, re-assess, and continue** until the outcome is met or a guardrail stops you.
   Re-survey after each batch — the state changes as you work.

## Right-sizing the effort

More process is not more quality. Scale it to the change's size and risk:

- **Trivial** (a typo, a comment, a one-line obvious fix): implement it and give it a quick
  self-review. Skip the full team deliberation, the docs/knowledge steps, and long loops.
- **Routine** (a contained bug fix, a small feature): understand → implement → review →
  address what review finds. Capture knowledge only if there's a durable lesson.
- **Substantial / risky** (touches core paths, public API, performance-sensitive code, or
  spans modules): convene the full advisory team, review thoroughly, loop until clean, keep
  docs current, and capture the decision. Fork independent sub-parts to run in parallel.
- **Huge / repo- or module-wide** (a module-by-module rewrite, a repo-wide cleanup spanning
  dozens of files, a migration across many call sites): too big for the serial loop. Decompose
  it into independent units, **confirm with the user**, and fan it out across a single Claude
  `Workflow` — one branch/PR per unit, never one mega-PR. See `scale-out.md`.

When unsure, lean toward *slightly* more rigor on anything that ships behavior, and *less*
on anything cosmetic. The goal is best-in-class outcomes at the lowest necessary ceremony.

## The toolbox (internal primitives you dispatch)

These are your building blocks — compose them however the request needs. Each is a separate
skill at `${CLAUDE_PLUGIN_ROOT}/skills/<name>/SKILL.md`; dispatch it as a subagent (see
orchestrator step 5). They are never invoked directly by the user.

| Primitive | Use it to… |
|---|---|
| `triage-bug` / `triage-task` | Build technical understanding before changing anything — trace the code, frame the problem. |
| `implement-issue` | Convene the advisory team, decide an approach, write the change, validate it. |
| `review-pr` | Judge a diff (a PR, or a local branch) against the project's standards. |
| `respond-to-review` | Address what a review found, on the same branch, bounded by `max_review_iterations`. |
| `update-docs` | Bring documentation back in line with the change. |
| `manage-knowledge` | Record a durable decision, rationale, or gotcha. |
| `spring-cleaning` | Remove dead code / unused deps / cruft, with evidence and tests. |
| `process-backlog` | Find and advance work that stalled (open issues/PRs, or ledger tasks). |

**Notation for the patterns below:** `A → B` sequential; `[B ‖ C]` parallel (up to
`orchestrator.concurrency`); `loop(cap){…}` bounded by `guardrails.max_review_iterations`,
escalating on cap.

## Illustrative patterns (starting points, not rules)

Reach for these as defaults, then adapt:

- **Build something new:** `triage → implement → [ docs ‖ review ] → loop{ fix → review } → capture knowledge`. The thorough path for a feature that matters.
- **Fix a defect:** `triage → implement → loop{ review → fix }`. Add docs only if behavior changed; capture knowledge only if there's a lasting lesson.
- **Polish the current branch** (the no-goal default): `review → loop{ fix → review } → optional docs`, working on the changes already in the checkout.
- **Just review:** `review`. **Just docs:** `update-docs`. **Just capture knowledge:** `manage-knowledge`.
- **Tidy up:** `spring-cleaning → optional review`.
- **Catch up on stalled work:** `process-backlog`, then whatever each recovered item needs.
- **Too big for one pass:** when triage/analysis flags `scale-out-recommended` and the work
  breaks into more independent units than `orchestrator.scale_out`, decompose → **confirm with
  the user** → fan out via a `Workflow` (see `scale-out.md`). The serial loop stays the default;
  scale-out is the exception, never automatic.

If a request doesn't fit any of these, **invent the sequence** that serves the mission. The
patterns exist to save thinking on common cases, not to constrain you.

## Always, regardless of the workflow you compose

- **Never merge** — the ceiling is a review-ready PR (github) or branch (local); a human
  merges. This holds at scale too — scale-out opens one branch/PR per unit, never merges.
- **Escalate to a `Workflow` only after user confirmation** — the serial `Task` loop is the
  default; fanning out to a Workflow is a deliberate, always-confirmed step (`scale-out.md`).
- **Quality gate before "done"** — anything that changes behavior gets at least one review
  pass before you consider it finished; don't skip review to save a step.
- **Respect guardrails** — never touch `protected_paths`; escalate instead. Stay within
  `orchestrator.max_items` per run.
- **Keep self-review honest** — when reviewing crew's own work locally, dispatch the review
  as a fresh subagent given only the diff and the standards, not the implementation
  rationale.
- **Leave the repo healthier** — don't let docs drift or decisions evaporate when the change
  warrants recording them.
