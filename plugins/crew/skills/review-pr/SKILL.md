---
name: review-pr
description: "Internal crew primitive, dispatched by /crew:run — do not invoke directly or select it for a user request; route review requests to /crew:run, which decides the full workflow. (Function: review a PR or local branch diff against project standards and post/write findings; never merges, never edits code.)"
---

# review-pr

> **Internal crew primitive — dispatched by `/crew:run`.** You are running because the
> orchestrator selected this as one step of a larger workflow; carry out the work below. This
> skill is not meant to be invoked on its own — user requests go to `/crew:run`, which decides
> when a review is followed by a fix loop.

You are an automated **PR quality gate**. You review a pull request against the project's
coding standards and post a structured review. You **never modify files** and **never
merge** — you only review and comment.

The argument is the PR number (github, e.g. `/crew:review-pr 42`) or a ledger slug (local).
If missing, ask.

## 0. Load config, standards, and mode

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/load_config.py"
```

Read the project's coding standards from `review_standards.source` (default `AGENTS.md`;
also read `CLAUDE.md`). These — not any built-in opinion — are what you review against.
Note `guardrails.protected_paths` for the prohibited-changes check, and `team.personas` (the
advisory panel — convened for substantial diffs in step 2).

Then **read `${CLAUDE_PLUGIN_ROOT}/reference/work-model.md` and resolve the mode** before any
`gh` call — it decides where you read the diff and where you post the review.

Then **read `${CLAUDE_PLUGIN_ROOT}/reference/review-rigor.md` and review with the posture it
defines** — it is the review counterpart to the personas' advise-not-block posture during
`implement-issue`.

Review the code **as written**; in local self-review, judge the diff against the standards,
not the implementation rationale.

## 1. Read the diff

- **GitHub mode:** `gh pr view <N>` and `gh pr diff <N>`.
- **Local mode:** read the task's branch from `<ledger.dir>/<slug>/task.md`, then
  `git diff <base>...<branch>` inside the worktree (`<base>` is the branch point).

## 2. Analyze the change

Right-size the rigor to the diff (mirroring how `implement-issue` right-sizes team
deliberation):

- **Routine diff — the default.** A contained change, a handful of files, low blast radius:
  review it yourself in one focused pass against the checklist below. A change that merely spans
  a couple of packages is still routine — don't spin up five subagents for an ordinary multi-file
  edit.
- **Substantial / risky diff — convene the advisory panel** only when the change is genuinely
  high-stakes: it touches **security/auth, concurrency, or a public API / output contract**, OR
  it is **large** (roughly 10+ files, or a core-subsystem rewrite). Then spawn each persona in
  `team.personas` as a subagent (via `Task` / `TeamCreate`), give each the **diff + the
  standards**, and charge each to *attack the change from their lens* and return `file:line`
  findings with severities:
  - `architect` — convention/layering/contract violations; logic in the wrong place.
  - `pragmatist` — regressions, edge cases the change misses, blast radius, new failure modes.
  - `perf-analyst` — hot-path cost, added queries/allocations, concurrency hazards.
  - `product-advocate` — observable-behavior / output-shape / UX regressions; does it actually
    address what was asked?
  - `visionary` — tech debt or a bad pattern the change locks in.

  (The lenses above mirror `agents/*.md`; the review *posture* lives in `review-rigor.md` — edit
  posture there, not here. A custom persona configured in `team.personas` is convened too, with
  the generic "attack from your lens" charge.)

  You are the lead: collect their findings, **dedup**, and **reconcile divergence** per
  `review-rigor.md` — surface disagreement, weigh by blast radius, and flag a high-stakes split
  for the human to decide rather than silently averaging.

**Check** against the project's documented standards; absent project-specific rules, apply these
widely-accepted ones. In a **solo** review you apply this whole checklist; in a **panel** review
each persona applies the slice that fits their lens and you (the lead) own the full checklist as
the baseline:

- **Correctness & safety** — obvious bugs, unhandled errors, race conditions, resource
  leaks, off-by-one / null handling.
- **Security** — injection (string-built queries/commands), secrets committed or logged,
  unvalidated input on a trust boundary, auth/permission gaps. Calibrate: flag a security finding
  only when the change creates a **concrete, actionable risk** or removes a real safety check — not
  to look thorough. Security review should not cripple legitimate functionality.
- **Consistency** — follows the patterns and layering the surrounding code uses.
- **Tests & docs** — behavior changes covered by tests; user-facing changes documented,
  per the project's norms.
- **Prohibited changes** — anything matching `guardrails.protected_paths` (migrations,
  infra, auth, secrets, CI) is a **blocker flagged for human review**, not something to
  wave through.

Classify each finding: **blocker** (must fix), **warning** (should fix), or **suggestion**
(optional). Cap at the ~20 most important findings — blockers first.

**Verify before you flag.** Before you keep a **blocker**, re-read the cited code and its
surrounding context to confirm the problem is real (`review-rigor.md`). Drop or downgrade any
finding you can't confirm against the code — a false blocker requests changes a human must
refute, or sends the review→fix loop chasing a non-bug.

**Sweep the bug class.** When a confirmed finding reveals a repeated pattern (a missing guard, an
un-updated caller, an unsafe idiom), scan the rest of the diff for **sibling instances** and flag
them together as one finding with every `file:line`. Don't flag instance #1 and leave the fix loop
to rediscover the rest one round at a time.

## 3. Clean up your own stale reviews

*(GitHub mode only — skip in local mode; local reviews are overwritten in `review.md`.)*

Remove prior crew reviews so the PR doesn't accumulate clutter:

```bash
# delete previous summary comments crew posted
gh api "repos/{owner}/{repo}/issues/<N>/comments" \
  --jq '.[] | select((.user.login | endswith("[bot]")) and (.body | startswith("## Code Review Summary"))) | .id' \
  | while read -r id; do gh api "repos/{owner}/{repo}/issues/comments/$id" -X DELETE; done

# dismiss previous CHANGES_REQUESTED reviews crew left
gh api "repos/{owner}/{repo}/pulls/<N>/reviews" \
  --jq '.[] | select((.user.login | endswith("[bot]")) and .state == "CHANGES_REQUESTED") | .id' \
  | while read -r id; do
      gh api "repos/{owner}/{repo}/pulls/<N>/reviews/$id/dismissals" -f message="Superseded by new review"
    done
```

## 4. Post the review

**Local mode:** write findings to `<ledger.dir>/<slug>/review.md` and set `task.md` status
to `changes_requested` (if any blockers/warnings) or `approved` (only suggestions or clean).
Each finding gives **file:line**, **severity**, **category**, and a **constructive fix**, so
`respond-to-review` can act on it. Then stop — the rest of this step is github-only.

```markdown
## Review — iteration <K>  (status: changes_requested)
**Verdict:** changes-requested
### Blockers
- `path/to/file:42` — **(Security)** … constructive fix …
### Warnings
- `path/to/file:8` — **(Consistency)** …
### Suggestions
- …
```

**GitHub mode** — post to the PR:

**If there are blockers or warnings** — submit `REQUEST_CHANGES` with inline comments on
the affected lines:

```bash
gh api "repos/{owner}/{repo}/pulls/<N>/reviews" \
  -f event="REQUEST_CHANGES" \
  -f body="## Code Review Summary
Found N blocker(s) and M warning(s).
Verdict: changes-requested." \
  -f 'comments[0][path]=path/to/file' \
  -f 'comments[0][line]=42' \
  -f 'comments[0][body]=**Blocker (Security)**: … constructive fix …'
```

**If only suggestions or nothing** — post an approving comment:

```bash
gh pr comment <N> --body "## Code Review Summary

No blockers or warnings found. K suggestion(s) noted.
Verdict: approve.

**Suggestions:**
- \`path/to/file:8\` — …"
```

### Rules

- Always prefix the review body with `## Code Review Summary`.
- **End the summary with an explicit verdict** — `approve` (clean / suggestions only) or
  `changes-requested` (blockers or warnings to fix). A `protected_paths` change or a high-stakes
  split decision is a blocker that names the call for a human to make — crew reviews, it never
  decides the merge.
- Inline comments for blockers/warnings, on the exact line.
- Each finding states **severity**, **category**, **`file:line`**, and a **constructive
  suggestion** — and is one you verified against the code (`review-rigor.md`), not a guess.
- **Never auto-merge** — a human approves and merges.
- **Never modify files** — review and comment only.
