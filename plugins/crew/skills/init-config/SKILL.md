---
name: init-config
description: Create a crew.config.yaml at the repo root, pre-filled from the example template and tuned to the detected stack (test/lint commands, docs index). Use when asked to "set up crew" / "configure crew" / "create crew config", or invoked as /crew:init-config.
---

# init-config

You write a `crew.config.yaml` at the repo root so crew is tuned to this project. Config is
optional — crew works without it — but a config makes label names, guardrails, and
commands explicit.

## 1. Don't clobber

If `crew.config.yaml` already exists at the repo root, **do not overwrite it.** Show the
user the current contents and offer to adjust specific fields instead.

## 2. Detect the stack

Run the resolver to see what crew would auto-detect (commands, docs index):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Also glance at the repo: package manager / build files, where docs live, and whether the
project uses non-default GitHub label names (`gh label list`).

## 3. Write the config

Start from the annotated template and fill in what you detected:

```bash
cp "${CLAUDE_PLUGIN_ROOT}/templates/crew.config.example.yaml" crew.config.yaml
```

Then edit `crew.config.yaml` to reflect this repo:

- `project.name` and `project.docs_index` (real values, or remove `docs_index` to let crew
  auto-detect).
- `commands.{install,lint,typecheck,test}` — the project's real commands (drop keys the
  project doesn't have rather than leaving wrong values).
- `labels.*` — only if the repo uses non-default label names.
- `guardrails.protected_paths` — add this repo's sensitive areas (DB schema migrations, infra,
  secrets, generated code). The default ships `**/migrations/**`, but **DB migrations are named
  differently across tools** — detect this repo's actual mechanism and add the matching glob:
  e.g. Liquibase uses `**/changelog/**` or `**/db/changelog/**` (and `*.changelog.*` /
  `changesets`), Flyway `**/db/migration/**`, Rails/Django/Alembic `**/migrations/**`, golang-migrate
  `**/migrate/**`. Match the directory the repo actually uses; **don't** add a bare `**/changelog/**`
  that would also catch a docs `CHANGELOG.md`. If unsure, glob to the real path you find.
- `mode` — leave `auto` unless the team wants to pin `github` or `local`.
- `local.isolation` — leave `auto` (jj if installed, else kosho, else native `git worktree`);
  pin it only if the team standardizes on one. Note that `jj`/`auto` will **colocate jj at the
  repo root** (`.jj/` beside `.git/`) on first local-mode run if it isn't already.
- Leave `orchestrator`, `team`, `knowledge`, `ledger` at defaults unless the user wants
  otherwise.

Keep the explanatory comments so the file stays self-documenting.

If local mode may be used, offer to add crew's scratch dirs to `.gitignore` so they don't
pollute the repo or crew's own diffs: `.crew/` (the ledger, which also holds local git
worktrees and jj workspaces under `.crew/workspaces/`) and `.kosho/`. The colocated `.jj/`
store should go in the user's **global** excludes (`~/.config/git/ignore`), not the tracked
`.gitignore`, unless the team has adopted jj — offer to add it there.

## 4. Confirm and next steps

Show the written file. Remind the user that:

- **GitHub mode** needs the GitHub CLI authenticated (`gh auth status`), and the config's
  label names must exist in the repo (`gh label create` if not). **Local mode** needs
  neither — just a git repo.
- They can now run `/crew:run "<goal>"` (a freeform goal runs locally; an issue/PR number
  runs against GitHub) or any individual `/crew:*` skill.
