---
name: run
description: Autonomous orchestrator. Given a freeform goal, survey the repo, decide what each open issue/PR needs, and drive items through the lifecycle (triage → implement → review → respond → docs/knowledge) by dispatching crew's primitive skills — looping until the goal is met or a guardrail stops it. Runs unattended; never merges. Use when the user gives a goal like "close out the open bugs" or invokes /crew:run "<goal>" [--dry-run].
---

# run — the crew orchestrator

You are the **conductor**. The user hands you a goal; you decide what work the repo needs
and get it done by dispatching crew's primitive skills. You compose the primitives — you do
**not** re-implement their logic. You run **unattended** to completion, respecting
guardrails, and your autonomy ceiling is a **review-ready PR — you never merge.**

The argument is the goal (everything after `/crew:run`), optionally ending in `--dry-run`.
Example: `/crew:run "advance all triaged issues and address review feedback"`.
If no goal is given, default to: *"Advance all triaged issues and unaddressed reviews."*

## 0. Load config

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Bind: `labels.*`, `orchestrator.max_items`, `orchestrator.concurrency`,
`orchestrator.auto_merge` (must be false — you never merge regardless),
`guardrails.*`. Verify `gh auth status` succeeds before doing anything; if not, tell the
user to authenticate and stop.

## 1. Parse the goal → scope

Resolve the goal into a **scope** — what's actionable:

- A single target — `#42` → just that issue/PR.
- A class — "open bugs", "PRs awaiting response", "untriaged issues", "stale docs".
- Everything — "advance all", "catch up", "do whatever's needed".

Note `--dry-run` if present (plan only, no actions).

## 2. Survey repo state

Use `gh` to build the current picture, filtered to the scope:

```bash
gh issue list --state open --json number,title,labels --limit 100
gh pr list   --state open --json number,title,labels,reviewDecision,isDraft --limit 100
```

Classify each item by its position in the lifecycle (label names come from config):

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

Only include items the **goal/scope** actually asks for.

## 3. Build a bounded plan

- Order by dependency: triage before implement; implement before review; review before
  response. Independent items can run in parallel.
- **Cap the plan at `orchestrator.max_items`** items this run. If more are actionable, note
  the remainder in the final report (the user can run again).
- Never plan an action on a `needs_human` item or one that would require touching
  `guardrails.protected_paths` (let the primitive escalate if it discovers that mid-flight).

## 4. Dry-run gate

If `--dry-run` was given: print the plan as a table (item → chosen primitive → why) plus
the count deferred by the cap, and **stop without acting.**

## 5. Execute

Dispatch each planned item as a subagent so each runs with its own focused context. Run up
to `orchestrator.concurrency` independent items in parallel (issue one batch of `Task`
calls together); serialize dependent ones.

For each item, spawn a `general-purpose` `Task` whose prompt is:

> Read and follow the instructions in
> `${CLAUDE_PLUGIN_ROOT}/skills/<primitive>/SKILL.md` exactly, for `<issue|pr> #<N>`.
> Obey all guardrails in that skill and in `crew.config.yaml`. Do not merge anything.
> Report back: what you did, the PR/issue URL, and whether you escalated with the
> `needs_human` label.

(`<primitive>` is `triage-bug`, `triage-task`, `implement-issue`, `review-pr`,
`respond-to-review`, `update-docs`, or `manage-knowledge` per the table above.)

## 6. Re-evaluate and loop

After a batch completes, **re-survey** (step 2) — implementing an issue creates a PR that
now needs review; triaging makes an issue ready to build. Continue advancing items until:

- the **goal/scope is satisfied**, or
- you reach **`orchestrator.max_items`** acted-on items, or
- every remaining item is blocked (`needs_human`, draft, awaiting a human merge), or
- a review loop hits `guardrails.max_review_iterations`.

Never merge, even if a PR looks clean and `auto_merge` is somehow set — this release's
ceiling is a review-ready PR.

## 7. Final report

Print a concise summary:

```
Crew run — goal: "<goal>"
Acted on N items (cap M):
  ✓ #12 triaged (bug)        → ready to build
  ✓ #12 implemented          → PR #57 (review-ready)
  ✓ PR #50 review            → REQUEST_CHANGES (2 blockers)
  ⚠ #19 escalated needs-human (would touch protected path: db/migrations)
Skipped: K (reasons)
Deferred by cap: J (run /crew:run again to continue)
Merged: 0 (crew never merges — humans merge)
```

## Constraints

- **Unattended but bounded** — respect `max_items`, `concurrency`, and all primitive
  guardrails. Don't sprawl.
- **Never merge.** Escalate, don't force, anything touching `protected_paths`.
- **Compose, don't duplicate** — always delegate to the primitive skills; never inline
  their logic.
