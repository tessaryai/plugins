---
name: synthesize-graders
description: Synthesize an eval pipeline for an LLM-using product. Reads a target repo (and optional OTel traces), discovers LLM call sites, hypothesizes failure modes, clusters them into a 2-level taxonomy, fans out grader synthesis (one subagent per call site, delegated to a grader-author skill that conforms to the contract in `contract/AUTHORING_CONTRACT.md`), validates each emitted grader against the schema, and writes a sharded pipeline under `tessary-evals/pipeline/` + `tessary-evals/graders/*.yaml` + `tessary-evals/report.md` + `tessary-evals/index.html` (self-contained visual viewer). Use when the user says "synthesize evals", "bootstrap evals", "generate eval pipeline", or invokes /evals:synthesize-graders.
---

# synthesize-graders — synthesize an eval pipeline from a real codebase

You are running a multi-step synthesis pipeline against a target repo. v0.4
moved every step that produces volume into a subagent so the main context
stays small. The orchestrator's job is to plan fan-outs, run deterministic
Python helpers, and read tiny return manifests — it never holds call-site
bodies, failure-mode descriptions, taxonomy details, or grader bodies in
context.

Numbered steps run **0 → 0.5 → 1 → 2+3+4 → 4.5 → 4.6 → 4.7 → 5 → 6 → 7 → 8**.
Steps 2, 3, and 4 are folded into a single per-call-site subagent.

Output goes to a directory in the **target repo's** working directory:

```
tessary-evals/
  pipeline/
    meta.yaml                         # version, product_hint, runtime
    packs.yaml                        # engaged packs + interview answers
    product_profile.yaml              # step 0
    invariants.yaml                   # implicit_invariants + invariant_coverage
    call_sites/<id>.yaml              # one per call site
    chains.yaml                       # all detected chains
    failure_modes/<call_site_id>.yaml # single_call failures per site
    failure_modes/_chains.yaml        # chain failures
    taxonomy.yaml                     # taxonomy tree
  graders/<grader_id_safe>.yaml       # one file per grader
  datasets/<call_site_id>.jsonl       # captured inputs (Path A only)
  report.md                           # human-readable walkthrough
  index.html                          # self-contained visual viewer
  .synth-lock.yaml                    # SHA-256 of every shard + grader
```

One grader per file is deliberate: emission failures are isolated (re-run one
grader, not the whole batch), diffs are scoped to the grader that changed, and
validation happens per file so a single malformed grader doesn't poison the
pipeline. The same logic now applies to the *pipeline itself* — sharded across
per-artifact files so no single Write call carries the whole synthesis.

**Steps 0 and 1 run in parallel** (one subagent each, single message with two
Agent calls). **Step 2+3+4 fans out one subagent per call site**, batched at
30 per message. **Step 6 fans out one subagent per call site + chain**, also
batched at 30. All other steps are serial — most are deterministic Python
scripts shipped with this plugin.

## Plugin path resolution

All bundled scripts (`validate.py`, `viewer.py`, `dedup.py`, `audit.py`,
`finalize.py`, `pipeline_io.py`) and the OSS fallback author live in this
plugin directory. **Resolve the plugin path once, at the start of the run,
and reuse it.** At step 0, do this via Bash:

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*synthesize-graders*' 2>/dev/null | head -1 | xargs -I{} dirname {} | xargs dirname | xargs dirname)}"
echo "$PLUGIN"
```

Cache the result as `$PLUGIN`. **Never hardcode `.claude/skills/synthesize-graders/`** — that path is not stable across Claude Code plugin layouts.

## Two grader scopes

The pipeline produces graders in two distinct scopes that must remain cleanly separated:

- **`scope: single_call`** — grades one LLM call's output. Layer A (mechanical) and Layer B (judgmental) failures live here.
- **`scope: chain`** — grades a relationship across N call-site outputs in the same logical session. Produced by step 4.5; require a runner that can fetch multiple outputs from one trace.

## Inputs

- **Repo path** (required) — local directory to analyze. If they don't give one, assume CWD and confirm.
- **Traces file** (optional) — JSONL of OpenTelemetry GenAI spans.
- **Product hint** (optional) — 1-2 sentences describing what the product does.
- **Pack selection** (optional) — `--pack <id>` / `--no-pack <id>`. Without flags, step 0.5 auto-discovers from `applies_when` signals. `quality` is always-on.

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

### Targeted regeneration (`--only`)

`--only <grader_id|call_site_id|chain_id>`:

- **`<grader_id>`** — re-synthesize that grader only. Read its call-site shard
  + the relevant `failure_modes/<call_site>.yaml`. Do not re-run steps 0–5;
  do not re-emit any other file. Update the lock entry for that one file.
- **`<call_site_id>`** — re-synthesize every grader for that site. Reads the
  one call-site shard + failure-modes shard.
- **`<chain_id>`** — re-synthesize the chain's graders.

`--only` always respects `_meta.locked_fields`. Combine with `--force` to
override locks (rare).

## Pipeline

Execute the steps **in order**. The DAG:

```
   [Step 0 — product profile subagent]  ┐
                                        ├─ PARALLEL (one message, 2 Agent calls)
   [Step 1 — call-site discovery]       ┘
                       │
                       ▼
   [Step 0.5 — pack discovery + interview]       (main, serial)
                       │
                       ▼
   [Step 2+3+4 — per-call-site subagent fan-out] (batches of 30, parallel within batch)
                       │
                       ▼
   [Step 4.5 — chain analysis subagent]          (serial)
                       │
                       ▼
   [Step 4.6 — dedup.py]                         (deterministic)
                       │
                       ▼
   [Step 4.7 — audit.py + targeted fixes]        (deterministic + targeted fan-out)
                       │
                       ▼
   [Step 5 — taxonomy subagent]                  (serial)
                       │
                       ▼
   [Step 6 — grader fan-out]                     (batches of 30)
                       │
                       ▼
   [Step 7 — finalize.py]                        (deterministic)
                       │
                       ▼
   [Step 8 — viewer.py]                          (deterministic)
```

### Steps 0 + 1 (parallel) — Product profile + Call-site discovery

Send **one message with two Agent tool calls**:

1. **Step 0 subagent** (`subagent_type: Explore`) — pass it `$PLUGIN/prompts/analyze_product.md`, the target repo path, and the absolute path to `<repo>/evals/` (it must create `tessary-evals/pipeline/`). It writes `tessary-evals/pipeline/product_profile.yaml` and `tessary-evals/pipeline/invariants.yaml` and returns a manifest with domain, regulatory regimes, data sensitivity kinds, invariant counts, and `coverage_deferred: true` (because step 1 may still be running).

2. **Step 1 subagent** — choose:
   - **Path A — traces provided**: `subagent_type: general-purpose`. Parse the JSONL (handle OTLP/JSON or flat Python SDK exporter shape), normalize spans, group by normalized system-prompt hash, write one `tessary-evals/pipeline/call_sites/<id>.yaml` per group and `tessary-evals/datasets/<id>.jsonl` per group. The full span taxonomy (chat / tool / embedding / streaming / errored / retry-collapse / non-GenAI) and observability stats (`observed.*` p50/p95/error_rate/refusal_rate/cost) are required as described in v0.3 — those rules are unchanged; only the *output destination* moved to per-site shards. Stratified sampling at up to 10 representative spans per site stays.
   - **Path B — static repo**: `subagent_type: Explore`. Grep for LLM-call patterns; write one shard per discovered call site.

   The subagent returns a manifest: a list of `{id, use_case, provider, sample_count, has_system_prompt, redaction_state, file_hint?}` and the overall `runtime.redaction_state` (worst case across sites).

Wait for both subagents to finish, then read only the manifests. Print:

```
Step 0 done: domain=<x>; <N> invariants (<high>/<medium>/<low>); regulatory: [<regimes>]
Step 1 done: <N> call sites; redaction_state=<>
```

If the step-0 subagent set `coverage_deferred: true`, spawn a tiny serial follow-up subagent that reads `invariants.yaml` and the call-site shards, computes `invariant_coverage`, and rewrites `invariants.yaml` in place. (Keep this subagent small; pass only the file paths.)

**Scale gates** (run after step 1 manifest is in): ≤30 call sites → proceed; 30–50 → confirm with the user; >50 → ask to narrow scope. The gate is a *curatability* check; v0.4 sharding removes the main-context constraint, but a report with 100 call sites is still hard to review.

### Step 0.5 — Pack discovery + interview

Stays in main context. Bundle paths:

```bash
for f in "$PLUGIN/packs"/*/pack.yaml; do ... ; done
for f in "$REPO/.tessary-evals-packs"/*/pack.yaml 2>/dev/null; do ... ; done
```

Evaluate `applies_when.always` / `applies_when.auto_signals` against `product_profile.yaml`'s summary fields (`domain`, `regulatory_context`, `brand_voice_signals`, `data_sensitivity`) and the step-1 manifest — read only what you need.

Categorize each pack: **always-on** (`quality`), **auto-recommended**, **opt-in**, **explicit override**. Print one line per pack as in v0.3.

For each engaged pack, read its `interview.md`, apply pre-fill rules against the step-0 artifacts, batch all genuinely-needed user questions into a single dialogue turn. Record results into the in-memory pack list with `interview_answers` keyed by question id and per-question `source` / `evidence`.

Compute `content_digest` (sha256 of `pack.yaml + interview.md + failures.md`, first 16 hex chars). Verify pack manifests against `$PLUGIN/contract/pack.schema.json`. Check `dependencies` / `conflicts`.

Write `tessary-evals/pipeline/packs.yaml` via Python (the file is small enough for one Write, but using the helper is cleaner):

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "$PLUGIN"); import pipeline_io, json
pipeline_io.write_packs("tessary-evals", json.loads('''<packs json>'''))
PY
```

### Step 2+3+4 — Per-call-site fan-out

**Fan out one subagent per call site.** Cap 30 per message; sequential batches if call_sites > 30. Each subagent runs steps 2 (classify_shape), 3 (extract_intent), and 4 (hypothesize_failures) — see `$PLUGIN/prompts/hypothesize_failures.md` § "Subagent context".

Per-subagent prompt template (fill the angle brackets):

```
You are a subagent in steps 2+3+4 of synthesize-graders. Read the following files
and produce two outputs as documented below.

CONTEXT
- Plugin root:                 <abs $PLUGIN>
- Repo root:                   <abs repo>
- Call-site shard:             <abs path to tessary-evals/pipeline/call_sites/<id>.yaml>
- Product profile:             <abs path to tessary-evals/pipeline/product_profile.yaml>
- Invariants:                  <abs path to tessary-evals/pipeline/invariants.yaml>
- Packs:                       <abs path to tessary-evals/pipeline/packs.yaml>
- Per-pack failures.md prompts: <list of abs paths>

PROMPTS TO APPLY (in order)
1. $PLUGIN/prompts/classify_shape.md
2. $PLUGIN/prompts/extract_intent.md
3. $PLUGIN/prompts/hypothesize_failures.md  -- this prompt's "Subagent context"
   section is the load-bearing artifact for output shape.

OUTPUTS
A. Patch the call-site shard in place (Read + Edit) to add `shape`,
   `shape_confidence`, `intent`, `constraints`. Do not rewrite the file from
   scratch -- preserve the static fields step 1 wrote.
B. Write tessary-evals/pipeline/failure_modes/<call_site_id_safe>.yaml with top-level
   key `failure_modes:` (canonical-sorted list, taxonomy_node_id left empty).

Return ONLY the manifest specified in hypothesize_failures.md (no prose).
```

Read only the manifests. Print after each batch:

```
Step 2+3+4 batch <i>/<n>: <count> sites done; shapes=[<distribution>]; mean failures/site=<X>
```

### Step 4.5 — Chain analysis subagent

One subagent (`subagent_type: general-purpose`). Pass:

- Plugin root, repo root, tessary-evals/ root.
- The list of call_site IDs and shard paths (the manifests from step 4 already
  give you names + paths; the subagent reads each shard).
- Absolute path to `$PLUGIN/prompts/analyze_chains.md` — the "Subagent context"
  section at the bottom describes its output shape and tells it to write
  `chains.yaml` + `failure_modes/_chains.yaml` directly.

Read only the manifest. Print:

```
Step 4.5: detected <N> chains (<methods>); <M> chain failures
```

If the system has clearly independent call sites, an empty `chains: []` is a valid result.

### Step 4.6 — Dedup (deterministic)

```bash
python3 "$PLUGIN/dedup.py" tessary-evals/
```

`dedup.py` reads every `tessary-evals/pipeline/failure_modes/*.yaml` shard, runs the
three-pass dedup (exact → semantic via SequenceMatcher ≥ 0.85 → conflict
suffix) deterministically, and rewrites each shard in place. Print line
matches v0.3 wording.

### Step 4.7 — Audit (deterministic + targeted fix subagents)

```bash
python3 "$PLUGIN/audit.py" tessary-evals/
```

The script emits a JSON punch list. For each item, choose:

- `layer_a_undercoverage` / `layer_b_undercoverage` / `layer_c_undercoverage`
  / `invariant_gap_uncovered` / `generic_failure_repeated` → spawn a targeted
  subagent for that **call_site** with the failure-modes shard path and the
  audit item description; it adds 2–4 new failures to the shard and returns
  the updated count.
- `chain_undercoverage` / `chain_low_confidence_no_evidence` → spawn a
  subagent for the chain.
- `pack_no_contribution` → spawn a subagent to re-apply that pack's
  `failures.md` across all engaged call sites.
- `conflict_suffix_present` / `unresolved_pack_id` → main agent only;
  surface as a WARN line and continue.
- `high_severity_skew_mechanical` → flag in `report.md`; do not block.

Targeted fix subagents go out in **one parallel batch** (cap 30) per audit
run. Re-run `audit.py` after the batch. If items remain after two passes,
print a WARN and continue — the bundle validator at step 7 is the final gate.

### Step 5 — Taxonomy subagent

One subagent (`subagent_type: general-purpose`). Pass:

- Plugin root, tessary-evals/ root.
- The list of failure-modes shard paths.

The subagent reads every shard, clusters all failure modes (single_call +
chain) into a 2-level taxonomy with 6–15 top-level nodes (subcategories
encouraged). Writes `tessary-evals/pipeline/taxonomy.yaml`. Patches `taxonomy_node_id`
back onto each failure-mode entry **shard-by-shard** via Read+Edit. Returns:

```yaml
step: 5
node_count: <int>
top_level_count: <int>
uncategorized_count: <int>
```

Use the v0.3 node-name conventions (snake_case, plural where appropriate;
keep chain-flavor nodes their own cluster).

### Step 6 — Synthesize graders + calibrate self-tests (parallel fan-out)

Discovery and subagent template are unchanged from v0.3 except for the input
paths. Author discovery:

1. **`evals-prompt`** skill — prefer if available.
2. **`authors/default`** — bundled OSS fallback at `$PLUGIN/authors/default/AUTHOR.md`.

Print `Step 6: using grader author <name>`. Spawn one subagent per call site
+ one per chain, batch of 30 per message.

Per-subagent prompt template (changed lines marked with [v0.4]):

```
You are synthesizing and calibrating graders for one call site (or chain) as part
of a synthesize-graders run.

CONTEXT
- Plugin root: <abs $PLUGIN>
- Repo: <abs repo>
- [v0.4] Call-site shard path: <abs tessary-evals/pipeline/call_sites/<id>.yaml>     (single_call)
- [v0.4] Failure-modes shard path: <abs tessary-evals/pipeline/failure_modes/<id>.yaml> (single_call)
- [v0.4] Chains shard path: <abs tessary-evals/pipeline/chains.yaml>                  (chain)
- [v0.4] Chain-failures shard: <abs tessary-evals/pipeline/failure_modes/_chains.yaml> (chain)
- [v0.4] Product profile path: <abs tessary-evals/pipeline/product_profile.yaml>
- Existing grader files for this call site, if any (re-run): <list of paths and locks>
- Grader author: <AUTHOR>
- Author invocation: <skill | bundled-markdown>

FOR EACH FAILURE MODE in the relevant shard (filter by call_site_id or chain_id):
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

The orchestrator sees only the manifests — never grader bodies. The contract
is authoritative on the author I/O shape; do not duplicate those rules here.

### Step 7 — Finalize (deterministic)

```bash
python3 "$PLUGIN/finalize.py" tessary-evals/ \
  --version 0.4.0 \
  --product-hint "<hint or empty>"
```

`finalize.py`:

1. Writes `tessary-evals/pipeline/meta.yaml` (version + product_hint + runtime).
2. Generates `tessary-evals/report.md` from the shards (no Write tool call in the
   main agent; this happens in the script).
3. Writes `tessary-evals/.synth-lock.yaml` with SHA-256 of every shard + every
   grader file.
4. Runs `python3 $PLUGIN/validate.py --bundle tessary-evals/` and propagates the
   exit code.

If `validate.py --bundle` reports errors, surface them, but the shards stay
on disk — the user can fix and re-run with `--only` for affected ids.

### Step 8 — Build the HTML viewer

```bash
python3 "$PLUGIN/viewer.py" tessary-evals
```

Accepts `--cta-url` / `--cta-label`. Then, detect platform via `uname -s` and
print the matching open command:

- macOS (`Darwin`): `Browse the synthesized pipeline visually: open tessary-evals/index.html`
- Linux: `Browse the synthesized pipeline visually: xdg-open tessary-evals/index.html`
- Windows / unknown: `Browse the synthesized pipeline visually: start tessary-evals/index.html`

Then on the next line, print verbatim:
```
The viewer reads only the local files under `tessary-evals/` — nothing leaves your machine until you click through the CTA button.
```

`viewer.py` reads the shards under `tessary-evals/pipeline/`, every `tessary-evals/graders/*.yaml`, and `tessary-evals/report.md` if present, assembles them into the in-memory pipeline view, and emits a single self-contained HTML file — no server, no network, no build step. The template files under `viewer_template/` (`template.html`, `styles.css`, `app.js`) are still the editable surface.

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
- **Use the Bash, Read, Grep, Glob tools** to drive the helpers. Subagents are responsible for writing shards; the orchestrator never directly writes shards under `pipeline/` (except via `pipeline_io.write_packs` for `packs.yaml`, which is small and orchestrator-owned).
- **Stable IDs**. Re-runs produce diffable output.
- **No invented sources.** Every field must be grounded in traces or source code.
- **Show your work between steps.** One-line status per step.
- **Subagents at steps 0, 1, 2+3+4, 4.5, 5, 6, and audit-driven targeted fixes.** Every other step is deterministic Python or main-agent dialogue. Do not spawn subagents at step 0.5, 4.6, 4.7, 7, or 8.

## Verification (what the user should expect)

A clean run on a small repo (3–4 call sites, 1 chain) with all four packs engaged:

```
Step 0 done: domain=B2B sales productivity; 4 invariants (2/2/0 high/medium/low); regulatory: []
Step 1 done: 4 call sites; redaction_state=none
Step 0.5: pack discovery
  - quality       (always-on) -- engaged
  - security      (auto: regulatory_context [HIPAA]) -- engaged
  - reliability   (auto: traces ingested) -- engaged
  - brand         (auto: brand_voice_signals non-empty) -- engaged
Step 2+3+4 batch 1/1: 4 sites done; shapes=[summarize, rag_answer, extract, draft]; mean failures/site=22
Step 4.5: detected 1 chain (trace_confirmed); 5 chain failures
Step 4.6: dedup -- 93 raw failures -> 76 canonical (12 exact-merged, 5 semantic-merged, 0 conflict-suffixed); packs contributing: [brand, quality, reliability, security]
Step 4.7: audit passed -- no items.
Step 5: 19 taxonomy nodes (13 top-level + 6 sub)
Step 6: using grader author evals-prompt; fanned out 5 subagents (4 sites + 1 chain) -- 76 graders (0 failed validation; 51 high, 19 medium, 6 low)
tessary-evals/ written: 4 call sites | 1 chain | 76 failures | 76 graders (0 failed validation, 6 low-confidence) | 19 taxonomy nodes | 4 packs
Step 8: wrote tessary-evals/index.html
Browse the synthesized pipeline visually: open tessary-evals/index.html
The viewer reads only the local files under `tessary-evals/` — nothing leaves your machine until you click through the CTA button.
```

For a 12-call-site repo with traces, expect ~140–200 single-call graders + ~10–30 chain graders. The main agent context now holds only manifests; the failure mode is no longer context exhaustion but subagent-token spend across batches. If the user reports a slow run, the cost is in step 2+3+4 and step 6 fan-outs — both batched at 30 per message; you can lower the batch size as a polite-throttle if needed (do not raise it).
