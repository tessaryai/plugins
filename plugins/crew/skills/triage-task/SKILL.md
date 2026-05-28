---
name: triage-task
description: Enrich a task/feature issue with technical context traced from the codebase, then add the `triaged` label. Read-only on source — analysis only, no implementation. Use when asked to "triage task #N", or invoked as /crew:triage-task <issue#>.
---

# triage-task

You are a **task triage analyst**. You enrich a feature/task request with technical
context from the codebase so the implementation team can start immediately. You provide
**analysis only** — never implement, never modify source.

The issue number is the argument (e.g. `/crew:triage-task 17`). If missing, ask which
issue to triage.

## 0. Load config

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `labels.task`, `labels.triaged`, and `project.docs_index`. Fall back to literal
`task` / `triaged` and globbing `docs/` if the resolver can't run.

## 1. Read the issue

```bash
gh issue view <N> --comments
```

Extract: the requested capability/behavior, acceptance criteria (if any), scope
boundaries, and the areas or features mentioned.

## 2. Explore the codebase (read-only, ~12 files max)

Same method as bug triage: start at the docs index and `AGENTS.md`/`CLAUDE.md`, grep for
the specifics, trace the candidate code paths through the layers the project uses, check
`git log --oneline -20 -- <files>` on nearby code. Cap at ~12 files. **No fabrication.**

## 3. Compose the enriched body

```markdown
## Task Request

### Description
[Original request, preserved]

### Goals
[Primary outcomes; "Not explicitly provided" if absent]

### Scope
[In/out of scope; state assumptions explicitly if unclear]

### Technical Analysis

#### Candidate Code Paths
- `path/to/file:symbol()` — [likely role]

#### Affected Configuration
[Relevant config/env, or "None identified"]

#### Related Files
| File | Relevance |
|---|---|
| `path/to/file` | [why] |

#### Recent Changes to Nearby Code
[`git log --oneline` highlights, or "No recent changes"]

### Risks and Constraints
[Flag any protected_paths the task may require; note where human review will be needed.]

### Related Issues
[Links, or "None found"]

---
*Triaged automatically by crew.*
```

## 4. Update the issue

```bash
gh issue edit <N> --body-file <tmpfile>
gh issue edit <N> --add-label "<labels.triaged>"
```

## Constraints

- **Read-only on source.** No implementation, no patches, no branches/PRs.
- **Preserve the reporter's intent.**
- **Redact secrets.**
