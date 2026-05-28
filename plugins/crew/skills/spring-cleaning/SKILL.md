---
name: spring-cleaning
description: Propose bounded codebase cleanups — dead code, unused dependencies/exports, stale TODOs, orphaned files — each backed by evidence and validated against the test suite, in one PR per category. Never touches protected paths, never merges. Use when asked to "clean up the repo" / "find dead code", or invoked as /crew:spring-cleaning [scope].
---

# spring-cleaning

You perform **bounded, evidence-backed cleanup**. You never make sweeping rewrites — each
cleanup is small, justified, and validated. Your ceiling is a review-ready PR — **never
merge.**

Optional argument is the scope: `dead-code`, `unused-deps`, `stale-todos`, `orphaned`, or
`all` (default: ask the user, or `dead-code` if unattended).

## 0. Load config

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Obey `guardrails.protected_paths` (never touch these), `guardrails.max_files_per_pr` (cap
per cleanup PR), `commands.*` (to validate), and `labels.{agent_pr,cleanup}`.

Then **read `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` and resolve the mode** before any
`gh` call. Detection and validation are identical in both modes; only the output differs
(step 4).

## 1. Detect (read-only first)

Pick detectors by language — use what the repo already has before installing anything:

- **dead code / unused exports:** `knip` or `ts-prune` (JS/TS), `ruff check --select F401`
  + `vulture` (Python), `go vet` / `deadcode` (Go), `cargo +nightly udeps` (Rust).
- **unused dependencies:** `depcheck` (JS/TS), comparing manifest vs imports otherwise.
- **stale TODOs:** `grep -rn "TODO\|FIXME\|XXX"` and cross-reference with `git blame` age.
- **orphaned files:** files with no inbound references / not in any build graph.

Gather **evidence** for each candidate (e.g. "no inbound references", "import removed in
PR #X"). Do not act on anything you can't justify.

## 2. Propose a bounded set

For the chosen scope, select at most `guardrails.max_files_per_pr` changes. Exclude
anything matching `protected_paths`. Prefer high-confidence removals; when unsure, leave it
and note it in the PR description as a candidate for human judgment.

## 3. Validate

Apply the removals on a branch, then run `commands.install` and `commands.test` (and
`lint`/`typecheck` if present). If anything breaks, revert that item — a cleanup that
breaks the build is not a cleanup.

## 4. One change set per category

Work on branch `crew/cleanup-<scope>` (local mode: in an isolated worktree per
`local.isolation`, work-model.md §4). List each removal with its evidence and the test
result.

- **GitHub mode:** open a PR labeled `labels.agent_pr` + `labels.cleanup`, titled
  `chore(cleanup): <scope>`, with that list in the body.
- **Local mode:** commit to the branch (no push, no PR); record the removal list + evidence
  in `<ledger.dir>/cleanup-<scope>/decision.md`.

**Never merge.**

## Constraints

- **Never touch `protected_paths`.**
- **Evidence required** for every change; **bounded** by `max_files_per_pr`.
- **Validated** — tests must pass.
- **Never merge.**
