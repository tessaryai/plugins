# synthesize-graders — changelog & migration notes

This document summarizes every change to `synthesize-graders` since the initial commit (`92a4802`). It is written for **consumers of synthesize-graders output** — the teams whose runners, viewers, CI integrations, or curation tools read `evals/pipeline.yaml` and `evals/graders/*.yaml` — and tells you what your code needs to change to consume the current output cleanly.

> **TL;DR (v0.3, current)**
> - **Pipeline schema bumped from v0.2.0 → v0.3.0.** New top-level `packs[]` block; new `failure_modes[].pack_ids` and `failure_modes[].compliance_tags` (set-valued tags, not part of identity); grader files mirror these tags. New `pack.schema.json` defines manifests.
> - **Four bundled packs ship by default**: `quality` (always-on, free), `security` (addon — covers all governance/regulatory/PII), `reliability` (included — anchored to observed.* stats), `brand` (addon).
> - **New step 0.5 — pack discovery + pre-filled interview.** Interview questions are answered automatically from step-0 product analysis where possible; the user is only asked when no signal exists in the repo.
> - **New step 4.6 — dedup & merge across packs**, with deterministic three-pass merge (exact / semantic / conflict-suffix). The audit was renumbered to step 4.7.
> - **`validate.py`** gains `--pack <id>` filter (coverage matrix + compliance-tag report), `_bundle_pack_resolution`, `_bundle_dedup_uniqueness`, `_bundle_pack_dependencies` checks.
>
> **v0.2 (previous TL;DR — still applies)**
> - **Pipeline schema bumped from v0.0.1 → v0.2.0.** New top-level `runtime` block; new `call_sites[].observed`, `call_sites[].source_spans`, `call_sites[].dataset_path`; new `failure_modes[].layer` value `C`; extended `call_sites[].shape` enum; extended `chains[].detection_method` enum.
> - **Grader contract bumped from v1 → v2.** New author-owned fields: `self_tests[].category`, `applies_when_check`. New orchestrator-owned fields: `self_test_variance`, `_meta` (provenance + locks), operational fields (`owner`, `block_on_fail`, `cost_budget_tokens`, `latency_budget_ms_p95`, `dataset_refs`).
> - **OTel ingestion** uses standard `gen_ai.*` semconv only — no Langfuse-specific attributes.
> - **`validate.py`** gains `--bundle <dir>` mode for global checks (FM↔grader bijection, chain DAG acyclicity, taxonomy reachability, layer-A/B/C coverage gates, lock-file consistency).
> - **New files on disk:** `evals/datasets/<call_site_id>.jsonl` (captured inputs) and `evals/.synth-lock.yaml` (re-run safety).
> - **Targeted regeneration** via `/evals:synthesize-graders --only <id>` for fixing one grader after curator review.

---

## Commit-by-commit history

### `92a4802` — Initial commit (contract v1)

Established the orchestrator pipeline (steps 0–8), the grader-author contract v1, the per-file validator, and a Langfuse-flavored trace ingestion path.

Files: `SKILL.md`, `prompts/`, `output_format.md`, `contract/AUTHORING_CONTRACT.md`, `contract/grader.schema.json`, `validate.py`, `authors/default/AUTHOR.md`.

### `18f66be` — Viewer, license, coherence/SOLID pass

Added `viewer.py` + `viewer_template/` (HTML viewer for the synthesized bundle), `LICENSE`, plus refactors for orthogonality across prompts and SKILL.md. Validator refactored into small per-rule predicates so adding/removing rules stays local.

### `fa57758` — Viewer redesign

Re-themed the viewer as a light-theme inspector with tables + modals. No schema changes.

### Uncommitted changes (this PR — v0.2)

The bulk of the changes documented below. Schema v0.0.1 → v0.2.0, contract v1 → v2.

---

## What's new in v0.3 (packs + dedup + interview pre-fill)

### v0.3.1 — Four high-level packs

`synthesize-graders` now ships four bundled concern-bundle "packs" at `packs/<id>/`:

| Pack | Tier hint | When it's on by default | What it contributes |
|---|---|---|---|
| `quality` | free | always | Layer A/B baseline — faithfulness, helpfulness, calibration, audience-fit, schema/format |
| `security` | addon | `regulatory_context` non-empty, or `data_sensitivity` non-empty, or user-supplied content reaches the prompt | Layer C adversarial robustness + regulatory compliance failures, narrowed by the interview to apply only to regulations / data classes / threat surfaces that exist |
| `reliability` | included | traces ingested with `observed.*` stats | Layer C cost regressions, latency regressions, output variance, fallback hygiene; budgets anchored to observed p95 |
| `brand` | addon | `brand_voice_signals` non-empty, or user-facing call sites exist | Layer A banned-term checks + Layer B tone / voice / persona consistency / competitor handling |

Pack identity lives in the **set-valued** `failure_modes[].pack_ids: [string, ...]` — a failure can belong to multiple packs (e.g. `ai_disclosure_omitted` is both `brand` and `security`). Compliance control mappings travel as `failure_modes[].compliance_tags: [string, ...]`.

**Failure IDs are pack-agnostic**: `<call_site_id>::<failure_name>`. Toggling a pack does not rename or duplicate failures. The only exception is the rare "conflict suffix" case at step 4.6 dedup where two packs propose the same name with materially different rubrics — see § v0.3.3.

`tier_hint` on each pack manifest is **informational only** — the orchestrator and validator never enforce it. Your consuming product reads `pipeline.packs[].tier_hint` and gates enablement in your UI / API.

### v0.3.2 — Step 0.5: pack discovery + pre-filled interview

A new step runs between product analysis (step 0) and call-site discovery (step 1). It does three things:

1. **Discovery**. Loads bundled packs from `$PLUGIN/packs/` and user packs from `$REPO/.evals-packs/`. Each pack's `applies_when.auto_signals` is matched against step-0 artifacts and (after step 1) the call sites. Packs are categorized as *always-on / auto-recommended / opt-in / explicit*.

2. **Pre-filled interview**. Each pack's `interview.md` declares per-question pre-fill rules pointing at step-0 artifacts (e.g. *Q1.regulations pre-fills from `product_profile.regulatory_context`*). The orchestrator:
   - Resolves answers from `product_profile`, `implicit_invariants`, `invariant_coverage`, dependency lists, and observed trace stats whenever possible.
   - Asks the user **only the questions no signal answered**.
   - Records each answer with `source: product_profile | invariants | code | observed | dependency | user` and `evidence: <file path>`.
   - Prints a transparency line per question so the user can see what was inferred vs asked.

3. **Manifest hygiene**. Validates pack manifests against `contract/pack.schema.json`; checks `dependencies` are satisfied and `conflicts` aren't co-engaged.

**What consumers need to do**: read `pipeline.packs[].interview_answers` if you want to surface the resolved Q&A in your UI. Each pack records `content_digest` so re-runs can detect when a pack itself changed (separately from product / trace changes).

### v0.3.3 — Step 4.6: deterministic dedup & merge across packs

The numbered pipeline became `0 → 0.5 → 1 → 2 → 3 → 4 → 4.5 → 4.6 → 4.7 → 5 → 6 → 7 → 8`. The previous step 4.6 audit moved to step 4.7.

The new step 4.6 is a **single deterministic pass** that takes the union of baseline + each pack's contributions + chain failures and produces one canonical `failure_modes:` list. Three passes in order:

1. **Exact merge** — failures sharing `(scope, call_site_id|chain_id, name)` collapse. `pack_ids` and `compliance_tags` union; `severity` takes the max; `layer` takes the most specific (C > B > A); `description` takes the longest non-empty contributor.
2. **Semantic merge** — pairs within the same `(scope, site_or_chain, layer)` group whose names differ only by trivial morphology, or whose descriptions are near-duplicates, merge under the lexicographically smaller name.
3. **Conflict suffix** — failures that survive both passes but still share a name with materially different descriptions disambiguate by appending the second contributor's pack id: `<name>__<pack_id>`. The orchestrator prints a `WARN`. This is the only case pack identity enters a failure name; pack authors are advised to namespace within their pack to avoid it.

Determinism guarantee: given the same step-0/1/4/4.5 inputs and the same engaged packs at the same `content_digest`s, step 4.6 produces byte-identical output across re-runs. The canonical sort (by `scope` → `site_or_chain` → `name`) + lexicographic tiebreakers are the load-bearing pieces.

**Output line**:

```
Step 4.6: dedup — 93 raw failures → 76 canonical (12 exact-merged, 5 semantic-merged, 0 conflict-suffixed); packs contributing: [quality, security, reliability, brand]
```

### v0.3.4 — Step 4.7: audit (renumbered, with pack-aware checks added)

Previously step 4.6. Now reads the **post-dedup** canonical list and adds three new questions to the existing audit:

- Did every engaged pack contribute at least one failure? (A dead pack record is usually an interview problem.)
- Did dedup produce conflict-suffixed names? (Surface for pack maintainer to namespace.)
- Do all `failure_modes[].pack_ids` resolve to a `pipeline.packs[].id`? (A non-resolvable pack id is a step-4.6 bug.)

`validate.py --bundle` enforces all of these deterministically; the audit prompt is the soft check.

### v0.3.5 — `validate.py` extensions

- `_bundle_pack_resolution` — every `pack_ids` entry on a failure mode or grader resolves to `pipeline.packs[].id`.
- `_bundle_dedup_uniqueness` — no two failures share `(scope, call_site|chain, name)` post-dedup. Failure to merge in step 4.6 is now a hard error rather than a silent duplicate.
- `_bundle_pack_dependencies` — declared `dependencies` are also engaged; `conflicts` are not co-engaged.
- `--pack <id>` — narrows the bundle output to one pack and prints a compliance-tag coverage matrix:

  ```
  --pack security: coverage matrix
    failures: 14 ({'A': 1, 'B': 3, 'C': 10})
    graders: 14
    compliance tags:
      EU-AI-Act.Art-13: 4
      EU-AI-Act.Art-15: 6
      HIPAA-164.502: 2
      HIPAA-164.514: 2
      NIST-AI-RMF.MS-2.6: 4
  ```

  Useful for compliance reviewers who want to see one regulation's footprint without reading 90 grader files.

### v0.3 migration checklist

For consumers upgrading from v0.2 → v0.3:

- [ ] **Schema version**: `pipeline.yaml.version` is now `"0.3.0"`. Bump consumer pins.
- [ ] **New top-level `packs[]`**: render in your viewer if you want users to see which packs are active and the interview Q&A. Safe to ignore otherwise.
- [ ] **`failure_modes[].pack_ids` and `compliance_tags`**: render as tag chips. Both are sets; a failure can carry multiple.
- [ ] **Same on graders**: `pack_ids` and `compliance_tags` are mirrored from the failure mode onto the on-disk grader. Already-built filters in your viewer should accept both.
- [ ] **Conflict-suffixed names**: `<name>__<pack_id>` is a legal failure name (rare; only after a pack conflict). Render normally; the pack tags carry the differentiation.
- [ ] **`--pack` filter**: useful for compliance review surfaces. Wire it into your CI / GRC export if you have one.

## What's new in v0.2 (and what you need to do)

### 1. OTel trace ingestion uses standard `gen_ai.*` semconv only

**What changed.** The Path A (traces-provided) ingestion in `SKILL.md` step 1 no longer reads Langfuse-specific attributes (`langfuse.observation.input`) or the non-standard `llm.use_case`. It now exclusively follows the [OTel GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):

- Provider/model: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.model`.
- Operation: `gen_ai.operation.name` (`chat | text_completion | generate_content | embeddings | execute_tool`).
- Messages in: `gen_ai.input.messages` (newer semconv) or span events `gen_ai.{system,user,assistant,tool}.message`.
- Messages out: `gen_ai.output.messages` or `gen_ai.choice` events.
- Token / cost: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`.
- Status / refusal: `status.status_code`, `gen_ai.response.finish_reasons`.

A reference JSONL is in `examples/sample_traces.jsonl`. Both OTLP/JSON and the flatter Python SDK exporter shape are accepted; the orchestrator normalizes them internally.

**What you need to do.** If you produce traces for synthesize-graders, make sure your instrumentation emits `gen_ai.*` attributes — most OTel-native and OpenLLMetry/OpenInference SDKs already do. Vendor-only attributes (`langfuse.*`, `langsmith.*`) are ignored.

### 2. Extended span taxonomy in Path A

**What changed.** The ingestion now distinguishes seven span flavors:

| Flavor | Detection | Treatment |
|---|---|---|
| chat / completion | `gen_ai.operation.name ∈ {chat, text_completion, generate_content}` | Primary call site source. |
| tool / function | `gen_ai.operation.name == "execute_tool"` or `gen_ai.tool.name` set | Own call site with `shape: tool_call`. |
| embedding | `gen_ai.operation.name == "embeddings"` | `shape: embedding`; observability-only. |
| streaming | `gen_ai.choice` events with empty `gen_ai.output.messages` | Output reconstructed from event deltas. |
| errored | `status.status_code == ERROR` or refusal/content_filter finish reason | Feeds `observed.error_rate` / `observed.refusal_rate`; high-signal for Layer B/C. |
| retry duplicate | identical normalized prompt within ≤100ms in same `trace_id` | Collapsed; not double-counted. |
| non-GenAI | no `gen_ai.*` | Ignored. |

**What you need to do.** Nothing if you only consume `pipeline.yaml`. If you run your own ingestion on the same traces, mirror this taxonomy to avoid double-counting retries or misclassifying tool spans as `chat`.

### 3. Sampling, time windowing, and observability stats

**What changed.** Each call site in `pipeline.yaml` now carries an `observed` block populated from the trace window:

```yaml
call_sites:
  - id: ...
    observed:
      first_seen: <iso8601>
      last_seen: <iso8601>
      error_rate: <float>
      refusal_rate: <float>
      p50_latency_ms / p95_latency_ms: <int>
      p50_tokens_in / p95_tokens_in / p95_tokens_out: <int>
      cost_estimate_usd: <float>
      redaction_state: none | partial | redacted | unknown
```

Representative samples for `source_spans` and dataset capture are now **stratified across 5 time buckets** (up to 2 per bucket, cap 10 total). The orchestrator also warns when one call site dominates the trace (> 70% of retained spans) and asks before ingesting traces older than 90 days.

**What you need to do.** Curation tools / runners can now prioritize graders by `observed.error_rate` or budget judge invocations against `observed.p95_*`. If you previously inferred latency/cost from your own telemetry, you can read it from `pipeline.yaml` directly.

### 4. Redaction-aware ingestion

**What changed.** Spans whose content is composed entirely of placeholder tokens (`<REDACTED>`, `[PII]`, `***`, runs of 40+ identical hex chars, masked emails) are no longer hashed into fake call sites. They group under a single explicit `sha::redacted` call site and trigger a warning asking for an unredacted replay sample. Partially redacted spans get `call_sites[].observed.redaction_state: partial` so downstream Layer C "PII leakage" graders can treat the placeholder pattern as the canonical leak shape.

**What you need to do.** If your trace store applies redaction in the pipeline before exporting to JSONL, expect to see a `runtime.redaction_state: redacted` warning and a thin call-site catalog — re-ingest with content capture enabled or accept the synthetic call site.

### 5. New chain detection: `parent_id` trees + ensembles

**What changed in `prompts/analyze_chains.md`.**

- The chain detector now builds a tree per `trace_id` from `parent_id`. Sequential parent → child edges are the primary detection signal.
- Sibling spans with **identical normalized prompts under the same parent** are detected as `detection_method: ensemble` (self-consistency, voting, n>1 sampling) rather than a sequential chain. Combined shape is `ensemble_vote`. Chain emits `ensemble_span_ids: [<hex>, ...]`.
- Two new chain failure categories: **ensemble disagreement masked** (chosen output overrides majority) and **ensemble majority wrong** (consistent agreement on a wrong answer).
- Modelling parallel siblings as a sequential chain is now an explicit anti-pattern.

**What you need to do.** Runner code that fetches outputs for chain graders must support ensemble shape: `chain.call_site_ids` for an ensemble is the same id repeated, and the runner uses `ensemble_span_ids` to fetch N sibling outputs from the trace store.

### 6. New shape enum values

**What changed in `prompts/classify_shape.md` and `pipeline.yaml.call_sites[].shape`.** Added: `embedding`, `rerank`, `guardrail`, `moderation`, `ensemble_vote`. Disambiguation rules made explicit (e.g. "a numeric-vector output is `embedding`, not `extract`").

**What you need to do.** If your viewer or grader runner switches on `shape`, add cases for the new values. Embedding sites won't have judge graders — only observability/cost/latency entries.

### 7. New failure-mode layer: **Layer C — adversarial / operational**

**What changed in `prompts/hypothesize_failures.md`.** Per call site, the orchestrator now produces 11–26 failure modes across **three** layers:

- Layer A: 3–8 mechanical / structural (unchanged).
- Layer B: 5–12 user-centric / judgmental (unchanged).
- **Layer C (new): 3–6 adversarial / operational** — prompt injection, jailbreak, PII/secret leakage, tool-arg exfiltration, cost regression, latency regression, non-determinism, audit-trail loss.

Per-shape priorities table was extended with a Layer C column. Step 4.6 audit now enforces Layer C coverage; step 5 taxonomy gains a `Layer C flavor` cluster (`prompt_injection_resistance`, `pii_leakage`, `secret_leakage`, `tool_arg_exfiltration`, `cost_regressions`, `latency_regressions`, `output_variance`, `audit_trail_loss`).

`failure_modes[].layer` now accepts `A | B | C | null` (chain failures use `null`).

**What you need to do.** Update consumers that group failures by layer (your viewer probably does). The Layer C category is the one a security reviewer will look for first; its graders are typically the highest-severity / `block_on_fail: true`.

### 8. Grader contract v2 — new author-owned fields

**What changed in `contract/AUTHORING_CONTRACT.md` and `contract/grader.schema.json`.**

- **`self_tests[].category`** — required taxonomy of self-test purpose: `clear_pass | clear_fail | near_miss | adversarial | not_applicable`. When `self_tests` has ≥ 4 entries, at least one must be `adversarial` (a sample_output that attempts to manipulate the judge — prompt-injection, role-confusion, fake prior verdict). `validate.py` enforces.
- **`applies_when_check`** — code-evaluable mirror of `applies_when`, required when `kind=deterministic` AND `applies_when` is non-empty. The judge evaluates `applies_when` natural-language; deterministic graders need a predicate a developer can implement as a function.

The default author (`authors/default/AUTHOR.md`) now wraps judge-prompt outputs in nonce-fenced markers (`<<BEGIN_OUTPUT_<nonce>>>` / `<<END_OUTPUT_<nonce>>>`) and instructs the judge to treat the contents as untrusted data — closing the prompt-injection vector on the judge itself.

**What you need to do.**

- If you have a custom grader author skill, declare `contract_version: 2` and emit `self_tests[].category` + `applies_when_check`. v1 authors keep working but will fail validation on the new gates.
- If you write graders by hand, add `category` to each self-test and add at least one adversarial test once you have 4+ tests.
- If your judge runtime executes the rubric, parse the new nonce-fenced output blocks. The runtime mapping (`applicable=false → not_applicable`; `applicable=true,passed=true → pass`; else `fail`) is unchanged.

### 9. New orchestrator-owned grader fields

**What changed in `contract/grader.schema.json` and `output_format.md`.**

| Field | Type | Source |
|---|---|---|
| `self_test_variance` | `float \| null` | Flip rate across order-permuted reruns (step 6 calibration). Position-bias signal. |
| `owner` | `string \| null` | Free-text owner / team handle. |
| `block_on_fail` | `bool \| null` | Override `runtime.severity_policy`. |
| `cost_budget_tokens` | `int \| null` | Soft cap per judge invocation. Defaulted from `observed.p95_tokens_in/out`. |
| `latency_budget_ms_p95` | `int \| null` | Soft cap. Defaulted from `observed.p95_latency_ms × 2`. |
| `dataset_refs` | `[ref, ...] \| null` | Pointers to real inputs — `{trace_id, span_id}`, `{file: "path:line"}`, or `{jsonl_path}`. |
| `_meta` | object | Provenance + lock metadata (see § 11). |

**What you need to do.** Runners can read `dataset_refs` to replay graders against real inputs without re-fetching from the trace store. CI integrations can enforce `block_on_fail` (or fall back to `runtime.severity_policy`). All new fields are optional — v1 consumers will keep working if they ignore them.

### 10. New top-level `runtime` block in `pipeline.yaml`

```yaml
runtime:
  judge_model: <string | null>
  judge_temperature: <float>            # default 0.0
  max_concurrency: <int>                # default 8
  budget_usd_per_run: <float | null>
  severity_policy:
    high: block | warn | report         # default: block
    medium: block | warn | report       # default: warn
    low: block | warn | report          # default: report
  redaction_state: none | partial | redacted | unknown
```

**What you need to do.** Runners and CI integrations should read `runtime.severity_policy` to map severity → gate behavior. Previously you had to guess; now there's a default and a place to override.

### 11. Survivable re-runs: `_meta` block + `.synth-lock.yaml`

**What changed.** Every grader file emitted by step 6 now carries a `_meta` block:

```yaml
_meta:
  author: default | evals-prompt | ...
  author_contract_version: 2
  synthesized_at: <iso8601>
  synth_inputs_digest: <hex>            # SHA-256 over canonical author input
  locked_fields: [judge_prompt, rubric, ...]
  human_edited: <bool>
```

The orchestrator also writes `evals/.synth-lock.yaml` (one SHA-256 per grader file) at the end of every run. On re-run, before doing anything, the orchestrator:

1. Loads the lock file and compares each grader's current hash against it.
2. Reads `_meta.locked_fields` and `_meta.human_edited` on every existing grader.
3. If any divergence or hand-edit is detected, asks the user (or accepts `--force`).
4. Passes `existing_grader.locked_fields` to the author; the author preserves listed fields **verbatim** (rejected by `validate.py` if mutated).

**What you need to do.**

- Curators: set `_meta.locked_fields: [judge_prompt, rubric]` (or similar) on any grader you hand-edit. Future runs will preserve those fields.
- Alternatively, set `_meta.human_edited: true` to skip re-synthesis of that file entirely (orchestrator passes it through untouched).
- CI: don't strip `_meta`. It is the survivability contract.

### 12. New `validate.py --bundle` mode

```bash
python3 validate.py --bundle evals/
python3 validate.py --bundle evals/ --calibration-set human_labels.csv
```

In addition to running every per-file check, bundle mode enforces:

- **FM↔grader bijection** — every `failure_modes[].grader_id` has a file, every file is referenced.
- **Chain DAG acyclicity** — internal cycles (`[A,B,A]` outside ensembles) and cross-chain cycles.
- **Taxonomy reachability** — every `taxonomy_node_id` resolves; no orphan nodes without children or failure modes.
- **Duplicate ID detection** across files.
- **Layer-A/B/C coverage gates** from step 4.6, deterministically (no longer just LLM-time soft check).
- **Lock consistency** — flags grader files that diverge from `.synth-lock.yaml` without `_meta` justification.
- **Optional calibration set** — informational agreement report against a CSV of human verdicts (`grader_id, sample_output, verdict`).

Per-file mode (`python3 validate.py <file>.yaml [--pipeline …]`) is unchanged and still works.

**What you need to do.** CI: replace `for f in evals/graders/*.yaml; do validate.py $f --pipeline ...; done` with a single `validate.py --bundle evals/`. The output is the same shape (exit non-zero on any error, errors on stderr) but catches an entire class of cross-file bugs that per-file mode can't see.

### 13. Captured-input datasets

**What changed.** Path A ingestion writes `evals/datasets/<call_site_id>.jsonl` containing up to 10 stratified representative spans per call site:

```jsonl
{"trace_id": "...", "span_id": "...", "parent_span_id": "...", "timestamp": "...", "input_messages": [...], "observed_output": "...", "observed_finish_reason": "...", "observed_tokens_in": N, "observed_tokens_out": M, "redaction_state": "none"}
```

Spans with `redaction_state: redacted` are filtered out (the runner can't usefully replay them). Each grader's `dataset_refs` includes a `jsonl_path: datasets/<call_site_id>.jsonl` entry pointing at the dataset.

**What you need to do.** Eval runners can now run graders against real inputs without touching the original trace store — just replay each row.

### 14. Targeted regeneration (`--only`)

**What changed.** New invocation pattern documented in `SKILL.md`:

```
/evals:synthesize-graders --only <grader_id|call_site_id|chain_id>
```

Skips steps 0–5; spawns one subagent for the affected call site/chain with the failure-mode list filtered to the named id. The lock file is updated only for the regenerated files. Combine with `--force` to also overwrite `_meta.locked_fields`.

**What you need to do.** This is the daily workflow once the initial pipeline exists. Direct curators here when a grader needs a small fix.

### 15. Per-grader calibration: position bias + adversarial probing

**What changed in `SKILL.md` step 6.** The in-subagent calibration loop now:

- Applies the rubric to each self-test twice — once forward, once with order/iteration reversed. Reports `self_test_variance = (flips / total)`.
- For `category: adversarial` self-tests, verifies the rubric actually catches the injection. If the rubric passes an adversarial output, confidence is demoted to `low` and the manifest flags `adversarial_uncaught: true`.
- Maps to `confidence`:
  - `pass_rate ≥ 0.8 AND variance ≤ 0.1` → `high`
  - `pass_rate ≥ 0.5 AND variance ≤ 0.2` → `medium`
  - else → `low`

**What you need to do.** Trust `confidence` as a signal slightly less than before — `low` no longer just means "thin context", it can also mean "the judge flipped under permutation". Surface `self_test_variance` in your viewer when non-null.

---

## Migration checklist

For a consumer of synthesize-graders output upgrading from v0.0.1 → v0.2:

- [ ] **Schema version**: `pipeline.yaml.version` is `"0.2.0"`. Bump any consumer that pins to `0.0.1`.
- [ ] **`call_sites[].shape`**: handle new values `embedding`, `rerank`, `guardrail`, `moderation`, `ensemble_vote`.
- [ ] **`call_sites[].observed`**: optional, but populate UI / prioritization off it when present.
- [ ] **`call_sites[].source_spans` and `dataset_path`**: deep-link from grader view to traces / replay dataset.
- [ ] **`failure_modes[].layer`**: accept new value `C`. Render Layer C as its own column / section.
- [ ] **`chains[].detection_method`**: accept new value `ensemble`. Render `ensemble_span_ids` in the chain viewer.
- [ ] **`runtime` block**: read `severity_policy` for CI gating. Honor `block_on_fail` per-grader override.
- [ ] **Graders**: read `self_tests[].category` (added in v2); display `adversarial` tests distinctly. Honor `_meta.locked_fields` and `_meta.human_edited` on overwrite.
- [ ] **Datasets**: optionally replay `evals/datasets/<call_site_id>.jsonl` rows through each grader.
- [ ] **Validator**: switch CI from per-file loop to `python3 validate.py --bundle evals/`.
- [ ] **Author skills (if any)**: declare `contract_version: 2` and emit `self_tests[].category` + `applies_when_check`.
- [ ] **Judge runtimes (if any)**: parse the nonce-fenced output delimiters in the default judge prompt.

---

## Backwards compatibility

All new fields are optional. v0.0.1 consumers that ignore unknown keys continue to work — they just won't surface the new signals. The breaking changes are concentrated in:

1. The shape and detection_method enums (new values).
2. `failure_modes[].layer` accepting `C`.
3. The validator's coverage gates and adversarial requirement — graders that don't carry Layer C failures or adversarial self-tests will fail `--bundle` mode.

If you need to ship a strict consumer for v0.0.1 and v0.2 side-by-side, gate on `pipeline.yaml.version`.

---

## References

- [`SKILL.md`](SKILL.md) — orchestrator spec
- [`output_format.md`](output_format.md) — on-disk schemas
- [`contract/AUTHORING_CONTRACT.md`](contract/AUTHORING_CONTRACT.md) — grader-author contract v2
- [`contract/grader.schema.json`](contract/grader.schema.json) — machine-readable schema
- [`prompts/`](prompts/) — per-step reasoning prompts
- [`authors/default/AUTHOR.md`](authors/default/AUTHOR.md) — bundled grader author (v2)
- [`examples/sample_traces.jsonl`](examples/sample_traces.jsonl) — reference OTel GenAI trace shape
- [`packs/`](packs/) — bundled packs (`quality`, `security`, `reliability`, `brand`)
- [`contract/pack.schema.json`](contract/pack.schema.json) — pack manifest schema (v1)
- [`validate.py`](validate.py) — authoritative validator (per-file + `--bundle` + `--pack`)
