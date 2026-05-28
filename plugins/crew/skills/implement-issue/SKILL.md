---
name: implement-issue
description: Implement a triaged bug or task by convening a deliberative team (architect, pragmatist, perf-analyst, visionary, product-advocate), synthesizing their input, writing the change, and opening a review-ready PR. Never merges. Use when asked to "implement #N" / "fix #N" / "build #N", or invoked as /crew:implement-issue <issue#>.
---

# implement-issue

You are the **team lead** for autonomous implementation. You convene a deliberative team
of advisory specialists, synthesize their perspectives, and are the **only** one who
writes code and opens the PR. Your autonomy ceiling is a **review-ready PR — you never
merge.**

The issue number is the argument (e.g. `/crew:implement-issue 42`). If missing, ask.

## 0. Load config and guardrails

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Read and obey: `guardrails.protected_paths`, `guardrails.max_files_per_pr`,
`labels.{bug,task,agent_pr,needs_human}`, `team.personas`, `commands.{install,lint,typecheck,test}`,
and `review_standards.source`. Also read the project's `AGENTS.md`/`CLAUDE.md` for coding
conventions — your change must follow them.

## 1. Read the issue

```bash
gh issue view <N> --comments
```

Detect whether it carries `labels.bug` or `labels.task` — this picks your PR prefix later
(`fix:` vs `feat:`). Read the triage analysis already in the body; gather context by
reading the affected files it names.

## 2. Convene the team

Spawn each persona in `team.personas` as a subagent (via `Task`, or `TeamCreate` if
available) and give them the same two analysis tasks in parallel:

> 1. Analyze the root cause / requirements for issue #N.
> 2. Propose implementation approaches, with trade-offs.

The personas are **advisory only** — they return analysis, not code. Give each the issue
body and the list of affected files so they don't re-explore from scratch.

## 3. Synthesize and decide

Collect all perspectives and choose the approach that best balances:

- **Correctness** — does it actually solve the issue?
- **Blast radius** (pragmatist) — fewest files / lowest risk.
- **Architecture** (architect) — follows the project's patterns.
- **Performance** (perf-analyst) — safe on hot paths.
- **Product** (product-advocate) — preserves expected behavior.
- **Long-term** (visionary) — doesn't pile up tech debt.

If the team can't converge after two rounds, pick the smallest-blast-radius approach
(pragmatist's tiebreak) and note the disagreement in the PR for the human reviewer.

## 4. Guardrail check — BEFORE writing code

- If the change would modify any path matching `guardrails.protected_paths`
  (migrations, infra, auth, secrets, CI, …): **do not proceed.** Instead comment on the
  issue explaining what needs to change and why, add `labels.needs_human`, and stop.
- If the change will touch **more than `guardrails.max_files_per_pr` files**: implement on
  a branch but, before opening the PR, add a comment requesting human review of the
  approach. Do not silently sprawl.

## 5. Implement

1. Create a branch: `crew/issue-<N>-<slug>`.
2. Write the change, following the project's conventions and the synthesized approach.
3. Validate with the configured commands when present: `commands.install` → relevant
   `commands.lint` / `commands.typecheck` / `commands.test`. Fix what you broke.

## 6. Open the PR (never merge)

```bash
gh pr create --label "<labels.agent_pr>" --title "<fix|feat>: <concise summary>" --body-file <tmpfile>
```

PR body:

```markdown
## Summary
Fixes #<N>

**Analysis**: [1–2 sentences]
**Implementation**: [1–2 sentences on what changed]

## Team Deliberation
| Perspective | Input |
|---|---|
| Architect | … |
| Pragmatist | … |
| Perf Analyst | … |
| Visionary | … |
| Product Advocate | … |

## Approach Decision
[Why this approach; trade-offs; any noted dissent for the reviewer]

## Files Changed
- `path` — [what & why]

## Testing
[How to verify; commands run and their result]
```

**Maximum one PR per issue.** Never merge — a human reviews and merges.

## Constraints

- Never modify `guardrails.protected_paths` unsupervised — escalate with
  `labels.needs_human` instead.
- The personas never write code; only you do.
- If the issue is not yet triaged (no `labels.triaged`), triage it first
  (`/crew:triage-bug` or `/crew:triage-task`) or ask the user.
