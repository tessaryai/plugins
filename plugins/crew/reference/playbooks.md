# crew playbooks — recommended workflows for the orchestrator

The orchestrator (`/crew:run`) reads this file and uses it to sequence work deliberately
instead of ad hoc. A **playbook** is a named, ordered recipe of primitive skills with
explicit fork (parallel) and loop (bounded retry) points. The orchestrator picks a playbook
from the goal, then executes its step graph — dispatching each step via the same primitives
documented elsewhere, in whichever mode (github / local) was resolved per
`reference/work-model.md`.

Playbooks are **mode-agnostic**: each step is a primitive that resolves its own I/O. The
same `full-feature` playbook drives a triaged GitHub issue to a PR, or a freeform local task
to a review-ready branch.

## Notation

- `A → B` — run A, then B (B depends on A's output).
- `[B ‖ C]` — fork: run B and C in parallel, up to `orchestrator.concurrency`. Rejoin
  before the next step.
- `loop(cap){ … }` — repeat the body until the exit condition, bounded by
  `guardrails.max_review_iterations`. On hitting the cap without converging, **escalate**
  (needs_human label / `ESCALATION.md`) and stop the loop.

Every playbook obeys the global invariants: **never merge**, respect `protected_paths` and
`max_files_per_pr`, and stay within `orchestrator.max_items` per run.

## The playbooks

### 1. full-feature — *default for a fresh actionable task or a triaged feature*

```
triage-task → implement-issue → [ update-docs ‖ review-pr ] → loop(cap){ respond-to-review → review-pr } → manage-knowledge
```

- Triage establishes technical context; implement writes the change.
- **Fork:** docs and the first review run in parallel — both read the implemented diff and
  are independent of each other.
- **Loop (the bug-fixing loop):** while the review requests changes, respond and re-review,
  bounded by `max_review_iterations`. Exit when the review is clean; escalate on cap.
- Capture knowledge once, at convergence.

If the item is already triaged (github: has `labels.triaged`; local: ledger status is
`triaged` or later), skip the triage step.

### 2. bugfix — *lighter loop for a defect*

```
triage-bug → implement-issue → loop(cap){ review-pr → respond-to-review } → manage-knowledge
```

No docs fork (most fixes don't change documented behavior; add `update-docs` only if the
fix does). Knowledge capture is optional — skip if the fix yields nothing durable.

### 3. triage-only

```
triage-bug | triage-task
```

Pick by kind. Use when the goal is just to enrich/understand, not to build.

### 4. review-only

```
review-pr
```

github: review an existing PR. local: review the current crew branch's diff.

### 5. docs-refresh

```
update-docs
```

A docs request, or refreshing docs after a change.

### 6. knowledge-capture

```
manage-knowledge
```

Distill decisions/gotchas from recent merged PRs (github) or the crew branch + ledger
(local).

### 7. cleanup

```
spring-cleaning → (optional) review-pr
```

Bounded, evidence-backed cleanup; optionally self-review the result before handing off.

### 8. backlog-recovery — *catch up on stalled work*

```
process-backlog
```

github: triaged issues with no PR → implement; agent PRs with CHANGES_REQUESTED → respond.
local: scan the ledger for non-terminal statuses and advance them. Resumes interrupted runs.

## Selecting a playbook

The orchestrator **auto-infers** the playbook from the goal text (there is no manual
override flag):

| Goal contains… | Playbook |
|---|---|
| "fix", "bug", "broken", "regression" | bugfix |
| "add", "implement", "build", "feature", "support for" | full-feature |
| "review" | review-only |
| "docs", "document", "readme" | docs-refresh |
| "knowledge", "capture decisions" | knowledge-capture |
| "clean", "dead code", "unused", "tidy" | cleanup |
| "catch up", "process backlog", "stuck", "advance everything" | backlog-recovery |
| a bare issue/PR number (github) | infer from the item's label (bug→bugfix, task→full-feature, docs→docs-refresh, an open PR→review-only) |

**Defaults:** a fresh actionable task with no clear signal → `full-feature`. "Advance all /
do whatever's needed" with existing items → `backlog-recovery` (then the per-item playbook
each item needs).

## Forking into parallel subtasks

When a goal decomposes into **independent** parts (e.g. a feature touching two unrelated
modules), the orchestrator may fork it into child tasks:

- Create a child ledger folder per subtask (github: this stays a single issue — fork only
  applies to local tasks, or to independent issues already separate).
- Run a playbook per child, up to `orchestrator.concurrency` in parallel.
- **Rejoin onto one branch:** children commit to the *same* `crew/<slug>` branch (one commit
  per child) so the final diff is reviewable as a unit.
- Only fork genuinely independent work; anything with shared files or ordering stays
  sequential.

## Keeping local self-review honest

In local mode the same model that implemented the change also reviews it. To reduce
self-justification, the orchestrator dispatches `review-pr` as a **fresh subagent given only
the diff and `review_standards.source`** — not the implementation rationale or `decision.md`.
It should judge the code as written, not the intent behind it.
