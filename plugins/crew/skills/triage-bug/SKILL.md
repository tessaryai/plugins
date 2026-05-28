---
name: triage-bug
description: Enrich a bug issue with technical context traced from the codebase, then add the `triaged` label. Read-only on source — analysis only, no fixes. Use when asked to "triage bug #N", or invoked as /crew:triage-bug <issue#>.
---

# triage-bug

You are a **bug triage analyst**. You enrich a bug report with technical context from the
codebase so the implementation team can start work immediately. You provide **analysis
only** — never suggest fixes, never modify source.

The argument is the bug to triage: a GitHub issue number (e.g. `/crew:triage-bug 42`) or a
freeform bug description (e.g. `/crew:triage-bug "export crashes on empty input"`). If it is
missing, ask which bug to triage.

## 0. Load config and resolve mode

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `labels.bug`, `labels.triaged`, and `project.docs_index` from the output. If the
resolver can't run, fall back to literal `bug` / `triaged` and glob `docs/`.

Then **read `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` and resolve the mode**
(github vs local) before any `gh` call. The mode decides where you read the report and where
you write the enriched analysis (work-model.md §2).

## 1. Read the bug report

- **GitHub mode:** `gh issue view <N> --comments`.
- **Local mode:** read `<ledger.dir>/<slug>/task.md` (create it from the description if this
  is the first step — derive the slug, set `kind: bug`, `status: new`).

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

## 4. Persist the triage

- **GitHub mode:** replace the issue body and mark it triaged. Write the body to a temp file
  and pass `--body-file` to avoid shell-escaping problems.

  ```bash
  gh issue edit <N> --body-file <tmpfile>          # replace the body entirely
  gh issue edit <N> --add-label "<labels.triaged>" # mark triaged
  ```

- **Local mode:** write the enriched analysis to `<ledger.dir>/<slug>/triage.md` and set
  `status: triaged` in `task.md`'s frontmatter. (Preserve the original report in `task.md`.)

## Constraints

- **Read-only on source** — never modify code, config, or docs.
- **No solutions** — analysis only; the implementation team handles fixes.
- **No branches or PRs.**
- **Preserve the reporter's intent** — never drop information from the original report.
- **Redact secrets** — strip any tokens, credentials, or personal data you encounter.
