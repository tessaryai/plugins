---
name: manage-knowledge
description: "Internal crew primitive, dispatched by /crew:run — do not invoke directly or select it for a user request; route knowledge-capture requests to /crew:run, which decides the full workflow. (Function: capture durable decisions, rationale, and gotchas into the knowledge base, deduped.)"
---

# manage-knowledge

> **Internal crew primitive — dispatched by `/crew:run`.** You are running because the
> orchestrator selected this as one step of a larger workflow; carry out the work below. This
> skill is not meant to be invoked on its own — user requests go to `/crew:run`.

You curate an **evergreen knowledge base** of durable decisions and gotchas — the "why"
behind the code that source and user docs don't capture. This complements `update-docs`
(which keeps user/developer docs accurate); here you distill *decisions and lessons*.

Argument is optional: a PR number captures from that PR; with no argument, do a sweep over
recent merged PRs that aren't yet represented.

## 0. Load config and mode

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `knowledge.dir` (default `docs/knowledge`), `labels.agent_pr`, and `ledger.dir`.

Then **read `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` and resolve the mode** before any
`gh` call.

## 1. Gather source material

- **GitHub — PR mode:** `gh pr view <N> --comments` + `gh pr diff <N>` — read the
  description, the review thread, and the change itself.
- **GitHub — sweep mode:** `gh pr list --state merged --limit 20 --json number,title,mergedAt`
  and pick recent ones not yet referenced in `knowledge.dir`.
- **Local mode:** read the task's `decision.md` and `review.md` from the ledger plus the
  branch's history (`git log`/`git diff <base>...<branch>` in the worktree).

## 2. Extract durable knowledge

Pull out only **durable, reusable** items — things a future engineer would want to know:

- **Decisions** — "we chose X over Y because Z" (with the trade-off and constraints).
- **Patterns / conventions** — a new approach the team adopted and why.
- **Gotchas** — non-obvious pitfalls, footguns, or constraints discovered the hard way.

Skip the ephemeral (one-off bug fixes with no lasting lesson, routine changes). If a PR
yields nothing durable, record nothing for it.

## 3. Dedupe and write

1. Read existing entries under `knowledge.dir`. If an item is already covered, **update**
   that entry rather than adding a duplicate; only add genuinely new knowledge.
2. Append/update a dated entry in `knowledge.dir/decisions.md` (create the file and a brief
   `knowledge.dir/README.md` topic index if absent), linking the source PR:

```markdown
## YYYY-MM-DD — <short title>
**Context:** …
**Decision / lesson:** …
**Why:** …
**Source:** #<PR>   (github; in local mode cite the task slug + branch)
```

3. Keep the index in `knowledge.dir/README.md` current.

## 4. Persist

- **GitHub mode:** branch `docs/knowledge-update-<N|date>`, commit, and open a PR labeled
  `labels.agent_pr` titled `docs(knowledge): capture decisions from #<N>`. **Never merge.**
- **Local mode:** commit the knowledge entry to the task's branch (in the worktree) and note
  it in the ledger. No PR.

## Constraints

- **Knowledge base only** — write under `knowledge.dir`; don't touch source.
- **Durable only** — quality over volume; an empty update is fine.
- **Dedupe aggressively.**
