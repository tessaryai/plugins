# Output format reference

The skill writes a directory, not a single file. Stick to these schemas exactly so re-running on the same inputs produces stable diffs and the per-grader / bundle validators pass.

```
evals/
  pipeline.yaml              # everything except per-grader bodies
  graders/
    <grader_id_safe>.yaml    # one per grader; id with `::` → `__` for the filename
  datasets/
    <call_site_id>.jsonl     # captured inputs (optional, written by Path A trace ingestion)
  report.md
  index.html                 # built by viewer.py
  .synth-lock.yaml           # content hashes from the last run (re-run safety)
```

`<grader_id_safe>` is the canonical grader ID with `::` replaced by `__`. Example: a grader with `id: persona::memory_citation::grader` is written to `evals/graders/persona__memory_citation__grader.yaml`. The canonical ID *inside* the file still uses `::`.

## `evals/pipeline.yaml`

Top-level keys, in this order:

```yaml
version: "0.3.0"
product_hint: <string | null>

# Packs active for this synthesis. Empty list = baseline-only run.
# Each pack entry records what was discovered at step 0, the interview answers
# (post-pre-fill from product analysis), and a content digest so re-runs are
# stable. See `packs/<pack_id>/pack.yaml` for the manifest schema.
packs:
  - id: <string>                     # pack id (see contract/pack.schema.json)
    name: <string>
    version: <string>
    tier_hint: <free | included | addon | null>
    enabled_by: <auto | explicit | tier_default>
                                     # auto      = applies_when matched at step 0
                                     # explicit  = user passed --pack <id>
                                     # tier_default = consumer-product policy
    interview_answers:               # the resolved Q&A, with provenance
      <question_id>:
        answer: <free-form>
        source: <product_profile | invariants | user | default>
        evidence: <string | null>    # file path or "user reply at <timestamp>"
    contributes_compliance_tags: [<string>, ...]   # final set, narrowed by interview answers
    content_digest: <hex>            # SHA-256 of pack.yaml + interview.md + failures.md;
                                     # lets re-runs notice when a pack itself has changed


product_profile:
  domain: <string | null>
  user_types:
    - role: <string>
      surface: <string>
      constraints: <string>
  business_model: <string | null>
  data_sensitivity:
    - kind: <string>
      evidence: <string>      # "<file path>: <reason>"
  regulatory_context:
    - regime: <string>
      evidence: <string>
  brand_voice_signals:
    - signal: <string>
      evidence: <string>
  notable_dependencies: [<string>, ...]

implicit_invariants:
  - name: <snake_case>
    description: <string>
    confidence: <high | medium | low>
    evidence:
      - <string>              # "<file path>: <reason>"
    applies_to: <"all_call_sites" | [<call_site_id>, ...]>

invariant_coverage:
  - invariant: <name>
    enforced_in: [<call_site_id>, ...]
    likely_gap_in: [<call_site_id>, ...]

# Runtime configuration consumed by downstream eval runners and CI integrations.
# All fields optional; values shown are defaults the orchestrator writes when traces
# are present (so cost/latency budgets are at least anchored to observed numbers).
runtime:
  judge_model: <string | null>           # e.g. "claude-sonnet-4-6"; null = runner default
  judge_temperature: <float>              # default 0.0
  max_concurrency: <int>                  # default 8
  budget_usd_per_run: <float | null>      # soft cap; runner warns when exceeded
  severity_policy:                        # how severities map to CI behavior
    high: <block | warn | report>         # default: block
    medium: <block | warn | report>       # default: warn
    low: <block | warn | report>          # default: report
  redaction_state: <none | partial | redacted | unknown>
                                          # set by Path A ingestion; "redacted" means
                                          # one or more representative prompts were
                                          # composed of placeholder tokens — calibrate
                                          # accordingly.

call_sites:
  - id: <string>                     # source-code label (snake_cased) if discovered statically,
                                     # else sha::<16-hex>. Synthetic hex = first 16 hex chars
                                     # of SHA-256 over the normalized representative system
                                     # prompt (strip outer whitespace, collapse internal
                                     # whitespace runs to single space, lowercase). When no
                                     # system prompt is available on the trace, hash the first
                                     # 512 chars of the first user message instead. Stable
                                     # across re-runs.
    use_case: <string | null>        # human-readable display hint (e.g. OTel span name,
                                     # gen_ai.operation.name, or static label). Not load-bearing
                                     # for identity — id is the source of truth.
    provider: <string>               # "anthropic" / "openai" / "litellm" / "other"
    model: <string | null>
    system_prompt: <string | null>
    shape: <enum>                    # see prompts/classify_shape.md (extended in v0.2:
                                     # adds embedding, rerank, guardrail, moderation,
                                     # ensemble_vote)
    shape_confidence: <enum>         # high / medium / low
    intent: <string>
    constraints:
      - kind: <enum>                 # schema / length / format / refusal / citation / other
        description: <string>
        enforcement: <enum>          # deterministic / judge
    sample_count: <int>

    # Path B (static repo): file_hint + line_hint identify the source.
    file_hint: <string | null>
    line_hint: <int | null>

    # Path A (traces): source_spans link each call site back to the spans that produced it.
    # Up to ~10 representative spans; if more existed, sample_count is the true total.
    source_spans:
      - trace_id: <hex string>
        span_id: <hex string>
        parent_span_id: <hex string | null>
        service_name: <string | null>
        timestamp: <iso8601 | null>

    # Path A: pointer to the captured-inputs dataset for this call site. Empty when no
    # traces were provided.
    dataset_path: <string | null>    # e.g. "datasets/checkout_extractor.jsonl"

    # Path A: observed production stats over the trace window. Drives prioritization,
    # cost/latency budgets, and the audit in step 4.7. All numbers optional individually.
    observed:
      first_seen: <iso8601 | null>
      last_seen: <iso8601 | null>
      error_rate: <float | null>            # fraction of spans with status=ERROR
      refusal_rate: <float | null>          # fraction with finish_reasons containing refusal/content_filter
      p50_latency_ms: <int | null>
      p95_latency_ms: <int | null>
      p50_tokens_in: <int | null>
      p95_tokens_in: <int | null>
      p95_tokens_out: <int | null>
      cost_estimate_usd: <float | null>     # sum across observed spans, when input/output
                                            # tokens and model price are known
      redaction_state: <none | partial | redacted | unknown>
                                            # per-site override of runtime.redaction_state

chains:
  - id: <string>                     # chain::<short_snake_case_label>
    name: <string>
    call_site_ids: [<string>, ...]   # ordered, A first
    detection_method: <enum>         # trace_confirmed / state_mediated / sequential_composition / ensemble
    confidence: <enum>               # high / medium / low
    rationale: <string>
    # For ensembles: list of sibling span IDs so the runner can grade disagreement.
    ensemble_span_ids: [<hex>, ...]  # optional; only when detection_method == ensemble

failure_modes:
  - id: <string>                     # <call_site_id>::<name> OR <chain_id>::<name>.
                                     # Pack identity is NEVER part of the id — packs are
                                     # tags (see pack_ids below). The only exception is
                                     # the rare "conflict suffix" case at step 4.6, where
                                     # two packs propose the same name with materially
                                     # different rubrics; the second is renamed
                                     # <name>__<pack_id>. Validator warns.
    scope: <single_call | chain>
    call_site_id: <string | null>
    chain_id: <string | null>
    name: <string>
    description: <string>
    severity: <enum>                 # low / medium / high
    layer: <A | B | C | null>        # C = adversarial / operational (added in v0.2)
    pack_ids: [<string>, ...]        # set; empty/[] = baseline. Multiple packs can claim
                                     # the same failure — step 4.6 merges them with union
                                     # semantics. Every entry must resolve to pipeline.packs[].id.
    compliance_tags: [<string>, ...] # set; union of contributing packs' tags, narrowed
                                     # by interview answers. Free-form strings.
    taxonomy_node_id: <string>
    grader_id: <string>              # join key into evals/graders/<grader_id_safe>.yaml

taxonomy:
  - id: <string>                     # tax::<slug> or tax::<parent>::<sub>
    name: <string>
    description: <string>
    parent_id: <string | null>
    example_call_site_ids: [<string>, ...]
    example_chain_ids: [<string>, ...]
```

Note: `graders[]` is NOT in `pipeline.yaml`. Graders live in their own files for isolation, per-grader validation, and clean diffs.

## `evals/graders/<grader_id_safe>.yaml`

One file per grader. Required keys (see `contract/grader.schema.json` for the full schema):

```yaml
id: <string>                         # canonical, with `::`
scope: <single_call | chain>
failure_mode_id: <string>
call_site_id: <string | null>        # required when scope == single_call
chain_id: <string | null>            # required when scope == chain
name: <string>                       # human-readable

kind: <llm_judge | deterministic | execution>
applies_when: <string | null>        # natural-language precondition; null when always applicable
applies_when_check: <string | null>  # code-evaluable mirror; required when kind=deterministic
                                     # AND applies_when is non-empty

# Required when kind == llm_judge:
judge_prompt: <string>
rubric: <string>

# Required when kind == deterministic:
deterministic_check: <string>        # description of the code-level check (actual code lives in-app)

# Required when kind == execution:
execution_spec: <string>             # what runs against the live system

self_tests:
  # Single-call form (one synthetic output):
  - sample_output: <string>
    expected_verdict: <pass | fail | not_applicable>
    category: <clear_pass | clear_fail | near_miss | adversarial | not_applicable>
    rationale: <string>
  # OR chain form (N-tuple keyed by call_site_id):
  - call_site_outputs:
      <call_site_id_a>: <synthetic output A>
      <call_site_id_b>: <synthetic output B>
    expected_verdict: <pass | fail | not_applicable>
    category: <enum>
    rationale: <string>

self_test_pass_rate: <float | null>  # filled by step 6 calibration
self_test_variance: <float | null>   # filled by step 6 calibration; flip rate across order-permuted reruns
confidence: <high | medium | low>
rationale: <string>                  # one line; user-impact framing
taxonomy_node_id: <string>           # propagated from failure mode

# Operational fields (all optional). Defaults pulled from runtime.severity_policy.
owner: <string | null>               # e.g. "@oncall-ml"
block_on_fail: <bool | null>         # null = inherit from severity_policy
cost_budget_tokens: <int | null>
latency_budget_ms_p95: <int | null>
pack_ids: [<string>, ...]            # set; propagated from failure_modes[].pack_ids
compliance_tags: [<string>, ...]     # set; propagated from failure_modes[].compliance_tags
dataset_refs:                        # pointers to real inputs (or null/[])
  - trace_id: <hex>
    span_id: <hex>
    label: <string | null>
  - file: <"path:line">
  - jsonl_path: <"datasets/<call_site_id>.jsonl">

# Provenance + lock metadata for survivable re-runs.
_meta:
  author: <string>                   # "default" | "evals-prompt" | ...
  author_contract_version: 2
  synthesized_at: <iso8601>
  synth_inputs_digest: <hex>         # SHA-256 over canonical author input
  locked_fields: [<field>, ...]      # fields a re-run must preserve verbatim
  human_edited: <bool>               # set by curators / tooling

# Optional — present only when validate.py was unable to produce a clean grader after 3 retries.
# Step 6 audit surfaces these.
_validation_error: <string | null>
```

### Validator invariants

The full rule list is in `contract/AUTHORING_CONTRACT.md` § "Invariants the author must satisfy" (canonical for humans) and `contract/grader.schema.json` (canonical for machines). `validate.py` is the enforcer. This document only describes the **on-disk shape**; refer to the contract for the rules.

Bundle-level invariants (FM↔grader bijection, chain DAG acyclicity, duplicate IDs, taxonomy reachability, layer-A/B coverage gates) are enforced by `validate.py --bundle evals/`.

## `evals/datasets/<call_site_id>.jsonl`

Optional. Written by Path A ingestion (one row per representative span captured for that call site). Format:

```jsonl
{"trace_id": "<hex>", "span_id": "<hex>", "parent_span_id": "<hex|null>", "timestamp": "<iso8601>", "input_messages": [{"role":"system|user|assistant|tool","content":"..."}], "observed_output": "<string>", "observed_finish_reason": "<string|null>", "observed_tokens_in": <int|null>, "observed_tokens_out": <int|null>, "redaction_state": "<none|partial|redacted>"}
```

The runner can replay these against each grader without needing to re-fetch the original trace store. Spans with `redaction_state: redacted` should be filtered out unless the runner has a re-hydration pathway.

## `evals/.synth-lock.yaml`

Written at the end of every successful run. Format:

```yaml
version: 1
synthesized_at: <iso8601>
inputs_digest: <hex>                 # SHA-256 over the orchestrator inputs (repo digest + traces digest + product hint)
graders:
  <grader_id_safe>: <content sha256>
  ...
```

On the next run, the orchestrator compares each grader file's current hash against this lock. A divergence on a file whose `_meta.locked_fields` is empty triggers a `WARN: <file> diverged from lock without locked_fields — pass --force to overwrite or set locked_fields to preserve`. With `--force`, files are overwritten regardless.

## `evals/report.md`

```markdown
# Synthesized eval pipeline

**Product hint:** <hint>

**Summary:** <N> call sites, <C> chains, <M> single-call failures + <X> chain failures, <K> graders (<single_K> single-call + <chain_K> chain, <F> failed validation, <L> low-confidence, <A> adversarial-flagged), <T> taxonomy nodes, <P> packs.

## Engaged packs
Per-pack table: id | name | tier_hint | enabled_by | contributed failures | interview Q&A (pre-filled vs asked)

## Product profile
...
## Implicit invariants
...
## Failure taxonomy
...
## Chains
...
## Call sites
...
## Observed production stats
...
## Validation warnings (only when F > 0)

- `<grader_id>` — `<file>` — `<_validation_error>`
```
