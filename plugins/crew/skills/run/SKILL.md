---
name: run
description: Autonomous orchestrator. Given a freeform goal, work out what's needed and drive it through a recommended workflow (playbook) by dispatching crew's primitive skills — triage, implement, review, respond, docs, knowledge. Works on GitHub issues/PRs or purely locally on any freeform task. Loops until the goal is met or a guardrail stops it. Runs unattended; never merges. Use when the user gives a goal like "close out the open bugs", "add a --json flag to the export command", or invokes /crew:run "<goal>" [--dry-run].
---

# run — the crew orchestrator

You are the **conductor**. The user hands you a goal; you decide what work is needed and get
it done by dispatching crew's primitive skills along a **recommended workflow (playbook)**.
You compose the primitives — you do **not** re-implement their logic. You run **unattended**
to completion, respecting guardrails, and your autonomy ceiling is a **review-ready PR (or,
locally, a review-ready branch) — you never merge.**

The argument is the goal (everything after `/crew:run`), optionally ending in `--dry-run`.
Examples: `/crew:run "advance all triaged issues and address review feedback"`,
`/crew:run "add a hello command to the CLI"`. If no goal is given, default to:
*"Advance all triaged issues and unaddressed reviews."*

## 0. Load config and the shared playbooks

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Then **read these two files and follow them**:

- `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` — how to resolve the mode (github vs
  local) and the I/O contract / ledger for each.
- `${CLAUDE_PLUGIN_ROOT}/reference/playbooks.md` — the named workflows and how to pick one.

Bind: `mode`, `ledger.dir`, `local.isolation`, `labels.*`, `orchestrator.max_items`,
`orchestrator.concurrency`, `orchestrator.auto_merge` (must be false — you never merge
regardless), `guardrails.*`.

**Resolve the mode now, before any `gh` call** (per work-model.md §1). Only in **github**
mode do you require `gh auth status` to pass; if it fails there, tell the user to
authenticate and stop. In **local** mode never call `gh`; confirm you're in a git repo
instead.

## 1. Parse the goal → scope

Resolve the goal into a **scope** — what's actionable:

- A single target — `#42` (github) or one freeform task (local).
- A class — "open bugs", "PRs awaiting response", "untriaged issues", "stale docs" (github).
- Everything — "advance all", "catch up", "do whatever's needed".

Note `--dry-run` if present (plan only, no actions).

## 2. Survey the work

**GitHub mode** — build the picture from `gh`, filtered to the scope:

```bash
gh issue list --state open --json number,title,labels --limit 100
gh pr list   --state open --json number,title,labels,reviewDecision,isDraft --limit 100
```

Classify each item by its lifecycle position (label names from config):

| State | Detected by | Needs |
|---|---|---|
| Untriaged bug | `bug` and not `triaged` | `triage-bug` |
| Untriaged task | `task` and not `triaged` | `triage-task` |
| Ready to build | (`bug`\|`task`) and `triaged`, no linked PR | `implement-issue` |
| Docs request | `docs` | `update-docs` |
| PR needs review | open PR, not draft, no crew review yet | `review-pr` |
| PR needs response | crew PR (`agent_pr`), `reviewDecision == CHANGES_REQUESTED` | `respond-to-review` |
| Merged recently | merged PR not yet in knowledge base | `manage-knowledge` (+ `update-docs` post-merge) |
| Escalated | carries `needs_human` | **skip** — leave for a human |

**Local mode** — the work item is the goal itself. Derive a slug and locate/create its
ledger folder (work-model.md §3). Also read existing folders under `<ledger.dir>/` and note
their `status` — an in-flight task may already be partway through a playbook (this is how
local runs resume). The status maps to the next step the same way labels do above
(`new`→triage, `triaged`→implement, `changes_requested`→respond, etc.).

Only include items the **goal/scope** actually asks for.

## 3. Choose a playbook and build a bounded plan

For each in-scope item, **select a playbook** from `reference/playbooks.md` by auto-inferring
from the goal text (there is no override flag). Common picks: a fresh task → `full-feature`;
a defect → `bugfix`; "advance everything" with existing items → `backlog-recovery`; "review
…" → `review-only`; "clean up …" → `cleanup`.

Then expand the chosen playbook into ordered steps:

- Honor the playbook's `→` (sequence), `[ ‖ ]` (parallel fork), and `loop(cap){…}` (bounded
  retry) structure. Skip steps already satisfied (e.g. don't re-triage a triaged item).
- **Cap the plan at `orchestrator.max_items`** acted-on items this run. Note any remainder
  in the final report (the user can run again).
- Never plan an action on a `needs_human` item or one that would require touching
  `guardrails.protected_paths` (let the primitive escalate if it discovers that mid-flight).

## 4. Dry-run gate

If `--dry-run` was given: print the plan as a table (item → chosen playbook → ordered steps
→ why) plus the count deferred by the cap, and **stop without acting.**

## 5. Execute

Dispatch each step as a subagent so each runs with its own focused context. Run independent
steps — including a playbook's parallel forks and independent subtasks — up to
`orchestrator.concurrency` in parallel (issue one batch of `Task` calls together); serialize
dependent ones.

For each step, spawn a `general-purpose` `Task` whose prompt is:

> Read and follow the instructions in
> `${CLAUDE_PLUGIN_ROOT}/skills/<primitive>/SKILL.md` exactly. First read
> `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` and operate in **<github|local>** mode.
> Work item: **<issue/PR #N | ledger slug `<slug>` at `<ledger.dir>/<slug>`>**.
> Obey all guardrails in that skill and in `crew.config.yaml`. Do not merge anything.
> Report back: what you did, the PR URL or branch name, and whether you escalated
> (`needs_human` label / `ESCALATION.md`).

(`<primitive>` is `triage-bug`, `triage-task`, `implement-issue`, `review-pr`,
`respond-to-review`, `update-docs`, or `manage-knowledge` per the playbook.)

For the **self-review** step in a playbook's loop, dispatch `review-pr` as a fresh subagent
given only the diff and the review standards — not the implementation rationale (see
playbooks.md, "Keeping local self-review honest").

## 6. Re-evaluate and loop

After a batch completes, **re-survey** (step 2) — implementing creates a PR/branch that now
needs review; triaging makes an item ready to build. In local mode, re-read the ledger
statuses. Advance items along their playbook until:

- the **goal/scope is satisfied**, or
- you reach **`orchestrator.max_items`** acted-on items, or
- every remaining item is blocked (`needs_human`, draft, awaiting a human merge), or
- a review loop hits **`guardrails.max_review_iterations`** (then escalate that item).

Never merge, even if a PR/branch looks clean and `auto_merge` is somehow set — the ceiling is
review-ready, in both modes.

## 7. Final report

Print a concise summary:

```
Crew run — goal: "<goal>"  (mode: <github|local>, playbook: <name>)
Acted on N items (cap M):
  ✓ #12 / "add hello cmd"  triaged        → ready to build
  ✓ #12 / "add hello cmd"  implemented    → PR #57 / branch crew/add-hello-command
  ✓ PR #50 / review        → REQUEST_CHANGES (2 blockers)
  ⚠ #19 escalated needs-human (would touch protected path: db/migrations)
Skipped: K (reasons)
Deferred by cap: J (run /crew:run again to continue)
Merged: 0 (crew never merges — humans merge)
```

In local mode, cite the **branch / worktree path** in place of the PR URL, and surface any
`ESCALATION.md` items.

## Constraints

- **Unattended but bounded** — respect `max_items`, `concurrency`, and all primitive
  guardrails. Don't sprawl.
- **Never merge.** Escalate, don't force, anything touching `protected_paths`.
- **Compose, don't duplicate** — always delegate to the primitive skills; never inline
  their logic.
- **Decide the mode before touching `gh`** — a freeform local goal must never be rejected
  for missing GitHub auth.
