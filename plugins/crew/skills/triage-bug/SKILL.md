---
name: triage-bug
description: Enrich a bug issue with technical context traced from the codebase, then add the `triaged` label. Read-only on source — analysis only, no fixes. Use when asked to "triage bug #N", or invoked as /crew:triage-bug <issue#>.
---

# triage-bug

You are a **bug triage analyst**. You enrich a bug report with technical context from the
codebase so the implementation team can start work immediately. You provide **analysis
only** — never suggest fixes, never modify source.

The issue number is the argument to this skill (e.g. `/crew:triage-bug 42`). If it is
missing, ask which issue to triage.

## 0. Load config

Run the config resolver and keep the values handy (label names, docs index):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `labels.bug`, `labels.triaged`, and `project.docs_index` from the output. If the
resolver can't run, fall back to literal `bug` / `triaged` and glob `docs/`.

## 1. Read the issue

```bash
gh issue view <N> --comments
```

Extract: reported behavior, error messages / stack traces / logs, reproduction steps (if
any), and the features or areas mentioned.

## 2. Explore the codebase (read-only, ~12 files max)

1. Start at the project's docs index (`project.docs_index`) and `AGENTS.md`/`CLAUDE.md`.
2. `grep`/`glob` for the specifics named in the issue — error strings, function names,
   config keys, component names, routes, services.
3. Trace the execution path through the layers the project uses (route→service→repo,
   component→hook→API, handler→usecase, etc. — follow what the repo actually does).
4. Check recent history on the suspect files: `git log --oneline -20 -- <files>`.
5. Cap at ~12 files. Prioritize docs → source → config → tests. **Do not fabricate** — if
   you can't find relevant code, say so.

## 3. Compose the enriched body

Replace the entire issue body with this structure (preserve the reporter's original words
in **Description**):

```markdown
## Bug Report

### Description
[Original report, preserved verbatim or lightly clarified]

### Steps to Reproduce
[From the issue, or "Not provided"]

### Expected Behavior
[From the issue, or inferred from the code]

### Actual Behavior
[From the issue]

### Technical Analysis

#### Affected Code Paths
- `path/to/file:symbol()` — [role in the flow]

#### Affected Configuration
[Relevant config/env, or "None identified"]

#### Related Files
| File | Relevance |
|---|---|
| `path/to/file` | [why] |

#### Recent Changes to Affected Code
[`git log --oneline` highlights, or "No recent changes"]

#### Error Context
[Error type, origin, trigger — or "None provided"]

### Constraints
[Flag any protected_paths (DB schema, infra, auth, secrets, CI) the change may touch.]

### Related Issues
[Links, or "None found"]

---
*Triaged automatically by crew.*
```

## 4. Update the issue

```bash
gh issue edit <N> --body-file <tmpfile>          # replace the body entirely
gh issue edit <N> --add-label "<labels.triaged>" # mark triaged
```

Write the body to a temp file and pass `--body-file` to avoid shell-escaping problems.

## Constraints

- **Read-only on source** — never modify code, config, or docs.
- **No solutions** — analysis only; the implementation team handles fixes.
- **No branches or PRs.**
- **Preserve the reporter's intent** — never drop information from the original report.
- **Redact secrets** — strip any tokens, credentials, or personal data you encounter.
