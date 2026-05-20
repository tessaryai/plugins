---
name: synthesize-graders
description: Generate a calibrated eval suite for an LLM product. Point it at the user's repo (with optional production traces) and it produces graders, datasets, and a visual report under `tessary-evals/`. Use when the user says "synthesize evals", "generate evals", "bootstrap evals for this repo", "create graders", or invokes /evals:synthesize-graders.
---

# synthesize-graders — synthesize an eval pipeline from a real codebase

You are running a phased synthesis pipeline against a target repo. The point of phasing is **time to first artifact**: a working `tessary-evals/index.html` appears after the first call site is graded, not after every call site is processed. The orchestrator processes one call site at a time, only synthesizes graders for `severity: high` failures in the first sweep, and defers everything else to an on-demand `--complete` flow. Medium- and low-severity failures still get hypothesized and written to disk — they just don't get graders until the user asks.

The orchestrator's job is to plan small fan-outs, run deterministic Python helpers, and read tiny return manifests — it never holds call-site bodies, failure-mode descriptions, taxonomy details, or grader bodies in context.

> **Mandatory stops — read before you start.** This skill MUST hand control back to the user after the first call site and again after the second. "Hand control back" means **end your turn**: print the status line and the gate prompt, then emit no more tool calls and no more output until the user replies. Do not process the whole `priorities.yaml` in one unattended turn — doing so silently consumes the entire session, which is the exact failure this skill is built to avoid. These two stops hold even if the user previously said "go fast" or "don't stop to ask"; an early human preview is the whole point. See Phase C.7 for the full gate. The only zero-gate path is `--complete all` on a run that has already been previewed.

Output goes to a directory in the **target repo's** working directory:

```
tessary-evals/
  pipeline/
    meta.yaml                         # version, product_hint, runtime, progress
    packs.yaml                        # engaged packs + interview answers
    priorities.yaml                   # ordered list of call_site_ids
    product_profile.yaml              # phase A
    invariants.yaml                   # implicit_invariants + invariant_coverage
    call_sites/<id>.yaml              # one per call site
    chains.yaml                       # all detected chains
    failure_modes/<call_site_id>.yaml # single_call failures per site
    failure_modes/_chains.yaml        # chain failures
    taxonomy.yaml                     # taxonomy tree (populated at end of phase C)
  graders/<grader_id_safe>.yaml       # one file per emitted (non-deferred) grader
  datasets/<call_site_id>.jsonl       # captured inputs (Path A only)
  report.md                           # human-readable walkthrough
  index.html                          # self-contained visual viewer
  .synth-lock.yaml                    # SHA-256 of every shard + grader
```

One grader per file is deliberate: emission failures are isolated (re-run one grader, not the whole batch), diffs are scoped to the grader that changed, and validation happens per file so a single malformed grader doesn't poison the pipeline. The same logic applies to the pipeline itself — sharded across per-artifact files so no single Write call carries the whole synthesis.

## Deferred failure modes

Every failure-mode entry carries a `grader_deferred: <bool>` field. The orchestrator sets it during phase C:

- `severity: high` → `grader_deferred: false` and a grader is synthesized this sweep.
- `severity: medium | low` → `grader_deferred: true` and `grader_id: null`; the failure is recorded but no grader is emitted yet.

The user can flesh out the deferred ones later with `/evals:synthesize-graders --complete <call_site_id>` (or `--complete all`). The viewer renders deferred failures with a distinct "deferred" badge and the same hint string.

## Plugin path resolution

All bundled scripts (`validate.py`, `viewer.py`, `dedup.py`, `audit.py`,
`finalize.py`, `pipeline_io.py`) and the OSS fallback author live in this
plugin directory. **Resolve the plugin path once, at the start of the run,
and reuse it.** At the start of Phase A, do this via Bash:

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*synthesize-graders*' 2>/dev/null | head -1 | xargs -I{} dirname {} | xargs dirname | xargs dirname)}"
echo "$PLUGIN"
```

Cache the result as `$PLUGIN`. **Never hardcode `.claude/skills/synthesize-graders/`** — that path is not stable across Claude Code plugin layouts.

## Two grader scopes

The pipeline produces graders in two distinct scopes that must remain cleanly separated:

- **`scope: single_call`** — grades one LLM call's output. Layer A (mechanical) and Layer B (judgmental) failures live here.
- **`scope: chain`** — grades a relationship across N call-site outputs in the same logical session. Produced by Phase D; requires a runner that can fetch multiple outputs from one trace.

## Inputs

- **Repo path** (required) — local directory to analyze. If they don't give one, assume CWD and confirm.
- **Traces file** (optional) — JSONL of OpenTelemetry GenAI spans.
- **Product hint** (optional) — 1-2 sentences describing what the product does.
- **Pack selection** (optional) — `--pack <id>` / `--no-pack <id>`. Without flags, the triage phase auto-discovers from `applies_when` signals. `quality` is always-on.
- **Deep-grade** (optional) — `--complete <call_site_id>` flips that site's deferred medium/low failures to non-deferred and synthesizes their graders. `--complete all` does the same for every site in priority order, reusing the same adaptive approval gate.
- **Pause cadence** (optional) — `--pause-every N` overrides the adaptive gate; the orchestrator pauses after every N sites instead of using the measured per-site budget.

## Re-run safety

If `tessary-evals/` already exists in the target repo, load `tessary-evals/.synth-lock.yaml`
(if present) before doing anything else. The lock now records hashes for
*every shard* under `pipeline/` *and* every grader. Triage:

1. **Load locks.** For each grader file, verify its current SHA against the
   lock. Read `_meta.locked_fields` and `_meta.human_edited` per file.
2. **Decide the safe path.** Shards under `pipeline/` are orchestrator-owned;
   re-runs overwrite them. Grader files are the human-curatable surface:
   - No grader is `human_edited` and no grader diverges from the lock →
     proceed; carry `_meta.locked_fields` forward.
   - Any grader `human_edited: true` OR diverges without `locked_fields` →
     ask the user:
     1. **Respect locks (default)** — re-synthesize, preserve listed fields,
        skip `human_edited: true` files entirely.
     2. **Diff** — write to `tessary-evals.new/` instead. Treat that as the output
        directory throughout the run.
     3. **Force overwrite** — `--force`. Destructive; warn explicitly.
     4. **Cancel**.

### Resume from a prior run

When `tessary-evals/` is present from a previous (possibly interrupted) run, pick up where it left off rather than redoing finished work. The lock file at `tessary-evals/.synth-lock.yaml` records, per labeled unit of work, the files that unit produced and the SHA-256 of each file's content. A unit is considered complete only when its lock entry exists **and every recorded file is still present with a matching hash** — file existence alone is never enough.

Two helpers drive this; both are CLI shims around `pipeline_io.py`:

```bash
# Exit 0 if <label>'s outputs are recorded and every file's content still matches.
python3 "$PLUGIN/pipeline_io.py" check-step <label> --evals-dir tessary-evals

# Record the listed paths as outputs of <label>, capturing their current SHA-256.
python3 "$PLUGIN/pipeline_io.py" lock <label> <path>... --evals-dir tessary-evals

# Per-file check (used inside grader fan-outs for per-grader resume).
python3 "$PLUGIN/pipeline_io.py" check-file <path> --evals-dir tessary-evals
```

Wrap each unit like this:

```bash
if python3 "$PLUGIN/pipeline_io.py" check-step <label> --evals-dir tessary-evals; then
  echo "<label>: resumed from prior run; skipping."
else
  # ... run the unit ...
  python3 "$PLUGIN/pipeline_io.py" lock <label> <produced paths> --evals-dir tessary-evals
fi
```

Lock labels used by the phased flow:

| Label | Paths to record on completion |
| --- | --- |
| `A` — Phase A (discovery) | `pipeline/product_profile.yaml`, `pipeline/invariants.yaml`, every `pipeline/call_sites/<id>.yaml` |
| `B` — Phase B (triage) | `pipeline/packs.yaml`, `pipeline/priorities.yaml` |
| `C-fm-<id>` — Phase C.1 per-site failure modes | `pipeline/failure_modes/<id>.yaml` plus the patched `pipeline/call_sites/<id>.yaml` |
| `D` — Phase D (chains + taxonomy) | `pipeline/chains.yaml`, `pipeline/failure_modes/_chains.yaml`, `pipeline/taxonomy.yaml` |

Grader files are not locked under a step label — they're locked individually as they're emitted, and `check-file` is the per-grader resume check. Partial grader batches resume cleanly from the first missing grader.

`dedup.py`, `audit.py`, `finalize.py`, and `viewer.py` always run — they're deterministic Python, cheap, and `finalize.py` / `viewer.py` must refresh the lock and viewer regardless. `dedup.py` and audit-driven targeted fix subagents rewrite failure-modes shards; re-lock the affected `C-fm-<id>` entries after each rewrite.

`--force` skips every resume check and re-runs every unit from scratch (use after intentional shard deletion, or when a prior run finished but the user wants a clean re-synthesis).

### Targeted regeneration (`--only`)

`--only <grader_id|call_site_id|chain_id>`:

- **`<grader_id>`** — re-synthesize that grader only. Read its call-site shard + the relevant `failure_modes/<call_site>.yaml`. Do not re-run Phases A–B or other sites; do not re-emit any other file. Update the lock entry for that one file.
- **`<call_site_id>`** — re-synthesize every non-deferred grader for that site. Reads the one call-site shard + failure-modes shard. Use `--complete <call_site_id>` instead if you also want the site's medium/low deferred failures fleshed out.
- **`<chain_id>`** — re-synthesize that chain's graders (non-deferred only; `--complete` to include deferred).

`--only` always respects `_meta.locked_fields`. Combine with `--force` to
override locks (rare).

## Pipeline

Five phases. A and B run once. C is the per-site loop with the user-approval gate. D wraps up chains + taxonomy at the end. E is the on-demand deep-grade flow triggered by `--complete`.

```
┌─ Phase A — Discovery (parallel) ────────────────────────────────┐
│  Product profile subagent  ‖  Call-site discovery subagent      │
└──────────────────────────────────┬──────────────────────────────┘
                                   ▼
┌─ Phase B — Triage (main agent, serial) ─────────────────────────┐
│  Pack discovery + interview  →  Rank call sites  →  Confirm     │
└──────────────────────────────────┬──────────────────────────────┘
                                   ▼
┌─ Phase C — Per-site loop ───────────────────────────────────────┐
│   For each call_site_id in priorities.yaml:                     │
│     Per-site subagent (steps 2+3+4)                             │
│     dedup.py (before deferral — settles severity)               │
│     Mark grader_deferred per severity                           │
│     Grader fan-out for non-deferred FMs only                    │
│     audit.py --partial + finalize.py --partial + viewer.py      │
│     Adaptive gate (strict for sites 1–2, then batch budget)     │
└──────────────────────────────────┬──────────────────────────────┘
                                   ▼
┌─ Phase D — Chains + taxonomy (once at end of C) ────────────────┐
│   Chain detection subagent → taxonomy subagent → final pass     │
│   of dedup / audit / finalize / viewer                          │
└─────────────────────────────────────────────────────────────────┘

Phase E (on demand): /evals:synthesize-graders --complete <id>
```

### Phase A — Discovery

Send **one message with two Agent tool calls** so they run in parallel.

1. **Product profile subagent** (`subagent_type: Explore`) — pass `$PLUGIN/prompts/analyze_product.md`, the target repo path, and the absolute `tessary-evals/` path. Writes `tessary-evals/pipeline/product_profile.yaml` and `tessary-evals/pipeline/invariants.yaml`. Returns a manifest with domain, regulatory regimes, data sensitivity kinds, invariant counts, and `coverage_deferred: true` (because call-site discovery may still be running).

2. **Call-site discovery subagent** — choose:
   - **Path A — traces provided**: `subagent_type: general-purpose`. Parse the JSONL (OTLP/JSON or flat Python SDK exporter shape), normalize spans, group by normalized system-prompt hash, write one `tessary-evals/pipeline/call_sites/<id>.yaml` per group and `tessary-evals/datasets/<id>.jsonl` per group. Span taxonomy and observability stats (`observed.*` p50/p95/error_rate/refusal_rate/cost) are required. Stratified sampling at up to 10 representative spans per site.
   - **Path B — static repo**: `subagent_type: Explore`. Grep for LLM-call patterns; write one shard per discovered call site. **Split on runtime dispatch — a single physical call location is not always a single call site.** A call site is one *(intent, system prompt, output schema)* combination, not one line of code. When a call location selects its prompt or schema from a registry / map / enum / `match` keyed on a parameter, follow the dispatch and emit **one call site per branch** — each branch has its own failure surface and deserves its own graders. Signals that a call location fans out and must be split:
     - the system prompt is loaded by a variable key (`load_prompt(gate.system_prompt_path)`, `PROMPTS[kind]`, `f"{name}.txt"`) rather than a fixed literal;
     - the response schema is chosen per branch (`schema = gate.response_schema`, `SCHEMAS[kind]`);
     - a registry / dispatch table is indexed by the parameter (`REGISTRY.get(name)`, `HANDLERS[kind]`, `match kind:`);
     - the trace label / `use_case` is parameterized (`use_case = f"epistemic-gate:{gate_name}"`) — this is the developer telling you these are distinct operations, so honor it: one call site per concrete label, named after it (`epistemic_gate_memory`, `epistemic_gate_concepts`, …).

     Enumerate the branch keys from the registry definition, the enum, or the call sites that pass the parameter. If a branch set is unbounded or you cannot enumerate it, emit one call site and note the limitation in `use_case`. Conversely, do **not** over-split: parameters that only vary content (the user's text, a temperature, a retry count) are the *same* call site — split only when the prompt or schema or declared trace identity changes per branch.

   Returns a manifest: a list of `{id, use_case, provider, sample_count, has_system_prompt, redaction_state, file_hint?}` and the overall `runtime.redaction_state` (worst case across sites).

   **`use_case` is the call site's display name — write it factually.** It names *what the call produces*, in a short noun phrase (≈3–6 words). State the operation and its object; nothing else.
   - **Drop transport/implementation descriptors** — how the call is delivered or stored is not what it does: no `stream`/`streaming`, `async`, `batched`, `cached`, `via cron`, `background worker`, `structured`, `JSON`.
   - **Drop rationale tails** — why it exists is not its name: cut `... to reduce token usage`, `... for downstream analysis`, `... so that ...`.
   - **Drop the input plumbing** — `... from multiple test sessions`, `... about completed sessions` are usually noise; keep an object qualifier only when it distinguishes this call site from a sibling.

   Examples (observed → factual): "Stream conversational chat responses about completed test sessions" → `Answer questions about a test session`; "Summarize conversation history into cached message to reduce token usage" → `Compact conversation history`; "Generate aggregate UX analysis report from multiple test sessions" → `Generate aggregate UX report`; "Extract episodic memories from session action steps via background worker" → `Extract episodic memories`.

After both return, read only the manifests. Print:

```
Phase A done: domain=<x>; <N> invariants (<high>/<medium>/<low>); regulatory: [<regimes>] | <M> call sites; redaction_state=<>
```

If the product subagent set `coverage_deferred: true`, spawn a tiny serial follow-up subagent that reads `invariants.yaml` and the call-site shards, computes `invariant_coverage`, and rewrites `invariants.yaml` in place.

Lock phase A:

```bash
python3 "$PLUGIN/pipeline_io.py" lock A \
  tessary-evals/pipeline/product_profile.yaml \
  tessary-evals/pipeline/invariants.yaml \
  tessary-evals/pipeline/call_sites/*.yaml \
  --evals-dir tessary-evals
```

### Phase B — Triage

**Pack discovery + interview.** Stays in main context. Bundle paths:

```bash
for f in "$PLUGIN/packs"/*/pack.yaml; do ... ; done
for f in "$REPO/.tessary-evals-packs"/*/pack.yaml 2>/dev/null; do ... ; done
```

Evaluate `applies_when.always` / `applies_when.auto_signals` against `product_profile.yaml` summary fields and the call-site manifest. Categorize each pack: **always-on** (`quality`), **auto-recommended**, **opt-in**, **explicit override**. Print one line per pack.

For each engaged pack, read its `interview.md`, apply pre-fill rules against the phase-A artifacts, batch every genuinely-needed question into a single dialog turn. Compute each pack's `content_digest` (sha256 of `pack.yaml + interview.md + failures.md`, first 16 hex chars). Verify pack manifests against `$PLUGIN/contract/pack.schema.json`. Check `dependencies` / `conflicts`.

Write `tessary-evals/pipeline/packs.yaml`:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "$PLUGIN"); import pipeline_io, json
pipeline_io.write_packs("tessary-evals", json.loads('''<packs json>'''))
PY
```

**Rank call sites.** Main-agent inline reasoning over the phase-A manifest. Signals, in order of weight:

1. **Trace anchoring** — Path A sites outrank Path B sites; among Path A, higher `observed.sample_count` wins.
2. **User-facing surface** — sites whose use_case / file_hint indicate a user-visible surface (UI chat, transactional email, support response) outrank purely-internal helpers.
3. **Data sensitivity / regulatory exposure** — sites whose surrounding code touches `product_profile.data_sensitivity` kinds or `regulatory_context` regimes get a bump.
4. **Path-prominence heuristic for Path B** — public route paths (`/api/v1/...`), exported top-level functions, and modules referenced from the repo's entrypoint outrank deeper utility modules.

Produce a full ordering. Print the top 3 with one-line reasons and a single y/n prompt:

```
Top call sites by impact:
  1. <id_a> — <reason>
  2. <id_b> — <reason>
  3. <id_c> — <reason>
I'll process them in this order; proceed? (y / "start with <id>" / "reorder")
```

Write `tessary-evals/pipeline/priorities.yaml` as `{"call_site_ids": [<id_a>, <id_b>, ...]}` and lock phase B:

```bash
python3 "$PLUGIN/pipeline_io.py" lock B \
  tessary-evals/pipeline/packs.yaml tessary-evals/pipeline/priorities.yaml \
  --evals-dir tessary-evals
```

### Phase C — Per-site loop

For each `call_site_id` in `priorities.yaml`, in order. **Track wall time for each iteration** — sites 1 and 2 set the per-site cost baseline used by the adaptive gate.

**Step C.1 — Per-site subagent (steps 2+3+4 for this one site).** One Agent call (not a fan-out batch). Subagent reads `prompts/per_site_kit.md` and follows it end-to-end. The kit hypothesizes all 11–26 failure modes; the orchestrator decides which get graded now.

Subagent prompt template:

```
You are a per-call-site subagent for synthesize-graders. Your instruction
document is at $PLUGIN/prompts/per_site_kit.md — read it once and follow it
end-to-end for the single call site assigned below.

CALL SITE: <id>

INPUT PATHS
- Plugin root:        <abs $PLUGIN>
- Repo root:          <abs repo>
- Call-site shard:    <abs path to tessary-evals/pipeline/call_sites/<id>.yaml>
- Product profile:    <abs path to tessary-evals/pipeline/product_profile.yaml>
- Invariants:         <abs path to tessary-evals/pipeline/invariants.yaml>
- Packs:              <abs path to tessary-evals/pipeline/packs.yaml>
- Pack failures.md:   <list of abs paths to each engaged pack's failures.md>

Return ONLY the manifest specified at the bottom of per_site_kit.md.
```

**Step C.2 — Dedup (deterministic) — before marking deferred or grading.** Run `python3 "$PLUGIN/dedup.py" tessary-evals/`. Dedup is intra-site (it only merges failures that share a `call_site_id` / `chain_id`, never across sites) and byte-stable on already-deduped shards, so re-running it each iteration leaves prior sites untouched. **Order matters:** dedup can merge failures and bump severity, so it must run *before* you derive `grader_deferred` (which depends on severity) and *before* grading (so a failure that gets merged away never gets an orphaned grader file).

**Step C.3 — Mark deferred.** Read the deduped `failure_modes/<id>.yaml`. For each entry:

- `severity: high` → set `grader_deferred: false`.
- `severity: medium` or `severity: low` → set `grader_deferred: true` and `grader_id: null`.

Patch the shard in place via Read + Edit, then re-lock:

```bash
python3 "$PLUGIN/pipeline_io.py" lock C-fm tessary-evals/pipeline/failure_modes/<id>.yaml \
  tessary-evals/pipeline/call_sites/<id>.yaml --evals-dir tessary-evals
```

**Step C.4 — Grader synthesis for this site.** Fan out one subagent per non-deferred failure-mode group in parallel inside a single Agent message. Author discovery and per-grader template are described under "Grader subagent template" below. Before spawning each subagent, run `python3 "$PLUGIN/pipeline_io.py" check-file tessary-evals/graders/<grader_id_safe>.yaml --evals-dir tessary-evals` — if exit 0, skip (already emitted in a prior partial run). Lock each emitted grader file as the subagent returns.

**Step C.5 — Bookkeeping.** Run, in order:

```bash
python3 "$PLUGIN/audit.py"    tessary-evals/ --partial
python3 "$PLUGIN/finalize.py" tessary-evals/ --partial
python3 "$PLUGIN/viewer.py"   tessary-evals
```

`audit.py --partial` is informational only — it never exits non-zero and suppresses checks that need every call site to be processed (generic-failure-repeated and pack_no_contribution). `finalize.py --partial` threads through to the embedded `validate.py --bundle` call so deferred failure modes don't trip the FM↔grader bijection check, and writes `sites_completed` / `sites_total` / `deferred_failure_count` into `pipeline/meta.yaml`.

**Step C.6 — Status line.** Print exactly one line:

```
Phase C site <i>/<n> [<id>]: <H> high-severity graders emitted; <D> failures deferred. Viewer: tessary-evals/index.html
```

**Step C.7 — Approval gate. This is a HARD STOP, not a printed question.**

The gate only works if you actually return control to the user. Printing a question and then continuing in the same turn is the bug this step exists to prevent — it silently burns the whole session. To stop correctly you must **end your turn**: print the status line and the prompt, then **emit no further tool calls and produce no further output**. Do not pre-fetch the next site, do not spawn the next subagent, do not "keep going while waiting." The run resumes only when the user sends their next message.

Mechanically:

1. After the gated site/batch finishes (status line already printed in C.6), print the gate prompt for that boundary (below).
2. **Stop. End the turn. Wait for the user.** The next site does not begin until the user replies.
3. When the user replies, honor it: `y`/`yes`/`continue` → proceed; a number `N` → process the next N sites then gate again; `pause`/`stop`/`no` → exit cleanly (the SHA-verified lock lets them resume next session); `start with <id>` / `reorder` → adjust `priorities.yaml` and continue.

Gate boundaries (where you must stop):

- **After site 1 completes** — always. Prompt: `Site 1 of <n> done. Continue to <next_id>? (y / pause)`.
- **After site 2 completes** — always. Compute `mean_sec = (t1 + t2) / 2` and `K = min(remaining, max(1, floor(600 / mean_sec)))`. Prompt: `Sites 1 & 2 averaged ~<round(mean_sec)>s each. I can do the next K sites in ~<round(K * mean_sec / 60)> min before checking in again. Proceed? (y / pick N / pause)`.
- **After each subsequent batch of K sites** — re-measure mean per-site wall time on the batch just finished, re-propose K, stop again.
- `--pause-every N` overrides the adaptive batch: stop every N sites regardless.

The first two stops (sites 1 and 2) are non-negotiable even if the user earlier said "go fast" or "don't ask me" — the whole point is an early preview before committing the session. If the user wants zero gates, that is the `--complete all` flow on an already-previewed run, not the first sweep.

Never process the entire `priorities.yaml` in one unattended turn. If you ever find yourself about to start site 2's work without having stopped after site 1, that is the bug — stop instead.

### Phase D — Chains + taxonomy (end-of-Phase-C wrap-up)

Run only after Phase C has processed every site in `priorities.yaml` (not after each site). Mid-stream chain detection and taxonomy re-clustering just churn the shards.

**D.1 — Chain detection** (skip if `priorities.yaml` length < 2). One subagent (`subagent_type: general-purpose`) passing plugin root, repo root, `tessary-evals/` root, the list of call-site shard paths, and `$PLUGIN/prompts/analyze_chains.md`. Writes `chains.yaml` + `failure_modes/_chains.yaml`.

**D.2 — Dedup.** Run `python3 "$PLUGIN/dedup.py" tessary-evals/`. As in Phase C, dedup runs before deferral and grading so it can settle chain-failure severities and merges without orphaning graders.

**D.3 — Mark deferred for chain failures.** Apply the same rule to `failure_modes/_chains.yaml`: `severity: high` → `grader_deferred: false`; medium/low → `grader_deferred: true` and `grader_id: null`.

**D.4 — Taxonomy.** One subagent reads every failure-modes shard, clusters all failure modes (single_call + chain) into a 2-level taxonomy with 6–15 top-level nodes, writes `taxonomy.yaml`, and patches `taxonomy_node_id` back onto each failure-mode entry shard-by-shard via Read + Edit. (Taxonomy runs before grading so `taxonomy_node_id` can be spliced onto each grader.)

**D.5 — Grader synthesis for chains** (skip if no chains). Same fan-out pattern as C.4, applied to chain-scope failure modes that are not deferred.

**D.6 — Final pass.**

```bash
python3 "$PLUGIN/audit.py"    tessary-evals/ --partial
python3 "$PLUGIN/finalize.py" tessary-evals/ --partial
python3 "$PLUGIN/viewer.py"   tessary-evals
```

(Audit and finalize stay in `--partial` mode while any failure mode remains deferred; the bundle is consistent, just not exhaustively graded.)

Lock phase D:

```bash
python3 "$PLUGIN/pipeline_io.py" lock D \
  tessary-evals/pipeline/chains.yaml \
  tessary-evals/pipeline/failure_modes/_chains.yaml \
  tessary-evals/pipeline/taxonomy.yaml \
  --evals-dir tessary-evals
```

Print:

```
Synthesis complete: <K> graders emitted across <S> sites; <D> failures deferred. Run /evals:synthesize-graders --complete <call_site_id> to flesh out deferred failures for a site.
```

Then the platform-specific viewer-open line (see "Viewer open command" below).

### Phase E — Deep grade on demand

Triggered by `/evals:synthesize-graders --complete <call_site_id>` or `--complete all`.

1. For each targeted site: read `failure_modes/<id>.yaml`, flip `grader_deferred: true → false` for medium/low entries. Patch via Read + Edit; re-lock the shard.
2. Re-run Step C.4 (grader fan-out) for that site. `check-file` already skips emitted graders, so this only spawns subagents for the freshly-undeferred failures. The failures already carry a `taxonomy_node_id` from Phase D — splice the existing value; do **not** re-cluster the taxonomy (the failure set isn't changing, only the deferred flag, so re-clustering would only risk making already-emitted graders' `taxonomy_node_id` stale). Dedup is likewise unnecessary — these failures already survived it.
3. Run `audit.py` + `finalize.py` + `viewer.py` (`--partial` if other sites still have deferrals; otherwise plain).
4. `--complete all` iterates over `priorities.yaml` and applies the same adaptive approval gate as Phase C.

When the final remaining site has zero `grader_deferred: true` failures, `finalize.py` runs in non-partial mode and `validate.py --bundle` is the authoritative gate.

### Grader subagent template (used by C.3 and D.3)

Author discovery:

1. **`evals-prompt`** skill — prefer if available.
2. **`authors/default`** — bundled fallback at `$PLUGIN/authors/default/AUTHOR.md`.

Print `Using grader author <name>` once at first use. Per-subagent prompt:

```
You are synthesizing and calibrating graders for one call site (or chain) as part
of a synthesize-graders run.

CONTEXT
- Plugin root: <abs $PLUGIN>
- Repo: <abs repo>
- Call-site shard path: <abs tessary-evals/pipeline/call_sites/<id>.yaml>     (single_call)
- Failure-modes shard path: <abs tessary-evals/pipeline/failure_modes/<id>.yaml> (single_call)
- Chains shard path: <abs tessary-evals/pipeline/chains.yaml>                  (chain)
- Chain-failures shard: <abs tessary-evals/pipeline/failure_modes/_chains.yaml> (chain)
- Product profile path: <abs tessary-evals/pipeline/product_profile.yaml>
- Existing grader files for this call site, if any: <list of paths and locks>
- Grader author: <AUTHOR>
- Author invocation: <skill | bundled-markdown>

PROCESS each failure mode where grader_deferred is falsy (skip deferred ones):
1. If a grader file already exists, load it; pass _meta.locked_fields to the author
   as existing_grader.
2. Author body via the selected author (skill or bundled-markdown). Author-owned
   output shape: $PLUGIN/contract/AUTHORING_CONTRACT.md.
3. Splice orchestrator-owned fields onto the body (id, scope, failure_mode_id,
   call_site_id|chain_id, name, taxonomy_node_id; owner=null; block_on_fail=null;
   cost/latency budgets from observed.*; dataset_refs; _meta provenance with
   author_contract_version=2).
4. Write to tessary-evals/graders/<grader_id_safe>.yaml.
5. Validate: python3 "$PLUGIN/validate.py" tessary-evals/graders/<file>.yaml --pipeline tessary-evals/
   On failure, retry author up to 3x with validator_feedback; after 3 failures,
   write _validation_error and move on.
6. Calibrate self-tests in place (first pass + order-reversed pass for position
   bias). Compute pass_rate, variance, confidence (high if pass>=0.8 var<=0.1;
   medium if pass>=0.5 var<=0.2; else low). Patch via Read+Edit.

RETURN ONLY this YAML manifest (no prose):
  call_site_id: <id>  # or chain_id
  emitted: [<grader_id>, ...]
  failed_validation: [<grader_id>, ...]
  carried_locked: [<grader_id>, ...]
  calibration:
    <grader_id>: { pass_rate, variance, confidence, adversarial_uncaught }
```

The orchestrator sees only the manifests — never grader bodies. The contract is authoritative on the author I/O shape; do not duplicate those rules here.

### Viewer open command

After every viewer rebuild in C.4 and D.4, detect the platform via `uname -s` and print the matching open command:

- macOS (`Darwin`): `Browse the synthesized pipeline visually: open tessary-evals/index.html`
- Linux: `Browse the synthesized pipeline visually: xdg-open tessary-evals/index.html`
- Windows / unknown: `Browse the synthesized pipeline visually: start tessary-evals/index.html`

Then on the next line, print verbatim:

```
The viewer reads only the local files under `tessary-evals/` — nothing leaves your machine until you click through the CTA button.
```

`viewer.py` reads the shards under `tessary-evals/pipeline/`, every `tessary-evals/graders/*.yaml`, and `tessary-evals/report.md` if present, and emits a single self-contained HTML file. The template files under `viewer_template/` are the editable surface.
## Stable IDs

Unchanged from v0.3.

- **Call site ID**: Path B → source-code label, snake_cased. Path A → `sha::<16-hex>` over the normalized representative system prompt.
- **Failure mode ID**: `<call_site_id>::<name>` (single_call), `<chain_id>::<name>` (chain).
- **Chain ID**: `chain::<short_snake_case_label>`.
- **Grader ID**: `<failure_mode_id>::grader`.
- **Taxonomy node ID**: `tax::<slug>` or `tax::<parent>::<sub>`.

Filenames substitute `::` → `__`. This applies to grader files and to shard
files under `pipeline/call_sites/` and `pipeline/failure_modes/`.

## Constraints

- **No network for synthesis.** Purely local reasoning + files.
- **Use the Bash, Read, Grep, Glob tools** to drive the helpers. Subagents are responsible for writing shards; the orchestrator never directly writes shards under `pipeline/` (except via `pipeline_io.write_packs` for `packs.yaml`, which is orchestrator-owned).
- **Stable IDs.** Re-runs produce diffable output.
- **No invented sources.** Every field must be grounded in traces or source code.
- **Show your work between phases.** One-line status per phase and per per-site iteration; the per-site status line format is fixed (see Phase C.6).
- **Stop after site 1 and after site 2 — always.** End the turn and wait for the user; never run the whole priority list unattended. This overrides any prior "go fast / don't ask" instruction. See Phase C.7.
- **Subagents** at Phase A (product profile + call-site discovery), Phase C.1 (one per site), Phase C.4 (one per non-deferred failure group per site), Phase D.1 (chains), Phase D.4 (taxonomy), Phase D.5 (chain graders), and audit-driven targeted fixes. Every other step is deterministic Python or main-agent dialogue.

## Verification (what the user should expect)

A clean run on a small repo (3–4 call sites, 1 chain) with all four packs engaged:

```
Phase A done: domain=B2B sales productivity; 4 invariants (2/2/0 high/medium/low); regulatory: [] | 4 call sites; redaction_state=none
Phase B: pack discovery
  - quality       (always-on) -- engaged
  - security      (auto: regulatory_context [HIPAA]) -- engaged
  - reliability   (auto: traces ingested) -- engaged
  - brand         (auto: brand_voice_signals non-empty) -- engaged
Top call sites by impact:
  1. summarize_meeting_notes — user-facing, 1.2k traced calls/day
  2. extract_action_items — downstream of #1
  3. classify_intent — high-frequency router
I'll process them in this order; proceed? (y / "start with <id>" / "reorder")
> y

Phase C site 1/4 [summarize_meeting_notes]: 6 high-severity graders emitted; 14 failures deferred. Viewer: tessary-evals/index.html
Continue to extract_action_items? (y / pause)
> y

Phase C site 2/4 [extract_action_items]: 5 high-severity graders emitted; 12 failures deferred. Viewer: tessary-evals/index.html
Sites 1 & 2 averaged ~72s each. I can process the next 2 sites in ~3 min. Proceed? (y / pick N)
> y

Phase C site 3/4 [classify_intent]: 4 high-severity graders emitted; 9 failures deferred. Viewer: tessary-evals/index.html
Phase C site 4/4 [render_email_draft]: 5 high-severity graders emitted; 11 failures deferred. Viewer: tessary-evals/index.html

Phase D: detected 1 chain (trace_confirmed); 5 chain failures (3 high → graded, 2 deferred)
Phase D: 18 taxonomy nodes (13 top-level + 5 sub)
Synthesis complete: 23 graders emitted across 4 sites; 48 failures deferred. Run /evals:synthesize-graders --complete <call_site_id> to flesh out deferred failures for a site.
Browse the synthesized pipeline visually: open tessary-evals/index.html
The viewer reads only the local files under `tessary-evals/` — nothing leaves your machine until you click through the CTA button.
```

On a 12-call-site repo with traces, the first sweep typically emits 40–80 high-severity graders (≈25–35% of full-coverage output) and defers the rest. Time-to-first-HTML on site 1 should be 2–3 minutes; the per-site cost stabilizes after sites 1 & 2 and the adaptive gate keeps each batch under roughly 10 minutes wall. Users who want exhaustive coverage run `--complete all` after the first sweep finishes, and the same adaptive gate paces it.
