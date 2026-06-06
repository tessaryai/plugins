# crew work model — modes, I/O contract, and the local ledger

Every crew skill reads this file at step 0, right after loading config. It defines the one
thing all skills share: **how to decide whether you're working against GitHub or locally,
and how to read and persist work in each case.** Skills describe *what* they do; this file
defines *where the work comes from and goes*.

crew runs in one of two **modes**. GitHub mode is the original behavior (issues + PRs via
`gh`). Local mode lets crew serve any freeform task in a checked-out repo with **no GitHub
dependency** — no `gh`, no remote, no issue. The two are identical in their actual work
(triage analysis, deliberation, implementation, review); only the source of the work item
and the destination of the output differ.

## 1. Resolve the mode — before touching `gh`

Decide the mode **before running `gh auth status`** (this is what lets a local task in
through the door instead of being rejected for missing auth). `cfg.mode` comes from
`load_config.py`.

1. `cfg.mode == "github"` → **github**.
2. `cfg.mode == "local"` → **local**.
3. `cfg.mode == "auto"` (default):
   - The argument is an issue/PR reference — `#42` or a bare integer `42` → **github**.
     Then require `gh auth status`; if it fails, **stop** and tell the user to
     authenticate (the user clearly meant a GitHub item — do **not** silently fall to
     local).
   - The argument is freeform text (a task description) → **local**.
   - No argument, but the repo is github-y (`gh auth status` succeeds **and**
     `gh repo view` succeeds) → **github** (survey mode — the orchestrator's default).
   - Otherwise → **local**.

In **local mode, never call `gh`.** Local mode must work with no GitHub CLI and no remote.

Local mode requires a git repository (it commits to a branch in an isolated workspace). If
`git rev-parse --show-toplevel` fails, stop and tell the user to `git init` or use github
mode.

## 2. The I/O contract

Each primitive does the same analytical work in both modes; only these I/O verbs differ.

| Verb | GitHub mode | Local mode |
|---|---|---|
| Identify the work item | issue / PR number `<N>` | freeform description → **slug** → ledger folder `<ledger.dir>/<slug>/` |
| Read work context | `gh issue view <N> --comments` / `gh pr view <N> --comments` | read `<ledger.dir>/<slug>/task.md` (+ `triage.md` if present) |
| Read the code change | `gh pr diff <N>` | `git diff <base>...<branch>` inside the workspace (`<base>` = the branch point, usually the default branch or the commit the workspace was created from) |
| Persist triage | `gh issue edit <N> --body-file` + `--add-label <labels.triaged>` | write `triage.md`; set status `triaged` |
| Persist implementation | branch `crew/issue-<N>-<slug>` + `gh pr create --label <labels.agent_pr>` | commit on the workspace branch/stack (**no push, no PR**) + write `decision.md`; set status `implemented` |
| Persist review | post a GitHub review (REQUEST_CHANGES / approving comment) | write `review.md` (file:line findings + severities); set status `approved` or `changes_requested` |
| Persist a review response | push commits + summary comment | commit fixes in the workspace; append an iteration section to `review.md`; bump the iteration count |
| Persist docs / knowledge | open a docs PR | commit to the branch / `knowledge.dir`; note it in the ledger |
| Escalate (needs a human) | comment + add `<labels.needs_human>` label | write `<ledger.dir>/<slug>/ESCALATION.md`; set status `needs_human` |

The autonomy ceiling is identical in both modes: **crew never merges.** In local mode it
leaves a branch for the user to review and merge.

## 3. The local ledger

In github mode the issue body and the PR *are* the shared state between crew's steps. Local
mode has no issue, and each crew step runs as an **isolated `Task` subagent** with its own
context — so they need a durable, on-disk place to hand work off. That's the ledger.

Layout — one folder per task under `<ledger.dir>` (default `.crew/`):

```
<ledger.dir>/<slug>/
  task.md         # the request + status frontmatter (always)
  triage.md       # technical analysis (after triage)
  decision.md     # approach + team deliberation + files changed (after implement)
  review.md       # review findings, one section per iteration (after review)
  ESCALATION.md   # only when crew hands off to a human
```

`task.md` frontmatter carries the lifecycle status and the branch/worktree pointers:

```markdown
---
slug: add-hello-command
kind: task            # task | bug
status: new           # new | triaged | implemented | changes_requested | approved | needs_human | done
isolation: jj         # jj | kosho | git-worktree | none (the resolved mechanism)
branch: crew-add-hello-command            # branch (git/kosho) or top bookmark (jj)
worktree: .crew/workspaces/add-hello-command   # the workspace/worktree path, or "" for isolation: none
stack: [crew-add-hello-command]           # jj only: bookmarks bottom→top, one per feature set
iteration: 0          # review-response rounds so far
---

<the user's freeform request, verbatim>
```

**Slug:** derive a short kebab-case slug from the task description (e.g. "add a hello
command" → `add-hello-command`). The slug is the task's identity — reuse the same folder
across steps and across re-runs.

The ledger holds the *artifacts*; **git holds the diff** (the branch + commits). The ledger
only points at the branch — never paste diffs into it.

**Never `git add` the ledger, workspace, or worktree directories** (`<ledger.dir>/`, default
`.crew/`, which also holds jj workspaces under `.crew/workspaces/`; and `.kosho/`). They are
crew's scratch space, not part of the user's change. The colocated `.jj/` store is kept out of
the repo via the user's **global** git excludes, not the tracked `.gitignore` (§4.1).

## 4. Workspace isolation (local mode)

So crew never disturbs the user's working tree, local-mode code changes happen in an
isolated **workspace** (a jj workspace, or a git worktree) on the task's branch. Resolve
`local.isolation`:

- **`auto`** (default) — pick the first available mechanism in this order:
  **jj** (`command -v jj` succeeds) → **kosho** (`command -v kosho` succeeds) →
  **git-worktree** (always available). jj is preferred because it gives crew first-class
  **stacked changes** (§4.1) for long-running, multi-feature work.
- **`jj`** — use a **jj workspace** (§4.1). Requires `jj`; if missing, fall back as `auto`
  would (kosho → git-worktree).
- **`kosho`** — `kosho run crew-<slug> git rev-parse --show-toplevel` creates (on first
  use) and reports the worktree at `.kosho/crew-<slug>` on branch `crew-<slug>`. Run
  validation commands inside it via `kosho run crew-<slug> <cmd>`.
- **`git-worktree`** — `git worktree add <ledger.dir>/worktrees/<slug> -b crew/<slug>`
  (default `.crew/worktrees/<slug>`; if the branch/worktree already exists from a prior run,
  reuse it instead of erroring). Run validation by `cd`-ing into that path.
- **`none`** — no workspace; create/checkout branch `crew/<slug>` in the main working tree.
  First run `git status --porcelain`; if the tree is dirty in files crew intends to touch,
  **stop and report** rather than committing over the user's work.

Record the chosen isolation mechanism, branch/bookmark, and workspace path in `task.md` so
later steps (and re-runs) find them. **Do all edits, commits, and validation inside the
workspace path** — never the user's main checkout. Commit only crew's own files by explicit
path; never `git add -A`.

### 4.1 jj workspaces and stacking

jj (Jujutsu) is a Git-compatible VCS. In **colocated** mode (`.jj/` beside `.git/` at the
repo root) git stays the source of truth — remotes, branches, PRs, and CI keep working —
while jj adds stable change-IDs, automatic descendant rebasing, and an undoable op-log. crew
uses it to keep **logical feature sets stacked** so it can carry a large task across many
changes over a long run.

**Activate jj (once per repo):** jj only works colocated, and only at the repo **root** (it
refuses to init inside a git worktree). If `jj root` fails, crew is responsible for colocating
before isolating:

1. `jj git init --colocate` at `git rev-parse --show-toplevel`.
2. Add `.jj/` to the user's **global** git excludes (`~/.config/git/ignore`) — keep it out of
   the repo's tracked `.gitignore` unless the team has adopted jj.
3. Confirm the repo still builds (`commands.*` if configured) before proceeding.

If colocation fails for any reason, **fall back** to kosho → git-worktree rather than stopping.

**Create the workspace:** `jj workspace add <ledger.dir>/workspaces/<slug>` (default
`.crew/workspaces/<slug>`; reuse if it already exists from a prior run). Each workspace is an
isolated sibling working copy over the one shared backend. `cd` into it for all edits,
commits, and validation.

**Stacking — always start from a stack, one bookmark per logical feature set.** Within a
workspace crew maintains a **stack** of jj changes built on the base bookmark (the default
branch tip):

- On first entry, set a base: `jj new <default-branch>` and bookmark the workspace's starting
  point. The workspace **always begins as a stack**, even of length one.
- Each **logical feature set** gets its own jj change + bookmark (`crew-<slug>-<n>` or a
  feature-named bookmark), **stacked on the tip of the previous feature set**. A new logical
  feature set → `jj new` on the current tip, then `jj bookmark create` for it.
- crew still **commits separately per change** (jj records each change); a *bookmark* is added
  **only when a new logical feature set begins** — not per commit. Group commits that belong to
  the same feature set under one bookmark. If the work is a single feature set, that's one
  bookmark on top of the base (a stack of one) — don't manufacture extra layers.
- Editing a lower change auto-rebases its descendants (`Rebased N descendant commits…`) — let
  jj own history. **Never `git rebase` or `git commit --amend`** in a jj workspace; read-only
  `git` (status, diff, log) is fine.

**Stale recovery:** workspaces share one backend, so rewriting a shared ancestor can stale a
peer workspace (`Error: The working copy is stale`). If crew sees this, run
`jj workspace update-stale` and continue. (`jj util gc` if commands feel slow.)

**Pointers:** record `isolation: jj`, the workspace path, the base bookmark, and the current
stack of bookmarks in `task.md`. **Teardown is never crew's job mid-task** — crew never merges;
leave the stack for the user to submit (e.g. with `jst`) and merge. `jj workspace forget
<slug>` only during explicit cleanup.

## 5. Notes for skill authors

- Resolve the mode **once**, at step 0, and thread it (plus the issue number or ledger
  slug) into anything you dispatch. Subagents don't share your memory — pass the slug and
  tell them to read this file.
- Primitives are normally **dispatched by `/crew:run`**, which tells you the mode and the
  work item — they aren't meant to be invoked directly. (`/crew:run` is the user-facing
  entry point; `/crew:init-config` is the one other directly-run skill, for setup.)
- Everything in a skill's "Constraints" section (read-only-on-source, never-merge,
  protected-paths, redact-secrets) applies in **both** modes unchanged.
