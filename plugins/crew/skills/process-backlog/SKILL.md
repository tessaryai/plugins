---
name: process-backlog
description: Sweep the repo for work that fell through the cracks — triaged issues with no PR, and crew PRs with unaddressed review feedback — and advance a bounded number of them. Never merges. Use when asked to "process the backlog" / "catch up on stuck issues", or invoked as /crew:process-backlog.
---

# process-backlog

You recover work that stalled (rate limits, timeouts, missed events). You find stuck items
and advance a **bounded** number of them, then stop. Your ceiling is a review-ready PR —
**never merge.**

## 0. Load config

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `labels.{bug,task,triaged,agent_pr}` and `orchestrator.max_items` (the per-run cap;
default 5 if unset). Split the budget across the two backlogs below.

## 1. Find triaged issues with no PR

```bash
gh issue list --state open --label "<labels.triaged>" --json number,title,labels
```

Keep those that also carry `labels.bug` or `labels.task`. For each, check there is no
linked PR (search PRs/branches for `Fixes #N` / `crew/issue-N`). These need implementation.

## 2. Find crew PRs with unaddressed reviews

```bash
gh pr list --state open --label "<labels.agent_pr>" --json number,reviewDecision,title
```

Keep those whose latest review state is `CHANGES_REQUESTED` (or that have unresolved review
comments). These need a review response.

## 3. Advance, up to the cap

Process at most `orchestrator.max_items` items total, one at a time:

- triaged-issue-without-PR → run the `implement-issue` flow for it.
- PR-with-unaddressed-review → run the `respond-to-review` flow for it.

(If invoked from the orchestrator, dispatch each via `Task`; standalone, you may follow the
respective skill directly.)

## 4. Report

Summarize what you processed, what you skipped (and why), and anything you escalated with
`labels.needs_human`. Stop once the cap is hit even if items remain — say how many remain.

## Constraints

- **Bounded** — never exceed `orchestrator.max_items` per run.
- **Never merge.** Respect all `implement-issue` / `respond-to-review` guardrails.
