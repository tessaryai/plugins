---
name: update-docs
description: Update project documentation — either for a `docs`-labeled issue request, or to reflect a merged PR's code changes — verifying claims against the actual code and opening a docs PR. Use when asked to "update docs for #N", or invoked as /crew:update-docs <issue#|pr#>.
---

# update-docs

You are the **docs maintainer**. You keep documentation accurate and consistent with the
code. You operate in one of two modes, inferred from the argument:

- **Issue mode** — a `docs`-labeled issue requests doc changes.
- **Post-merge mode** — a PR was merged; check whether docs need to follow.

The number is the argument (e.g. `/crew:update-docs 88`). If ambiguous, check whether it's
an open issue or a merged PR with `gh`.

## 0. Load config

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `project.docs_index`, `labels.docs`, `labels.agent_pr`. Read the docs index and
`AGENTS.md`/`CLAUDE.md` to learn how this project organizes and formats docs (frontmatter,
sizing, where each topic lives). **Follow the project's existing doc conventions** — match
neighbouring files.

## 1. Gather the change

- **Issue mode:** `gh issue view <N> --comments` — understand exactly what doc updates are
  requested. Address *all* requested items.
- **Post-merge mode:** `gh pr view <N>` and `gh pr diff <N>` — understand what code
  changed and what user-facing or developer-facing behavior shifted.

## 2. Identify affected docs

Map the change to the docs that cover it, using the project's docs index / structure. Read
each candidate doc **and the relevant source code** — verify every claim you write against
the actual code. Don't document intended behavior; document real behavior.

## 3. Decide and act

- **If updates are needed:**
  1. Branch: `docs/update-from-<issue|pr>-<N>`.
  2. Make the edits, preserving the project's frontmatter/format conventions; refresh any
     `last_verified`-style dates the project uses.
  3. Open a PR titled `docs: update for <issue|pr> #<N>`, labeled `labels.agent_pr`. In
     issue mode include `Closes #<N>` so it auto-closes on merge.
- **If no updates are needed:** post a brief comment on the issue/PR explaining why, and
  stop. Don't open an empty PR.

## Constraints

- **Docs only** — modify documentation files, not source code.
- **Verify against code** — never invent behavior; if the code contradicts an existing
  doc, fix the doc to match the code.
- **Never merge.**
