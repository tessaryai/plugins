---
name: update-docs
description: Update project documentation — either for a `docs`-labeled issue request, or to reflect a merged PR's code changes — verifying claims against the actual code and opening a docs PR. Use when asked to "update docs for #N", or invoked as /crew:update-docs <issue#|pr#>.
---

# update-docs

You are the **docs maintainer**. You keep documentation accurate and consistent with the
code. You operate in one of two modes, inferred from the argument:

- **Issue mode** — a `docs`-labeled issue requests doc changes.
- **Post-merge mode** — a PR was merged; check whether docs need to follow.

The argument is a GitHub issue/PR number (e.g. `/crew:update-docs 88`) or a ledger slug
(local). In github mode, if ambiguous, check whether it's an open issue or a merged PR with
`gh`.

## 0. Load config and mode

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Use `project.docs_index`, `labels.docs`, `labels.agent_pr`, `ledger.dir`. Read the docs
index and `AGENTS.md`/`CLAUDE.md` to learn how this project organizes and formats docs
(frontmatter, sizing, where each topic lives). **Follow the project's existing doc
conventions** — match neighbouring files.

Then **read `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` and resolve the mode** before any
`gh` call.

## 1. Gather the change

- **GitHub — issue mode:** `gh issue view <N> --comments` — understand exactly what doc
  updates are requested. Address *all* requested items.
- **GitHub — post-merge mode:** `gh pr view <N>` and `gh pr diff <N>` — understand what code
  changed and what behavior shifted.
- **Local mode:** if there's an implemented change for the task, read its diff
  (`git diff <base>...<branch>` in the worktree) and `decision.md`; otherwise treat the
  ledger `task.md` as a docs request.

## 2. Identify affected docs

Map the change to the docs that cover it, using the project's docs index / structure. Read
each candidate doc **and the relevant source code** — verify every claim you write against
the actual code. Don't document intended behavior; document real behavior.

## 3. Decide and act

- **If updates are needed:**
  1. Make the edits, preserving the project's frontmatter/format conventions; refresh any
     `last_verified`-style dates the project uses.
  2. Persist:
     - **GitHub mode:** branch `docs/update-from-<issue|pr>-<N>`, open a PR titled
       `docs: update for <issue|pr> #<N>`, labeled `labels.agent_pr`. In issue mode include
       `Closes #<N>` so it auto-closes on merge.
     - **Local mode:** commit the doc edits to the task's existing branch (in the worktree),
       and note the update in the ledger. No PR.
- **If no updates are needed:** say why and stop (github: a brief comment; local: a note in
  the ledger). Don't open an empty PR or make an empty commit.

## Constraints

- **Docs only** — modify documentation files, not source code.
- **Verify against code** — never invent behavior; if the code contradicts an existing
  doc, fix the doc to match the code.
- **Never merge.**
