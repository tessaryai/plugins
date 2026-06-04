# Output format reference

The skill writes a directory of shards, not a single file. v0.4.0 broke the old
single-`pipeline.yaml` layout into one shard per logical artifact so each shard
is small enough to be written by a single subagent and the orchestrator never
holds the full pipeline content in context.

Stick to these schemas exactly so re-running on the same inputs produces stable
diffs and the per-grader / bundle validators pass.

```
.tessary/
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
`.tessary/graders/persona__memory_citation__grader.yaml`. The canonical ID *inside*
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

## `.tessary/pipeline/meta.yaml`

```yaml
version: "0.12.0"
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
`0.12.0` (0.7.0 added the `progress` block here, the `priorities.yaml` shard, and
the `grader_deferred` field on failure modes; 0.8.0 added the `quality_dimensions/`
shard and the `kind: score` grader for continuous 1–5 quality scoring; 0.9.0 added
the `invocation` field on call sites so indirect LLM calls — agent CLIs, raw HTTP,
sandbox runners — are discovered and tracked alongside in-process SDK calls; 0.10.0
added `scope: trace` graders (grade the final turn of a multi-turn session given the
prior n-1 messages), the `kind: agentic` grader (binary verdict from an agent in a
sandbox via `agent_spec`), and the agent-session dataset row shape; 0.11.0 added the
`default_grade_mode` field on call sites so multi-turn sites are flagged at discovery
and their graders default to `scope: trace`; 0.12.0 added the `expected_spans` call-site
field (telemetry nomenclature read from the call site's code, for platform span binding)
and the grader `_body_source: platform` marker that defers `judge_prompt`/`rubric`
authoring for `kind=llm_judge`/`score` to the platform — contract v8).

## `.tessary/pipeline/priorities.yaml`

The order in which phased synthesis processes call sites (added in schema 0.7.0).

```yaml
call_site_ids: [<string>, ...]   # call_site ids, most-important first
ranking_rationale: <string>      # optional; how the order was chosen
```

## `.tessary/pipeline/packs.yaml`

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

## `.tessary/pipeline/product_profile.yaml`

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

## `.tessary/pipeline/invariants.yaml`

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

## `.tessary/pipeline/call_sites/<id>.yaml`

One file per call site. The orchestrator never reads these in bulk; per-step
subagents read only the specific shard they're working on.

```yaml
id: <string>                       # snake_case label (Path B) or sha::<16hex> (Path A)
use_case: <string | null>          # human-readable display hint
invocation: <sdk | cli_agent | http | sandbox_agent>  # how the model is reached; default sdk
provider: <string>                 # "anthropic" / "openai" / "litellm" / "other"
model: <string | null>
system_prompt: <string | null>     # often null for cli_agent/sandbox_agent (prompt lives in the external tool)
shape: <enum>                      # see prompts/per_site_kit.md
shape_confidence: <high | medium | low>
default_grade_mode: <per_turn | per_conversation>  # schema 0.11.0; default per_turn.
                                   # per_conversation marks a multi-turn site (agents, chat) whose
                                   # turns share a trace and are graded once over the whole session;
                                   # the orchestrator then authors this site's graders as scope: trace.
                                   # The platform treats this as the default; its per-call-site
                                   # curation toggle overrides it.
intent: <string>
constraints:
  - kind: <schema | length | format | refusal | citation | other>
    description: <string>
    enforcement: <deterministic | judge>
sample_count: <int>

# Path B (static repo)
file_hint: <string | null>
line_hint: <int | null>
surrounding_code: <string | null>  # optional; the code snippet around the call site the discovery
                                   # step read to derive shape/intent/constraints and expected_spans.

# Telemetry nomenclature the call site's instrumentation emits (schema 0.12.0). OPTIONAL,
# best-effort, orchestrator-owned — written by the discovery step from explicit instrumentation
# visible in `surrounding_code` (OTel start_span("…")/start_as_current_span, Langfuse name= /
# @observe(name=) / update_current_observation(name=), logger/tracer names, the enclosing function
# name = the SDK default span name, provider-SDK default naming). Omitted / empty when no hint is
# found. The platform uses it to bind a grader to the right captured spans/traces.
expected_spans:
  - match_field: <name | model | trace_id | metadata.<key>>  # what the matcher keys on
    match_pattern: <string>          # exact string or glob (* / ?), e.g. "checkout_summary"
    kind: <span | trace>             # whether the match identifies a span or a whole trace
    confidence: <high | medium | low>

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

`invocation` (schema 0.9.0) records *how* the model is reached, so indirect calls
stay visible: `sdk` (in-process provider/framework SDK — the default and the only
value pre-0.9.0), `cli_agent` (the repo shells out to an agent/LLM CLI such as
`claude`, `opencode`, `aider`, `ollama`), `http` (raw HTTP to a model endpoint or
gateway, no SDK), `sandbox_agent` (an agent/LLM run inside a sandbox runner such as
e2b/modal/daytona/docker). Absent is treated as `sdk`. Indirect sites usually have
`system_prompt: null` (the prompt lives in the external tool) and no enforced output
schema, which shifts their failure surface (see `prompts/per_site_kit.md`).

## `.tessary/pipeline/chains.yaml`

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

## `.tessary/pipeline/failure_modes/<call_site_id>.yaml`

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

## `.tessary/pipeline/failure_modes/_chains.yaml`

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

## `.tessary/pipeline/quality_dimensions/<call_site_id>.yaml`

One shard per **judgment** call site (added in schema 0.8.0). Quality dimensions are
the continuous "how good is the output" axes scored 1–5 — distinct from failure
modes, which are binary "what went wrong" checks. Each becomes a `kind: score`
grader (see below). Mechanical sites (`embedding`, strict-schema `extract`, pure
`guardrail`/`moderation`) have no shard.

```yaml
quality_dimensions:
  - id: <string>                     # <call_site_id>::<dim_name>
    call_site_id: <string>
    scope: single_call               # v0.8.0 scopes quality dimensions to single_call
    name: <string>                   # snake_case axis name
    description: <string>            # what this axis measures
    why_it_matters: <string>         # why a sustained dip hurts the product
    rubric_levels:                   # anchored 1–5; each a concrete, observable description
      "5": <string>
      "4": <string>
      "3": <string>
      "2": <string>
      "1": <string>
    grader_id: <string>              # <id>::grader — the kind: score grader
```

Quality dimensions are never deferred: every judgment call site must carry at
least one, and each is graded in the first sweep. `validate.py --bundle` enforces
both (a judgment-shape call site with zero quality dimensions is an error, in full
and `--partial` mode alike).

## `.tessary/pipeline/taxonomy.yaml`

```yaml
taxonomy:
  - id: <string>                     # tax::<slug> or tax::<parent>::<sub>
    name: <string>
    description: <string>
    parent_id: <string | null>
    example_call_site_ids: [<string>, ...]
    example_chain_ids: [<string>, ...]
```

## `.tessary/graders/<grader_id_safe>.yaml`

One file per grader. Required keys (see `contract/grader.schema.json` for the
full schema):

```yaml
id: <string>                         # canonical, with `::`
scope: <single_call | chain | trace>
failure_mode_id: <string>
call_site_id: <string | null>        # required when scope == single_call or trace
chain_id: <string | null>            # required when scope == chain
name: <string>

kind: <llm_judge | deterministic | execution | agentic>
_body_source: platform              # v8 — present on kind=llm_judge / score: the verdict body
                                     # (judge_prompt/rubric) is DEFERRED to the platform, which
                                     # expands it on import. Omit for deterministic/execution/agentic.
applies_when: <string | null>       # always LLM-evaluated (inline for judge/score; a
                                     # separate LLM gate for deterministic). No applies_when_check (v6).

# kind == llm_judge:
# judge_prompt / rubric are NOT emitted by the plugin in v8 — they carry `_body_source: platform`
# and the platform authors the judge body on import. (Pre-v8 files may still carry an inline
# judge_prompt+rubric with no _body_source; that shape still validates.)

# kind == deterministic:
deterministic_check: <string>

# kind == execution:
execution_spec: <string>

# kind == agentic (verdict produced by an agent in a sandbox; emitted here, run by the platform):
agent_spec:
  harness: opencode
  sandbox: {image: <string>, network: <none | egress | full>}
  allowed_tools: [<string>, ...]
  task_prompt: <string>              # grading task; ends in one binary decision
  verdict_contract: <string>         # how the agent emits PASS/FAIL
  budgets: {max_turns: <int>, max_cost_usd: <float>, timeout_s: <int>}   # optional

# v7: graders carry NO self_tests. Behavior is calibrated platform-side against golden
# datasets (real labeled spans associated with the grader in evals-platform), not via
# per-grader self-test cases. The self_test_pass_rate / self_test_variance fields are gone.

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
  author_contract_version: 8
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
`validate.py --bundle .tessary/`. The bundle validator assembles the logical
pipeline view from the shards before running its checks.

## `.tessary/datasets/<call_site_id>.jsonl`

Optional. Written by Path A ingestion (one row per representative span captured
for that call site).

```jsonl
{"trace_id": "<hex>", "span_id": "<hex>", "parent_span_id": "<hex|null>", "timestamp": "<iso8601>", "input_messages": [{"role":"system|user|assistant|tool","content":"..."}], "observed_output": "<string>", "observed_finish_reason": "<string|null>", "observed_tokens_in": <int|null>, "observed_tokens_out": <int|null>, "redaction_state": "<none|partial|redacted>"}
```

Spans with `redaction_state: redacted` should be filtered out by the runner
unless it has a re-hydration pathway.

### Agent-session rows (schema 0.10.0)

When the input is an agent-session transcript (Claude Code / opencode and similar
agent runners — see SKILL.md "Path A-agent"), each row captures one **session** as a
turn sequence rather than one span. This is the natural input for `scope: trace`
graders (prior turns → final turn) and `kind: agentic` graders (which re-inspect the
repo). Fields beyond the span shape above:

```jsonl
{"session_id": "<string>", "call_site_id": "<string>", "invocation": "<cli_agent|sandbox_agent>", "messages": [{"role": "<user|assistant|tool>", "content": "<string>", "tool_calls": [<obj>, ...], "tool_results": [<obj>, ...]}], "repo_state": {"commit": "<sha|null>", "git_diff": "<unified diff text|null>"}, "redaction_state": "<none|partial|redacted>"}
```

`messages` is the ordered turn+tool sequence. `repo_state` is optional and captured
**per turn or per session boundary** so the git diff between two turns is available as
text — a normal `llm_judge`/`trace` grader can read it directly, or a `kind: agentic`
grader can recompute it in the sandbox. Omit `repo_state` when the session did not
mutate a repo. These dataset rows are also the substrate for **golden datasets** — the
spans a curator marks golden and labels per grader to calibrate it platform-side (v7).

**Sourcing a `scope: trace` grader's history (schema 0.11.0).** The canonical source is
**the final turn's self-contained input**: in practice (Langfuse / Claude-Code-style
instrumentation) each turn's logged `input` already contains the full prior transcript,
so the runner grades a multi-turn site by taking the **latest turn per trace** and
judging its transcript-bearing input + final output — no per-turn stitching. The
agent-session `messages[]` shape above is therefore **not required** for trace
`llm_judge` graders; it is retained for `kind: agentic` graders (which re-inspect the
repo) and for instrumentation that does *not* carry the whole transcript on the final
turn.

## `.tessary/.synth-lock.yaml`

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

## `.tessary/report.md`

```markdown
# Synthesized eval pipeline

**Product hint:** <hint>

**Summary:** <N> call sites, <C> chains, <M> single-call failures + <X> chain failures, <K> graders (<single_K> single-call + <chain_K> chain, <F> failed validation, <L> low-confidence), <T> taxonomy nodes, <P> packs.

## Engaged packs
## Product profile
## Implicit invariants
## Failure taxonomy
## Chains
## Call sites
## Observed production stats
## Validation warnings (only when F > 0)
```
