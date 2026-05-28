---
name: manage-knowledge
description: Capture durable engineering knowledge — decisions, rationale, and gotchas — from merged PRs and review discussions into an evergreen knowledge base, deduped against what's already recorded. Use when asked to "capture knowledge from PR #N" / "update the knowledge base", or invoked as /crew:manage-knowledge [pr#].
---

# manage-knowledge

You curate an **evergreen knowledge base** of durable decisions and gotchas — the "why"
behind the code that source and user docs don't capture. This complements `update-docs`
(which keeps user/developer docs accurate); here you distill *decisions and lessons*.

Argument is optional: a PR number captures from that PR; with no argument, do a sweep over
recent merged PRs that aren't yet represented.

## 0. Load config

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `knowledge.dir` (default `docs/knowledge`) and `labels.agent_pr`.

## 1. Gather source material

- **PR mode:** `gh pr view <N> --comments` + `gh pr diff <N>` — read the description, the
  review thread, and the change itself.
- **Sweep mode:** `gh pr list --state merged --limit 20 --json number,title,mergedAt` and
  pick recent ones not yet referenced in `knowledge.dir`.

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
**Source:** #<PR>
```

3. Keep the index in `knowledge.dir/README.md` current.

## 4. Open a PR

Branch `docs/knowledge-update-<N|date>`, commit, and open a PR labeled `labels.agent_pr`
titled `docs(knowledge): capture decisions from #<N>`. **Never merge.**

## Constraints

- **Knowledge base only** — write under `knowledge.dir`; don't touch source.
- **Durable only** — quality over volume; an empty update is fine.
- **Dedupe aggressively.**
