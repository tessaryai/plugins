---
name: reconcile-sop
description: Re-verify a repo's v3 SOP files against the current instruction surface after code changes — propose edits, retirements, and additions with evidence, then re-lint. The per-commit maintenance flow for what /evals:derive-sop authored. Use when the user says "reconcile the SOP", "is the SOP still true", "update the SOP for this change", "check SOP drift", or invokes /evals:reconcile-sop.
---

# reconcile-sop — keep the SOP true as the code changes

A v3 SOP (`.tessary/sops/<call_site_id>.yaml`, authored by `/evals:derive-sop`) states what a call
site's standing procedure **means**. Commits change prompts, tool descriptions, and routing — and a
conformance file that has drifted from its own instruction surface measures the wrong thing while
looking authoritative. This skill is the maintenance half of the contract: re-read, re-verify every
sentence, propose changes, re-lint.

**There are no stored anchors, by design.** The SOP deliberately carries no file paths, line
numbers, or quoted prompt text to check against — pointers rot the moment a prompt file is
refactored, and instructions live duplicated and disjoint across real repos (this platform's own
git-observer learned the same lesson and moved from static anchors to re-analysis). So
reconciliation is never "check the anchors": it is **re-derive the rule↔code correspondence by
reading the whole instruction surface, every time**. Evidence lives transiently in your change
proposal, never in the file.

## Resolve the plugin path once

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*/evals/skills/reconcile-sop/*' 2>/dev/null \
  | xargs -I{} dirname {} | xargs -I{} dirname {} | xargs -I{} dirname {} \
  | sort -V | tail -1)}"
echo "PLUGIN=$PLUGIN"
```

## Flow

### 1 — Locate the SOPs in scope

List `.tessary/sops/**/*.yaml`. If the user named a call site or a commit range, scope to the SOPs
plausibly touched; with no hint, reconcile all of them. No SOPs → route to `/evals:derive-sop`.
A recent diff (`git log`/`git diff` over prompt and tool files) tells you **where to look first —
never what to skip**: an instruction can change meaning through an edit far from where it was
first stated.

### 2 — Re-read the whole instruction surface

Exactly as `/evals:derive-sop` step 2: system prompts and their composed fragments, tool
definitions and descriptions, routing rules, few-shot examples, guardrail config, checked-in
policy documents — all copies, however duplicated or disjoint. This is a full re-read, not a
delta-read; the absence of anchors is what makes that mandatory, and it is what makes the result
trustworthy.

### 3 — Verify every sentence is still true

Walk the SOP line by line against what you just read:

- **each intent** — does the demand still exist? does `means:` still describe it?
- **each observation** — is the sentence still something the instructions call for or forbid?
  do its `counts:`/`counts_not:` exemplars still reflect the conventions the asides state — and,
  where the instruction surface supports them, do they still cover all three frame dimensions
  (what opens the obligation, that it persists, the carve-outs), not just the trigger?
- **each rule** — is the instruction it enforces still present, with the same scope, trigger,
  and exception? has an `unless:` appeared or disappeared?
- **each `# deferred:` comment** — is the instruction still there, and still inexpressible?
- **the residue** — instructions in the surface that map to *no* rule and *no* deferred comment.
  New instructions are the commonest drift.

### 4 — Propose changes, with evidence in the proposal only

Assemble one proposal for the user before touching the file. Per finding: the SOP line as it
stands, what the instruction surface now says (**quote it here, in the proposal — this is the one
place verbatim evidence belongs; it never enters the file**), and the proposed edit:

- **edit** — meaning shifted: reword the sentence / adjust rule scope, trigger, exceptions.
  Keep the id when the refined sentence still names the same act; the platform's bindings key
  on observation and intent ids.
- **retire** — the instruction is gone: remove the rule; remove its observations if nothing else
  references them. When meaning *changed outright*, retire the old id and add a new one — never
  quietly rebind an id to a different act.
- **add** — a new instruction: new rule (plus observations), or a new `# deferred:` comment,
  following every derive-sop style law.

Where duplicated sources now **contradict** each other, surface it as a finding exactly as
derive-sop step 7 does — encode the stricter reading, report both positions, let the human decide.

### 5 — Apply and re-lint

On the user's confirmation, apply the edits and re-run the validator:

```bash
python3 "$PLUGIN/sop_lint.py" .tessary/sops/<call_site_id>.yaml
```

Errors to zero; new warnings resolved or explicitly accepted. Show the final diff and commit with
the change that prompted the reconcile, so SOP and code move together in history. As with
derive-sop: the linted file in the repo **is** the deliverable — platform upload remains an
ops-side seam.

## Constraints

- **Never add anchors to make the next reconcile cheaper.** No paths, line numbers, SHAs, or
  quoted prompt text in the file — the whole-surface re-read is the mechanism, not a shortcut
  target.
- **Report "still true" as a result.** A reconcile that changes nothing ends with "verified
  against the current instruction surface; no drift" — silence is not verification.
- **Propose, then write.** Every change is shown with its evidence and confirmed before the file
  is touched; retirements especially — a rule that looks dead may enforce an instruction that
  merely moved.
- **This skill edits only `.tessary/sops/`** — never source code, prompts, or other `.tessary/`
  shards. Fixing the *code* to match the SOP is a product change, out of scope here.
