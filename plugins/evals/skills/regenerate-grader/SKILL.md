---
name: regenerate-grader
description: Re-author one or more existing graders in place from the current call-site/failure-mode shards — a lean, non-interactive subset of synthesize-graders for when a code change made specific graders stale. Use when you already know which grader ids (or call-site ids) to refresh and want only those rewritten, e.g. "regenerate grader X", "refresh the graders for call site Y", or when an automated drift-remediation step (the evals-platform observer) targets specific graders. NOT for bootstrapping a suite — use /evals:synthesize-graders for that.
---

# regenerate-grader — re-author specific graders in place

You re-author a **named set** of already-existing graders against the **current** `.tessary/` shards, and nothing else. This is the targeted-regeneration path (`synthesize-graders --only`) lifted into its own skill so a caller — human or an unattended drift-remediation agent — can refresh a few stale graders without loading the full phased synthesis orchestration, and without any approval gates.

**What this skill is NOT:** it does not run discovery, triage, dedup, taxonomy, chain detection, or the per-site approval loop. It never hypothesizes new failure modes or call sites, never edits a shard under `pipeline/`, and never touches a grader you did not name. If `.tessary/` does not already exist (no prior `synthesize-graders` run), stop and tell the user to run `/evals:synthesize-graders` first — there is nothing to regenerate.

**Fully non-interactive.** There are no mandatory stops. This skill is safe to call from a headless/SDK session (it is the entrypoint the evals-platform observer uses to remediate drift). Do exactly the targeted work and finish.

## Inputs

`ARGUMENTS` is a whitespace-separated list of targets. Each is one of:

- a **grader id** — `<call_site_id>::<name>::grader` — re-author exactly that grader.
- a **call-site id** — `<call_site_id>` — re-author every **non-deferred** grader bound to that call site (its `severity: high` failure-mode graders plus all its quality-dimension score graders), exactly as `synthesize-graders --only <call_site_id>` would. Do not flip any `grader_deferred` flags (that is `--complete`, which this skill does not do).
- a **chain id** — `chain::<label>` — re-author that chain's non-deferred graders.

Resolve each call-site / chain id to its concrete grader ids by reading the relevant `failure_modes/<id>.yaml` (+ `quality_dimensions/<id>.yaml`) and selecting entries whose `grader_deferred` is falsy. De-duplicate the final grader-id set.

## Plugin path resolution

Resolve the plugin path **once** and reuse it (identical to `synthesize-graders`):

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*synthesize-graders*' 2>/dev/null | head -1 | xargs -I{} dirname {} | xargs dirname | xargs dirname)}"
echo "$PLUGIN"
```

The bundled Python helpers (`validate.py`, `pipeline_io.py`, `finalize.py`, `viewer.py`) require **PyYAML**. If `python3 -c "import yaml"` fails, do **not** hand-edit grader YAML or hand-compute provenance digests — stop and report that the environment is missing the plugin's Python deps (`pip install pyyaml`). A hand-faked grader/lock is worse than a skipped one.

## Procedure

1. **Preconditions.** Confirm `.tessary/graders/` exists. Resolve `$PLUGIN`. Confirm PyYAML imports.

2. **Resolve the target grader-id set** from `ARGUMENTS` (see Inputs). On the current on-disk layout (schema ≥ `0.14.0`) grader ids map to **nested** paths — `::` becomes a `/` folder separator and the redundant trailing `::grader` is dropped: `epistemic_gate_analytics::reasoning_validity::grader` → `.tessary/graders/epistemic_gate_analytics/reasoning_validity.yaml`. The same `::` → `/` nesting applies to the `pipeline/failure_modes/`, `pipeline/quality_dimensions/`, and `pipeline/call_sites/` shards. Glob recursively (`rglob`) and read the canonical `id:` from each file body rather than parsing it out of the filename.

3. **Per-grader safety triage.** For each target grader file:
   - If the file is missing, record it as unresolved and skip (do not create a new grader from scratch — that is synthesis, not regeneration).
   - Read `_meta`. If `_meta.human_edited: true`, **skip it untouched** and note it (a human owns that body now). Carry `_meta.locked_fields` forward verbatim into the author call as `existing_grader.locked_fields`.
   - For a `kind=llm_judge`/`score` grader whose `_body_source` is `platform-materialized` or `human`, the inline body is **frozen** (see the contract's body-lifecycle): do not re-author the body. Re-author only the author-owned *definition* fields (`applies_when`, `confidence`, `rationale`, and for score the `rubric_levels`/`score_scale`) if they are not locked; leave the frozen body and its `body_digest` intact.

4. **Re-author each remaining target.** Fan out one subagent per grader (in a single message) so they run in parallel; for a single target just do it inline. Each subagent follows the **Grader subagent template** in `synthesize-graders/SKILL.md` § "Grader subagent template" — same author discovery (`evals-prompt` skill if present, else `$PLUGIN/authors/default/AUTHOR.md`), same per-`kind` body rules, same `$PLUGIN/contract/AUTHORING_CONTRACT.md`. The only differences here:
   - the failure-mode / quality-dimension block is read from the **existing** shards (the call site and its `failure_modes/`/`quality_dimensions/` entry), not freshly hypothesized;
   - splice the orchestrator-owned routing fields and `_meta` from the **existing** grader file unchanged except `_meta.synthesized_at` (refresh to now) — do not invent new ids, scope, taxonomy_node_id, or operational fields;
   - validate each file with `python3 "$PLUGIN/validate.py" .tessary/graders/<file>.yaml --pipeline .tessary/` and retry the author up to 3× on failure; after 3 failures write `_validation_error` and move on.

5. **Refresh lock + viewer** (deterministic; always run, even for one grader):

   ```bash
   python3 "$PLUGIN/finalize.py" .tessary/ --partial   # rewrites .synth-lock.yaml provenance, runs validate --bundle
   python3 "$PLUGIN/viewer.py"   .tessary
   ```

   `finalize.py` is what re-computes and records each rewritten grader's hash in `.synth-lock.yaml` — do not hand-edit the lock. `--partial` keeps any pre-existing deferred failure modes from tripping the FM↔grader bijection check.

6. **Report** one line: `regenerated <N> grader(s): [<ids>]; skipped <human_edited/missing> [<ids>]`. Do not re-print grader bodies. If invoked from an unattended session, that line is the result.

## Constraints

- **Only the named graders change.** Re-running on the same inputs is diffable/stable.
- **No new sources.** Every regenerated grader stays bound to its existing call site / failure mode; this skill never adds coverage (use `synthesize-graders --complete <id>` for deferred failures, or a full `synthesize-graders` run for new sites).
- **Respect locks and frozen bodies** (`_meta.locked_fields`, `_meta.human_edited`, materialized/human `_body_source`).
- **Never forge `_meta.grounding`.** Carry the existing value forward verbatim. This skill re-authors from the shards already on disk; it does not fetch traces, so it has no standing to promote a grader to `observed`, and downgrading a grounded grader to `none` would erase a true fact about how it was written. Omitting `--grounding` on `stamp-meta` does exactly the right thing.
- **Deterministic helpers only** for validation and locking — never hand-author the lock or a provenance digest.
