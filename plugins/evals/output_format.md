# Output format reference

The skill writes a directory of shards, not a single file. v0.4.0 broke the old
single-`pipeline.yaml` layout into one shard per logical artifact so each shard
is small enough to be written by a single subagent and the orchestrator never
holds the full pipeline content in context.

Stick to these schemas exactly so re-running on the same inputs produces stable
diffs and the per-grader / bundle validators pass.

```
tessary-evals/
  pipeline/
    meta.yaml                          # version, product_hint, runtime
    packs.yaml                         # engaged packs + interview answers
    product_profile.yaml               # step-0 product profile
    invariants.yaml                    # implicit_invariants + invariant_coverage
    call_sites/<id>.yaml               # one per call site
    chains.yaml                        # all detected chains
    failure_modes/<call_site_id>.yaml  # single_call failures for that site
    failure_modes/_chains.yaml         # chain failures (one file for all)
    taxonomy.yaml                      # full taxonomy tree
  graders/
    <grader_id_safe>.yaml              # one per grader; id with `::` -> `__`
  datasets/
    <call_site_id>.jsonl               # captured inputs (Path A only)
  report.md
  index.html                           # built by viewer.py
  .synth-lock.yaml                     # content hashes from the last run
```

`<grader_id_safe>` is the canonical grader ID with `::` replaced by `__`.
Example: a grader with `id: persona::memory_citation::grader` is written to
`tessary-evals/graders/persona__memory_citation__grader.yaml`. The canonical ID *inside*
the file still uses `::`.

The same filename transformation applies to call-site shards
(`call_sites/<id_safe>.yaml`, no `::` expected in practice but the substitution
is applied defensively) and failure-mode shards
(`failure_modes/<call_site_id_safe>.yaml`).

## Loading the logical pipeline view

Consumers that want the v0.3-style monolithic pipeline mapping can call
`pipeline_io.load_pipeline(evals_dir)` (bundled with the plugin) to assemble
every shard into one in-memory mapping with the same top-level keys
v0.3 emitted (`version`, `product_hint`, `packs`, `product_profile`,
`implicit_invariants`, `invariant_coverage`, `runtime`, `call_sites`, `chains`,
`failure_modes`, `taxonomy`). The shard files on disk remain the source of truth;
the assembled view is never written back to disk during synthesis.

## `tessary-evals/pipeline/meta.yaml`

```yaml
version: "0.7.0"
product_hint: <string | null>

runtime:
  judge_model: <string | null>           # e.g. "claude-sonnet-4-6"; null = runner default
  judge_temperature: <float>              # default 0.0
  max_concurrency: <int>                  # default 8
  budget_usd_per_run: <float | null>      # soft cap; runner warns when exceeded
  severity_policy:
    high: <block | warn | report>         # default: block
    medium: <block | warn | report>       # default: warn
    low: <block | warn | report>          # default: report
  redaction_state: <none | partial | redacted | unknown>

progress:                                 # added in schema 0.7.0 (phased synthesis)
  sites_completed: <int>                  # call sites with all non-deferred graders emitted
  sites_total: <int>                      # call sites discovered
  deferred_failure_count: <int>           # failure modes recorded but not yet graded
```

`version` is the synthesizer's on-disk schema version, not the plugin version.
Bump only when the shard layout or shard schemas change. Current schema is
`0.7.0` (phased synthesis added the `progress` block here, the `priorities.yaml`
shard, and the `grader_deferred` field on failure modes).

## `tessary-evals/pipeline/priorities.yaml`

The order in which phased synthesis processes call sites (added in schema 0.7.0).

```yaml
call_site_ids: [<string>, ...]   # call_site ids, most-important first
ranking_rationale: <string>      # optional; how the order was chosen
```

## `tessary-evals/pipeline/packs.yaml`

```yaml
packs:
  - id: <string>                     # pack id (see contract/pack.schema.json)
    name: <string>
    version: <string>
    tier_hint: <free | included | addon | null>
    enabled_by: <auto | explicit | tier_default>
                                     # auto      = applies_when matched at step 0
                                     # explicit  = user passed --pack <id>
                                     # tier_default = consumer-product policy
    interview_answers:
      <question_id>:
        answer: <free-form>
        source: <product_profile | invariants | user | default>
        evidence: <string | null>
    contributes_compliance_tags: [<string>, ...]
    content_digest: <hex>            # SHA-256 of pack.yaml + interview.md + failures.md
    dependencies: [<pack_id>, ...]   # optional; carried from the pack manifest
    conflicts:    [<pack_id>, ...]   # optional
```

## `tessary-evals/pipeline/product_profile.yaml`

```yaml
product_profile:
  domain: <string | null>
  user_types:
    - role: <string>
      surface: <string>
      constraints: <string>
  business_model: <string | null>
  data_sensitivity:
    - kind: <string>
      evidence: <string>             # "<file path>: <reason>"
  regulatory_context:
    - regime: <string>
      evidence: <string>
  brand_voice_signals:
    - signal: <string>
      evidence: <string>
  notable_dependencies: [<string>, ...]
```

## `tessary-evals/pipeline/invariants.yaml`

```yaml
implicit_invariants:
  - name: <snake_case>
    description: <string>
    confidence: <high | medium | low>
    evidence:
      - <string>                     # "<file path>: <reason>"
    applies_to: <"all_call_sites" | [<call_site_id>, ...]>

invariant_coverage:
  - invariant: <name>
    enforced_in: [<call_site_id>, ...]
    likely_gap_in: [<call_site_id>, ...]
```

## `tessary-evals/pipeline/call_sites/<id>.yaml`

One file per call site. The orchestrator never reads these in bulk; per-step
subagents read only the specific shard they're working on.

```yaml
id: <string>                       # snake_case label (Path B) or sha::<16hex> (Path A)
use_case: <string | null>          # human-readable display hint
provider: <string>                 # "anthropic" / "openai" / "litellm" / "other"
model: <string | null>
system_prompt: <string | null>
shape: <enum>                      # see prompts/per_site_kit.md
shape_confidence: <high | medium | low>
intent: <string>
constraints:
  - kind: <schema | length | format | refusal | citation | other>
    description: <string>
    enforcement: <deterministic | judge>
sample_count: <int>

# Path B (static repo)
file_hint: <string | null>
line_hint: <int | null>

# Path A (traces)
source_spans:
  - trace_id: <hex>
    span_id: <hex>
    parent_span_id: <hex | null>
    service_name: <string | null>
    timestamp: <iso8601 | null>

dataset_path: <string | null>      # e.g. "datasets/<id>.jsonl"

observed:
  first_seen: <iso8601 | null>
  last_seen: <iso8601 | null>
  error_rate: <float | null>
  refusal_rate: <float | null>
  p50_latency_ms: <int | null>
  p95_latency_ms: <int | null>
  p50_tokens_in: <int | null>
  p95_tokens_in: <int | null>
  p95_tokens_out: <int | null>
  cost_estimate_usd: <float | null>
  redaction_state: <none | partial | redacted | unknown>

discovered_at: <iso8601>           # written by step 1 subagent
```

After step 2+3+4 has run, the same shard carries `shape`, `shape_confidence`,
`intent`, and `constraints` (initially absent — step-1 writes only the static /
trace-derived fields).

## `tessary-evals/pipeline/chains.yaml`

```yaml
chains:
  - id: <string>                     # chain::<short_snake_case_label>
    name: <string>
    call_site_ids: [<string>, ...]
    detection_method: <trace_confirmed | state_mediated | sequential_composition | ensemble>
    confidence: <high | medium | low>
    rationale: <string>
    ensemble_span_ids: [<hex>, ...]  # optional; only when detection_method == ensemble
```

## `tessary-evals/pipeline/failure_modes/<call_site_id>.yaml`

One shard per call site, holding only that site's `scope: single_call` failures.

```yaml
failure_modes:
  - id: <string>                     # <call_site_id>::<name>
    scope: single_call
    call_site_id: <string>
    chain_id: null
    name: <string>
    description: <string>
    severity: <low | medium | high>
    layer: <A | B | C>
    pack_ids: [<string>, ...]
    compliance_tags: [<string>, ...]
    taxonomy_node_id: <string>       # populated by taxonomy step
    grader_id: <string | null>       # <failure_mode_id>::grader; null when deferred
    grader_deferred: <bool>          # 0.7.0; true = recorded but no grader emitted yet
```

`grader_deferred` (schema 0.7.0): during the first sweep only `severity: high`
failures are graded (`grader_deferred: false`, `grader_id` set). Medium/low
failures are recorded with `grader_deferred: true` and `grader_id: null` until
the user runs `--complete <call_site_id>`.

## `tessary-evals/pipeline/failure_modes/_chains.yaml`

All chain failures live in one shard (small set, cross-chain visibility helps
during dedup):

```yaml
failure_modes:
  - id: <string>                     # <chain_id>::<name>
    scope: chain
    call_site_id: null
    chain_id: <string>
    name: <string>
    description: <string>
    severity: <low | medium | high>
    layer: null                      # chain failures are not in the A/B/C layering
    pack_ids: [<string>, ...]
    compliance_tags: [<string>, ...]
    taxonomy_node_id: <string>
    grader_id: <string | null>       # null when deferred
    grader_deferred: <bool>          # 0.7.0; same semantics as single_call
```

## `tessary-evals/pipeline/taxonomy.yaml`

```yaml
taxonomy:
  - id: <string>                     # tax::<slug> or tax::<parent>::<sub>
    name: <string>
    description: <string>
    parent_id: <string | null>
    example_call_site_ids: [<string>, ...]
    example_chain_ids: [<string>, ...]
```

## `tessary-evals/graders/<grader_id_safe>.yaml`

One file per grader. Required keys (see `contract/grader.schema.json` for the
full schema):

```yaml
id: <string>                         # canonical, with `::`
scope: <single_call | chain>
failure_mode_id: <string>
call_site_id: <string | null>        # required when scope == single_call
chain_id: <string | null>            # required when scope == chain
name: <string>

kind: <llm_judge | deterministic | execution>
applies_when: <string | null>
applies_when_check: <string | null>  # required when kind=deterministic AND applies_when set

# kind == llm_judge:
judge_prompt: <string>
rubric: <string>

# kind == deterministic:
deterministic_check: <string>

# kind == execution:
execution_spec: <string>

self_tests:
  - sample_output: <string>          # single_call form
    expected_verdict: <pass | fail | not_applicable>
    category: <clear_pass | clear_fail | near_miss | adversarial | not_applicable>
    rationale: <string>
  # or chain form:
  - call_site_outputs:
      <call_site_id_a>: <synthetic output A>
      <call_site_id_b>: <synthetic output B>
    expected_verdict: <pass | fail | not_applicable>
    category: <enum>
    rationale: <string>

self_test_pass_rate: <float | null>  # filled by step 6 calibration
self_test_variance: <float | null>
confidence: <high | medium | low>
rationale: <string>
taxonomy_node_id: <string>

owner: <string | null>
block_on_fail: <bool | null>
cost_budget_tokens: <int | null>
latency_budget_ms_p95: <int | null>
pack_ids: [<string>, ...]
compliance_tags: [<string>, ...]
dataset_refs:
  - trace_id: <hex>
    span_id: <hex>
    label: <string | null>
  - file: <"path:line">
  - jsonl_path: <"datasets/<call_site_id>.jsonl">

_meta:
  author: <string>
  author_contract_version: 2
  synthesized_at: <iso8601>
  synth_inputs_digest: <hex>
  locked_fields: [<field>, ...]
  human_edited: <bool>

# Present only when validate.py was unable to produce a clean grader after 3 retries.
_validation_error: <string | null>
```

### Validator invariants

The full rule list lives in `contract/AUTHORING_CONTRACT.md` (canonical for
humans) and `contract/grader.schema.json` (canonical for machines).
`validate.py` is the enforcer. This document only describes the **on-disk
shape**; refer to the contract for the rules.

Bundle-level invariants (FM↔grader bijection, chain DAG acyclicity, duplicate
IDs, taxonomy reachability, layer-A/B/C coverage gates) are enforced by
`validate.py --bundle tessary-evals/`. The bundle validator assembles the logical
pipeline view from the shards before running its checks.

## `tessary-evals/datasets/<call_site_id>.jsonl`

Optional. Written by Path A ingestion (one row per representative span captured
for that call site).

```jsonl
{"trace_id": "<hex>", "span_id": "<hex>", "parent_span_id": "<hex|null>", "timestamp": "<iso8601>", "input_messages": [{"role":"system|user|assistant|tool","content":"..."}], "observed_output": "<string>", "observed_finish_reason": "<string|null>", "observed_tokens_in": <int|null>, "observed_tokens_out": <int|null>, "redaction_state": "<none|partial|redacted>"}
```

Spans with `redaction_state: redacted` should be filtered out by the runner
unless it has a re-hydration pathway.

## `tessary-evals/.synth-lock.yaml`

Written at the end of every successful run.

```yaml
version: 1
synthesized_at: <iso8601>
inputs_digest: <hex>                 # SHA-256 over the orchestrator inputs (repo digest + traces digest + product hint)
shards:                              # SHA-256 of every pipeline/* shard file
  pipeline/meta.yaml: <hex>
  pipeline/packs.yaml: <hex>
  pipeline/product_profile.yaml: <hex>
  pipeline/invariants.yaml: <hex>
  pipeline/chains.yaml: <hex>
  pipeline/taxonomy.yaml: <hex>
  pipeline/call_sites/<id>.yaml: <hex>
  pipeline/failure_modes/<id>.yaml: <hex>
  pipeline/failure_modes/_chains.yaml: <hex>
graders:
  <grader_id_safe>: <hex>
```

On the next run, the orchestrator compares each grader file's current hash
against the lock. A divergence on a file whose `_meta.locked_fields` is empty
triggers a `WARN: <file> diverged from lock without locked_fields — pass
--force to overwrite or set locked_fields to preserve`. Shard divergences are
informational only — shards under `pipeline/` are orchestrator-owned, not
human-curated, so they are always overwritten on re-run.

## `tessary-evals/report.md`

```markdown
# Synthesized eval pipeline

**Product hint:** <hint>

**Summary:** <N> call sites, <C> chains, <M> single-call failures + <X> chain failures, <K> graders (<single_K> single-call + <chain_K> chain, <F> failed validation, <L> low-confidence, <A> adversarial-flagged), <T> taxonomy nodes, <P> packs.

## Engaged packs
## Product profile
## Implicit invariants
## Failure taxonomy
## Chains
## Call sites
## Observed production stats
## Validation warnings (only when F > 0)
```
