---
name: respond-to-review
description: Address review feedback on a crew-generated PR by re-convening the relevant specialists, pushing fix commits, and summarizing what changed — capped at a configurable number of iterations before escalating to a human. Never merges. Use when asked to "address review on PR #N" / "respond to feedback", or invoked as /crew:respond-to-review <pr#>.
---

# respond-to-review

You are the **team lead** addressing review feedback on a PR you (crew) opened. You
re-convene the relevant specialists, push commits that address the feedback, and report
back. Your ceiling is still a **review-ready PR — you never merge.**

The argument is the PR number (github, e.g. `/crew:respond-to-review 42`) or a ledger slug
(local). If missing, ask.

## 0. Load config and mode

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Read `guardrails.max_review_iterations`, `guardrails.protected_paths`,
`guardrails.max_files_per_pr`, `team.personas`, `labels.needs_human`, `ledger.dir`, and the
`commands.*` for validation.

Then **read `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` and resolve the mode** before any
`gh` call — it decides where you read the feedback and apply the fixes.

## 1. Read the review

- **GitHub mode:** `gh pr view <N> --comments` and `gh pr diff <N>`.
- **Local mode:** read `<ledger.dir>/<slug>/review.md` (the latest iteration's findings) and
  the branch from `task.md`.

Collect every unresolved review comment / finding and the requested changes.

## 2. Check the iteration count

Determine how many response rounds crew has already done — github: from the PR's commit
history / prior crew summary comments; local: the `iteration` field in `task.md`. If that
count is **>= `max_review_iterations`**, **stop** and escalate:

> "This work has been through `<max_review_iterations>` review iterations. Requesting human
> review to resolve the remaining concerns."

— github: post the comment + add `labels.needs_human`; local: write `ESCALATION.md` + set
`status: needs_human`. Then end.

## 3. Route feedback to the team

Map each comment to the specialist best suited to advise, and spawn them (via `Task` /
`TeamCreate`):

- architecture/structure → `architect`
- performance → `perf-analyst`
- product/UX/behavior → `product-advocate`
- scope/complexity → `pragmatist`
- long-term/tech-debt → `visionary`

Collect their guidance. (Skip personas with no relevant comments.)

## 4. Apply the changes

1. Get onto the branch — github: `gh pr checkout <N>`; local: work in the task's existing
   worktree (from `task.md`).
2. Make the changes addressing the feedback. **Re-check guardrails** — never touch
   `protected_paths`; if feedback demands it, escalate instead (github: `labels.needs_human`;
   local: `ESCALATION.md`).
3. Validate with the configured `commands.*` (local: inside the worktree).
4. Commit your fixes (only crew's own files). **GitHub mode:** push to the PR branch.
   **Local mode:** the commit on the branch is the deliverable — do not push.

## 5. Summarize

List each piece of feedback and how it was addressed (or why not):

```markdown
## Crew — review response (iteration K)
- "<comment>" → <what changed> (`path`)
- …
```

- **GitHub mode:** post this as a PR comment.
- **Local mode:** append it as a new iteration section to `<ledger.dir>/<slug>/review.md`,
  bump the `iteration` field in `task.md`, and set `status: implemented` (ready for
  re-review).

## Constraints

- **Never merge.**
- **Never modify `protected_paths`** — escalate instead (github: `labels.needs_human`;
  local: `ESCALATION.md`).
- Stop after `max_review_iterations` and hand off to a human.
