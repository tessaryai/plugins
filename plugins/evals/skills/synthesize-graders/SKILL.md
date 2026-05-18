---
name: synthesize-graders
description: Synthesize an eval pipeline for an LLM-using product. Reads a target repo (and optional OTel traces), discovers LLM call sites, hypothesizes failure modes, clusters them into a 2-level taxonomy, fans out grader synthesis (one subagent per call site, delegated to a grader-author skill that conforms to the contract in `contract/AUTHORING_CONTRACT.md`), validates each emitted grader against the schema, and writes `evals/pipeline.yaml` + `evals/graders/*.yaml` + `evals/report.md` + `evals/index.html` (self-contained visual viewer). Use when the user says "synthesize evals", "bootstrap evals", "generate eval pipeline", or invokes /evals:synthesize-graders.
---

# synthesize-graders — synthesize an eval pipeline from a real codebase

You are running a multi-step synthesis pipeline against a target repo. Numbered steps run **0 → 0.5 → 1 → 2 → 3 → 4 → 4.5 → 4.6 → 4.7 → 5 → 6 → 7 → 8**; 0.5 is pack discovery + interview, 4.5/4.6/4.7 are interstitials (chain analysis, dedup, audit) inside the same reasoning thread as step 4. Each step has a dedicated prompt under `prompts/` or `packs/<pack>/`. Output goes to a directory in the **target repo's** working directory:

```
evals/
  pipeline.yaml                  # product profile, invariants, call sites, chains, failure modes, taxonomy
  graders/<grader_id_safe>.yaml  # one file per grader — judge_prompt, rubric, applies_when, self_tests
  report.md                      # human-readable walkthrough
  index.html                     # self-contained visual viewer
```

One grader per file is deliberate: emission failures are isolated (re-run one grader, not the whole batch), diffs are scoped to the grader that changed, and validation happens per file so a single malformed grader doesn't poison the pipeline.

Most synthesis reasoning happens in this Claude Code session. **Step 6 fans out — one subagent per call site (and per chain)** — so a 12-call-site repo doesn't serialize 150 sequential grader emissions through one context window. Each subagent invokes a **grader author** (see `contract/AUTHORING_CONTRACT.md`), validates each emitted file, and calibrates self-tests before returning. No external API calls; no persistent store between runs; the curation backend reads `evals/` from disk.

## Plugin path resolution

All bundled scripts (`validate.py`, `viewer.py`) and the OSS fallback author live in this plugin directory. **Resolve the plugin path once, at the start of the run, and reuse it.** At step 0, do this via Bash:

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*synthesize-graders*' 2>/dev/null | head -1 | xargs -I{} dirname {} | xargs dirname | xargs dirname)}"
echo "$PLUGIN"
```

Claude Code exposes the plugin root via `$CLAUDE_PLUGIN_ROOT`; the `find` fallback covers environments where the variable isn't set (SKILL.md lives at `skills/synthesize-graders/SKILL.md` under the plugin root, hence the two extra `dirname` calls). Cache the result as `$PLUGIN` and use `$PLUGIN/validate.py`, `$PLUGIN/viewer.py`, `$PLUGIN/authors/default/AUTHOR.md` thereafter. **Never hardcode `.claude/skills/synthesize-graders/`** — that path is not stable across Claude Code plugin layouts.

## Two grader scopes

The pipeline produces graders in two distinct scopes that must remain cleanly separated throughout the output:

- **`scope: single_call`** — grades one LLM call's output. The bulk of what you produce. Mechanical (Layer A) and user-centric (Layer B) failures both live here.
- **`scope: chain`** — grades a relationship across **N call-site outputs in the same logical session**. These are produced by step 4.5 (chain analysis) and require a runner that can fetch multiple outputs from one trace. They are a **separate category** in `pipeline.yaml` and `report.md` — surfaced under their own headings, not mixed into per-call-site sections.

Don't pretend a chain failure is a per-site failure or vice versa. Taxonomy clustering (step 5) places both, but the report keeps them visually separate.

## Inputs

The user will invoke this skill with one or more of:

- **Repo path** (required) — local directory to analyze. If they don't give one, assume the current working directory and confirm.
- **Traces file** (optional) — JSONL of OpenTelemetry GenAI spans (see `examples/sample_traces.jsonl` for a reference shape). If given, use these to discover call sites; the repo path is then secondary (used for enrichment when you need surrounding code).
- **Product hint** (optional) — 1-2 sentences describing what the product does. Sharpens intent extraction; ask if not given but keep going if the user declines.
- **Pack selection** (optional) — `--pack <id>` (repeatable) forces a pack engaged; `--no-pack <id>` forces a pack off. Without flags, step 0.5 runs pack auto-discovery from `applies_when` signals. `quality` is always-on regardless. See `packs/<id>/pack.yaml` for available packs.

## Re-run safety

If `evals/` already exists in the target repo, load `evals/.synth-lock.yaml` (if present) before doing anything else, then triage:

1. **Load locks.** Read each existing grader file and collect `_meta.locked_fields` and `_meta.human_edited`. Verify each file's current SHA-256 against the lock; record any divergence.
2. **Decide the safe path.**
   - If no grader is `human_edited` and no file diverges from the lock → re-run is safe; proceed to overwrite. Locked fields are still preserved (orchestrator carries them forward by passing them as `existing_grader.locked_fields` to the author).
   - If any grader is `human_edited: true` OR has lock divergence without `locked_fields` populated → **ask the user** which mode to use. Options:

     1. **Respect locks (default, recommended)** — re-synthesize all graders, but carry forward fields listed in each file's `_meta.locked_fields` verbatim, and skip files marked `human_edited: true` entirely (they pass through untouched).
     2. **Diff** — write to `evals.new/` instead. There is no CLI flag for this; treat `evals.new/` as the output directory throughout the run (every `Write` and every `python3 "$PLUGIN/viewer.py" <dir>` invocation) so the user can `diff -r evals evals.new` afterward.
     3. **Force overwrite** — invoked as `--force`. Ignore locks and `human_edited`. Destructive; warn explicitly that hand-edits will be lost.
     4. **Cancel**.

Stable IDs (see "Stable IDs" below) mean filenames collide between runs by design — that's a feature for diffing, a hazard for hand-edits. `_meta.locked_fields` + the lock file together make survival the default rather than the exception.

### Targeted regeneration (--only)

For fixing a single grader after curator review, invoke with `--only <grader_id|call_site_id|chain_id>`:

- **`<grader_id>`** — re-synthesize exactly that grader. Read `pipeline.yaml` for context; do not re-run steps 0–5; do not re-emit any other file. Spawn one subagent for the grader's call site or chain, with the failure-mode list filtered to the single matching id. The lock file is updated only for the regenerated file. (Step 4.6 dedup is a no-op for `--only <grader_id>` since the input is already a single failure mode.)
- **`<call_site_id>`** — re-synthesize all graders for that call site. Same as above but the subagent's failure-mode list contains all failures for the site.
- **`<chain_id>`** — re-synthesize all chain graders for that chain.

`--only` always respects `_meta.locked_fields`. Combine with `--force` to also overwrite locks (rare; only when the locked content is itself wrong). Print:

```
Step 6 (targeted): regenerated <grader_id> — <ok | failed_validation> — confidence <enum>
```

…and skip steps 7's full bundle write — only update the affected files and the lock entries for them. Cross-check the regenerated file via `validate.py <file> --pipeline evals/pipeline.yaml` before exiting.

## Pipeline

Execute the steps **in order**. Steps 0-5 are sequential — they build a shared understanding (including the taxonomy) that step 6 fans out against. Step 6 parallelizes per call site (and per chain) via subagents; each subagent both authors graders *and* calibrates their self-tests. Steps 7-8 re-sequentialize for the global write.

### Step 0 — Product context analysis

Apply `prompts/analyze_product.md`. Produce three artifacts that feed every downstream step:

- **`product_profile`** — domain, user types, business model, regulatory context, brand voice, data sensitivity. Cite a file path for every signal. Leave fields null when the repo is silent — never guess.
- **`implicit_invariants`** — rules the developer almost certainly believes but never wrote into every prompt (e.g. `no_legal_advice_without_disclaimer`, `pii_redacted_before_external_send`). Each carries `confidence: high | medium | low` and a list of evidence file paths. **No invariant without evidence.**
- **`invariant_coverage`** — for each invariant, the call sites that *appear* to enforce it vs the ones that *don't*. The "don't" list seeds Layer B failure-mode hypothesis with high signal.

This step drives Layer B failure-mode hypothesis downstream. Spend reasoning effort here — product-aware failure modes (the ones that catch implicit assumptions about user, domain, and regulatory context) depend on it.

If the repo gives you almost no signal (tiny scaffold, generic boilerplate), say so explicitly and produce a thin profile with `implicit_invariants: []`. Don't fabricate to seem thorough — a thin profile is a valid result that still helps downstream steps.

### Step 0.5 — Pack discovery + pre-filled interview

Packs are high-level concern bundles (`security`, `quality`, `reliability`, `brand`) that contribute failure modes at step 4. Each pack lives at `$PLUGIN/packs/<pack_id>/` with a manifest (`pack.yaml`), an interview prompt (`interview.md`), and a failure-synthesis prompt (`failures.md`). User-supplied packs are also discovered at `$REPO/.evals-packs/<pack_id>/` and override bundled packs with the same `id`.

#### Discovery

```bash
# Bundled packs:
for f in "$PLUGIN/packs"/*/pack.yaml; do ... ; done
# User packs:
for f in "$REPO/.evals-packs"/*/pack.yaml 2>/dev/null; do ... ; done
```

For each manifest, evaluate `applies_when.always` and `applies_when.auto_signals` against the step-0 artifacts (`product_profile`, `implicit_invariants`, `invariant_coverage`) and the call sites discovered at step 1 (defer the call-site-dependent checks until step 1 has run, then revisit).

Categorize each pack:

- **always-on** (`applies_when.always: true`) — `quality` defaults here; runs unconditionally.
- **auto-recommended** — at least one `auto_signal` matches the step-0 artifacts. Surface as "recommended on" but allow opt-out.
- **opt-in** — no signal matches. Surface as "available" only when the user explicitly invokes `--pack <id>`.
- **explicit override** — `--pack <id>` from the CLI forces enablement regardless of signal; `--no-pack <id>` forces disablement.

Print one line per pack:

```
Step 0.5: pack discovery
  - quality       (always-on) — engaged
  - security      (auto: regulatory_context includes [HIPAA], data_sensitivity includes [PHI]) — engaged
  - reliability   (auto: traces ingested with observed.p95_latency_ms) — engaged
  - brand         (auto: brand_voice_signals non-empty) — engaged
```

#### Interview with pre-fill from step 0

For each engaged pack, read its `interview.md`. The interview file declares per-question **pre-fill rules** that point at step-0 artifacts. Follow this protocol for every question:

1. **Apply pre-fill rules.** Inspect the cited step-0 fields (`product_profile.regulatory_context`, `implicit_invariants[].name`, etc.).
   - If the rules resolve to a confident answer → **set the answer and do not ask the user**. Record with `source: product_profile | invariants | code | observed | dependency` and `evidence: <file path>`.
   - If the rules resolve to a partial / lower-confidence answer → confirm with the user in one sentence: *"I see X from `<file>` — does that cover everything you need here?"* Record with `source: product_profile_confirmed`.
   - If no signal exists → ask the open question. Record with `source: user`.

2. **Print a transparency line** per question:
   ```
   [security/Q1.regulations] auto-filled from product_profile.regulatory_context: [HIPAA, GDPR]
   [security/Q3.threat_model] asking: ...
   [brand/Q4.persona] auto-filled from src/agent/prompt.py: 'Penny'
   ```

   The user sees what was inferred vs asked and can interrupt to correct.

3. **Batch the asks.** Ask all genuinely-needed user questions across all engaged packs in a single dialogue turn (one combined list with pack-prefixed labels). Don't ping-pong per pack.

Record results into `pipeline.packs[<id>].interview_answers` per the schema in `output_format.md`. Compute `content_digest` for each engaged pack:

```
sha256(pack.yaml + interview.md + failures.md), first 16 hex chars
```

This lets re-runs notice when a pack itself has changed (separately from the call-site / product changes).

#### Manifest hygiene

- Verify pack manifests pass `$PLUGIN/contract/pack.schema.json` (load + check; bail if any pack is malformed).
- Check `dependencies` are satisfied (every dep is also engaged); print a warning and prompt the user if not.
- Check `conflicts` are not co-engaged; fail loudly if so.

Output of this step is the populated `pipeline.packs[]` block (held in memory; written to disk at step 7). Pass it forward to step 4 so the per-pack `failures.md` prompts can consume `interview_answers`.

### Step 1 — Discover call sites

Two paths depending on inputs:

**Path A — traces provided:** Read the JSONL of OpenTelemetry spans. Use the [OTel GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — do **not** rely on vendor-specific attributes (Langfuse, LangSmith, etc.). The JSONL may be OTLP/JSON (one `ResourceSpans` per line, with `attributes` as `[{key, value: {stringValue|...}}]`) or the flatter Python SDK exporter shape (one span per line, `attributes` as a dict). Handle both — normalize each span to a `{name, trace_id, span_id, parent_id, start_time, end_time, status, attributes: dict, events: list, resource: dict}` view before extracting fields. The reference shape lives in `examples/sample_traces.jsonl`.

#### Span taxonomy to extract

GenAI spans come in several flavors. Treat them differently:

| Span kind | Detection signal | What synthesize-graders does |
|---|---|---|
| **chat / completion / generate_content** | `gen_ai.operation.name ∈ {chat, text_completion, generate_content}` and `gen_ai.system` set | Primary call-site source. Group by normalized-system-prompt hash. Shape classified at step 2. |
| **tool / function execution** | `gen_ai.operation.name == "execute_tool"` or attribute `gen_ai.tool.name` set | Emit as its own call site with `shape: tool_call` (skip classify_shape step 2 LLM-call for these). Group by tool name + normalized argument schema. |
| **embedding** | `gen_ai.operation.name == "embeddings"` | Emit as `shape: embedding`. Skip Layer A/B failure-mode hypothesis (no textual output); record only observability stats. |
| **streaming** | `gen_ai.input.messages` present, `gen_ai.output.messages` empty, and one or more `gen_ai.choice` events | Reconstruct output by concatenating `gen_ai.choice` event deltas in event-timestamp order. |
| **errored** | `status.status_code == "ERROR"`, or `gen_ai.response.finish_reasons` containing `content_filter | refusal | length | safety` | Still groups into its call site, but contributes to `observed.error_rate` / `observed.refusal_rate`. **High signal** for Layer B refusal + Layer C content-filter failure modes — pass the error reason into the failure-mode prompt as an "observed-in-prod" hint. |
| **retry duplicates** | Two spans within the same `trace_id` with identical normalized prompts and overlapping `[start_time, end_time]` windows, or sequential within < 100ms gap | Collapse to one logical sample. Do **not** double-count toward `sample_count` or `cost_estimate_usd`. |
| **non-GenAI** | No `gen_ai.*` attributes | Ignore. |

For each retained span, extract:

- **Provider / model** — `gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.model`.
- **Operation** — `gen_ai.operation.name` (becomes a hint for shape classification in step 2).
- **Messages in** — prefer `gen_ai.input.messages` (JSON-encoded array of `{role, parts}` per the current semconv). If absent, reconstruct from span events named `gen_ai.system.message` / `gen_ai.user.message` / `gen_ai.assistant.message` / `gen_ai.tool.message` — each event's `content` (or event body) carries the message text. The **system prompt** is the content of the `system` role message; this is the load-bearing field for call-site identity.
- **Messages out** — `gen_ai.output.messages` if present, otherwise span events named `gen_ai.choice` (one per generated choice). For streaming spans, concatenate.
- **Trace linkage** — `trace_id`, `span_id`, `parent_id` (top-level OTel fields, not under `attributes`). Used by step 4.5 to build the trace tree.
- **Status + finish reasons** — `status.status_code`, `gen_ai.response.finish_reasons`. Feed into `observed.error_rate` / `observed.refusal_rate`.
- **Token / cost stats** — `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`. Combine with a model price table to estimate `cost_estimate_usd` (omit when price unknown).
- **Latency** — `end_time − start_time`, in ms.

#### Grouping into call sites

Group spans by the **normalized system-prompt hash** (see "Stable IDs"). If no system message is present on a span, fall back to hashing the first 512 chars of the first user message — note this fallback in `report.md`. The span `name` (e.g. `chat anthropic`, `summarize_thread`) is a useful display hint (becomes `use_case`) but is **not** load-bearing for identity, because instrumentation libraries name spans inconsistently.

#### Sampling, time windowing, and observability stats

Within each call-site group:

1. **Sort spans by `start_time` ascending.**
2. **Compute `observed.*` over the full group** (not just the representative sample): `first_seen`, `last_seen`, `error_rate`, `refusal_rate`, `p50_latency_ms`, `p95_latency_ms`, `p50_tokens_in`, `p95_tokens_in`, `p95_tokens_out`, `cost_estimate_usd` (sum across the group when price is known).
3. **Pick representative samples for `source_spans` + dataset capture**: stratify by time so dataset rows aren't all from one hour. Bucket the time range into 5 equal buckets; sample up to 2 spans per bucket; cap the total at 10 spans per call site. Smaller groups: take all.
4. **Surface skew**: if one call site holds > 70% of all retained spans, print a warning (`call site <id> dominates the sample (N/M); other sites have thinner coverage`) so the user can decide whether to ask for broader traces or just proceed.
5. **Time-window guard**: if the JSONL spans more than 90 days, ask the user whether to filter to the last 30 days — stale invariants are a real risk. Default to filtering to the last 30 days when the user doesn't answer in the prompt.

These stats land in `call_sites[].observed` in `pipeline.yaml` (schema in `output_format.md`). They drive prioritization in `report.md`, cost/latency budgets in Layer C failure-mode hypothesis, and the audit gate in step 4.7.

#### Redaction state

Production traces commonly contain redaction placeholders. Detect them before hashing for identity:

- Placeholder tokens: `<REDACTED>`, `[REDACTED]`, `[PII]`, `***`, runs of 40+ identical hex chars, `***@***.***`-style email masks.
- A span whose system + first user message is **composed entirely** of placeholder tokens has `redaction_state: redacted`. **Do not** hash placeholder content for call-site identity — instead, group all redacted spans under one explicit synthetic call site `sha::redacted` and surface a warning asking the user for an unredacted replay sample.
- A span whose payloads are partially redacted is `redaction_state: partial` — still hash on the visible portion but mark the call site so downstream Layer C "PII leakage" failures know to treat the placeholder pattern as the canonical leak shape.
- A span with full content is `redaction_state: none`.

The overall `runtime.redaction_state` in `pipeline.yaml` is the worst case across all call sites: `redacted` if any site is, else `partial` if any site is, else `none`.

#### Captured-input datasets

For each call site (Path A), write `evals/datasets/<call_site_id>.jsonl` containing one row per representative sample (the 10 stratified spans selected above). Schema per row is documented in `output_format.md`. Filter out spans with `redaction_state: redacted` from the dataset — the runner can't usefully replay them. Reference the file path from `call_sites[].dataset_path` and attach a `dataset_refs` entry on every grader (step 6).

If the user has set the semconv opt-in for content capture (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`) and message content is genuinely absent (not redacted, just not captured), say so in the run log — don't fabricate payloads, and skip dataset capture for that call site (leave `dataset_path: null`).

**Path B — no traces, static repo:** Use `Grep` to find LLM-call patterns (`messages.create`, `chat.completions.create`, `litellm.completion`, plus generic `model=` + `messages=` calls). For each match, capture the file/line, the resolved model and system prompt (read constants in the same module), and ~30 lines of surrounding code.

Output: a numbered list of call sites with their identity, provider, model, system prompt, and any surrounding context. Show this to the user before proceeding so they can sanity-check before you spend reasoning effort downstream.

**Soft cap at ~50 call sites.** Below 30, proceed without asking. Between 30 and 50, print the list and confirm the user wants to continue (the report will get long but stays readable). Above 50, stop and ask the user to narrow scope (a specific subdirectory, a specific use_case, etc.) — at that scale a single session can't produce a curatable artifact and you'd be doing them a disservice by trying.

### Step 2 — Classify shape

Apply the rubric in `prompts/classify_shape.md` to each call site. Choose exactly one of: `summarize | extract | rag_answer | classify | draft | route | tool_call | agent_step | conversational_turn | other`. Record a confidence (`high` / `medium` / `low`).

### Step 3 — Extract intent + constraints

Apply `prompts/extract_intent.md` per call site. **Bring the product profile from step 0 with you** — the user description in your intent should reflect both the call-site-local signals (system prompt, surrounding code) *and* the product-level context (who the product is for, what regulatory regime applies, what brand voice is established).

Produce:
- `intent`: three sentences as specified in `extract_intent.md` — what this produces, who the user is + their constraint, what makes a good answer in user-impact terms. The user description must be informed by step 0's `user_types`.
- `constraints`: list of `{kind, description, enforcement}` where `kind` ∈ `schema | length | format | refusal | citation | other`, `enforcement` ∈ `deterministic | judge`. Prefer `deterministic` when a parser/regex/schema-check can verify the rule.

### Step 4 — Hypothesize per-call-site failure modes

Apply `prompts/hypothesize_failures.md` per call site. **All failure modes from this step have `scope: single_call`.**

Produce **11-26 failure modes per site, in three layers**:

- **Layer A (3-8 mechanical / structural)** — schema validity, format adherence, length bounds, citation structure, refusal-condition breaches, output-structure invariants. Each becomes a `kind: deterministic` grader downstream.
- **Layer B (5-12 user-centric / judgmental)** — faithfulness, helpfulness, calibration, tone, edge-case drift, cross-turn coherence. Each becomes a `kind: llm_judge` grader downstream.
- **Layer C (3-6 adversarial / operational)** — prompt injection, jailbreak, PII / secret leakage, tool-arg exfiltration, cost / latency regressions, non-determinism, audit-trail loss. Mix of deterministic (regex / token-count / latency timer) and judge graders. Anchor cost/latency budgets to the call site's `observed.p95_*` stats when present.

All three layers are required for every call site. **Lean on the `invariant_coverage.likely_gap_in` list from step 0** — those are call-site / invariant pairs where an invariant likely isn't enforced; convert each into a Layer B failure. **Lean on `product_profile.data_sensitivity` and `regulatory_context`** for Layer C: PII / PHI / financial signals seed Layer C "leakage" failures with high signal.

**Baseline failures carry `pack_ids: [quality]`** (the always-on baseline). Layer A schema/format/length checks default to `pack_ids: [quality]`; Layer C operational failures default to `pack_ids: [reliability]` *when the reliability pack is engaged*, else `[quality]`. Other tags are added by pack contributions below.

#### Pack contributions

After producing baseline failures, for each engaged pack other than `quality` (which is the baseline), read `$PLUGIN/packs/<pack_id>/failures.md` and produce that pack's contributions in the same YAML form, **gated by the pack's `interview_answers`**. Each contribution carries:

```yaml
pack_ids: [<pack_id>]
compliance_tags: [<subset of pack manifest's contributes_compliance_tags chosen by interview>]
```

Pack contributions are *additive* to baseline failures — overlaps are resolved at step 4.6 (dedup), not here. Do not pre-merge or drop in this step; let dedup do the canonical reconciliation.

Failure mode IDs must be stable: `<call_site_id>::<name>`. Pack identity is **not** part of the ID — it lives in `pack_ids`. Each failure mode carries `layer: A | B | C` so the audit, taxonomy, and report can split them cleanly.

### Step 4.5 — Chain analysis (cross-call failures)

Apply `prompts/analyze_chains.md`. **All failure modes from this step have `scope: chain`** and reference a `chain_id`.

Detect chains across the call sites discovered in step 1:

- **Trace-confirmed** (high confidence) when traces are provided and you can see outputs from one span feeding the inputs of another in the same `trace_id`.
- **State-mediated** (medium confidence, static) when A's output type or state-field name appears in B's input via grep.
- **Sequential composition** (low confidence, static) when A and B are called in the same function in obvious order.

For each detected chain, hypothesize 3-8 cross-call failure modes from the categories in `analyze_chains.md` (context drop, context contradiction, confidence not propagated, conditional gate misfire, information redundancy, stateful drift, tool/argument coherence, cumulative bias / drift). These are *additional* to the per-site failures from step 4 — they're not duplicates, they're a separate category that no per-site grader can catch.

Chain failure mode IDs: `<chain_id>::<failure_name>`. Emit them into the same flat `failure_modes:` list as single-call failures — `scope` and `chain_id`/`call_site_id` distinguish them. (The chain-analysis prompt may show them under a `chain_failure_modes:` heading for clarity; flatten into the unified list before step 5.)

If the system has clearly independent call sites, produce zero chains. An empty `chains: []` is a valid result.

### Step 4.6 — Dedup & merge across packs (deterministic)

The union of step-4 baseline failures + each engaged pack's contributions + step-4.5 chain failures is the input to this step. Run a single deterministic pass and produce one canonical `failure_modes:` list.

**Sort inputs canonically first** so re-runs are stable regardless of pack-load order:
1. By `scope` (`single_call` before `chain`).
2. By `call_site_id` or `chain_id` ascending.
3. By `name` ascending.

Then run three passes in order. Print one line per pass with counts.

#### Pass 1 — Exact merge

Failures sharing `(scope, call_site_id|chain_id, name)` collapse into one. The surviving entry's fields are reconciled:

- `pack_ids` = union of contributors'.
- `compliance_tags` = union.
- `severity` = max (high > medium > low). The strictest contributor wins — a HIPAA pack contribution doesn't degrade because a quality pack rated the same failure `medium`.
- `layer` = most specific (C > B > A; chain failures stay `null`). When two contributors disagree (rare), the more-specific layer wins.
- `description` = the longest non-empty contributor's description; tiebreak by lexicographically smallest.
- `id`, `taxonomy_node_id`, `grader_id` are unchanged (the id is `<call_site_id>::<name>` regardless of contributors).

#### Pass 2 — Semantic merge

For each remaining pair within the same `(scope, call_site_id|chain_id, layer)` group:

- If the two names differ only by trivial morphology (e.g. `pii_leakage` ↔ `pii_leakage_in_summary`) → merge under the lexicographically smaller name, applying pass-1 reconciliation to the union.
- If the descriptions are near-duplicates (semantic equivalence, judged inline by you), same merge rule.

Be conservative — when in doubt, leave the pair separate. False merges destroy coverage; failures-to-merge produce redundant graders, which step 6 calibration will surface as low-variance duplicates and step 4.7 audit will flag.

#### Pass 3 — Conflict suffix (rare)

If two surviving failures still share `(scope, call_site_id|chain_id, name)` but have materially different descriptions/severities (impossible after pass 1 — this only happens if pass-2 semantic merge created a name collision):

- Disambiguate by appending the pack id of the **second** (lexicographically larger pack_id) failure: `<name>__<pack_id>`. This is the only path by which pack identity enters a failure name; print a `WARN` line:

  ```
  WARN: name conflict at <call_site>::<name> across packs [<a>, <b>] — renamed second to <name>__<b>; pack authors should namespace
  ```

#### Output of step 4.6

Print:

```
Step 4.6: dedup — N raw failures → M canonical (K exact-merged, J semantic-merged, R conflict-suffixed); packs contributing: [quality, security, ...]
```

The canonical `failure_modes:` list is what step 5 (taxonomy) and step 4.7 (audit) read. No other step in the pipeline ever sees the raw pre-dedup union.

#### Determinism guarantee

Given the same step-0 / step-1 / step-4 / step-4.5 inputs and the same engaged packs at the same content_digests, this step must produce byte-identical output across re-runs. The canonical sort + lexicographic tiebreakers above are the load-bearing pieces.

### Step 4.7 — Audit the failure modes (do not skip)

Read the **post-dedup** canonical `failure_modes:` list from step 4.6 and answer these questions out loud:

1. **Does every call site have at least 3 mechanical (Layer A) single-call failures?** If not, you under-covered the cheap deterministic graders. Add them.
2. **Does every call site have at least 5 judgmental (Layer B) single-call failures?** If not, you stopped at the easy stuff and missed the high-impact cases users notice in production. Re-read the call site's intent — especially who the user is — and add 2-4 more judgmental failures.
3. **Does every call site have at least 3 adversarial / operational (Layer C) single-call failures, covering at least one of {prompt_injection, pii_leakage} when user data flows in?** If not, re-read the Layer C section in `hypothesize_failures.md` and the product profile's `data_sensitivity` and `regulatory_context`. Embedding-only sites are exempt (Layer C limited to cost/latency).
4. **Are at least half of your high-severity single-call failures from Layer B + Layer C combined?** Mechanical bugs are usually `medium`. Refusal-condition breaches are Layer A but legitimately high-severity in regulated domains — count them on the Layer A side of the ratio without penalty.
5. **Is the same generic failure showing up across every call site?** ("Hallucinates", "wrong format", "incorrect output", "vulnerable to injection".) Replace those with call-site-specific versions or merge them.
6. **For every chain detected in 4.5, do you have at least 3 cross-call failures, with at least one of them not being trivially convertible to a per-site failure?** ("B hallucinates" is a per-site failure on B; "B drops the context A surfaced" is a real chain failure.) If not, re-read `analyze_chains.md`. For ensembles, ensure you have an "ensemble disagreement masked" failure.
7. **Did you propose any chain whose detection method is `sequential_composition` (low confidence)?** If so, ensure the chain's `rationale` explicitly cites the file/line. Low-confidence chains without grounding should be dropped.
8. **Did you cover the `invariant_coverage.likely_gap_in` pairs from step 0?** Each one should have at least one Layer B or Layer C failure mode. If not, add them.
9. **Did every engaged pack contribute at least one failure?** A pack that's engaged but contributes zero failures usually means the interview returned all-empty answers — verify that's correct, and if so, disengage the pack (remove from `pipeline.packs[]`) rather than leaving a dead pack record. Exception: `quality` always stays.
10. **Did dedup produce any conflict-suffixed names?** If yes, the conflicting pack authors should rename to namespace within their own pack. Flag for the pack maintainer; the run continues.
11. **Do all `failure_modes[].pack_ids` entries resolve to a `pipeline.packs[].id`?** A non-resolvable pack_id is a step-4.6 bug.

Fix any issue before continuing. State what you changed in one line. `validate.py --bundle evals/` re-runs this audit deterministically at step 7 — soft prompt-time checks are not the only gate.

### Step 5 — Cluster failure modes into a 2-level taxonomy

**Taxonomy clustering runs before grader synthesis.** Each failure mode's `taxonomy_node_id` is computed here so step-6 subagents can splice it into the grader file at write time — there is no second pass over already-written grader bodies.

Group all failure modes — single-call **and** chain — by the *kind of brokenness* they represent. Top-level node names are snake_case, plural where appropriate, scannable.

**Aim for 6-15 top-level nodes**, with subcategorization wherever a top-level has clearly distinct sub-kinds. Subcategories are encouraged — they're how a large grader set stays navigable.

Cover all four flavors in the taxonomy:

- **Layer A flavor** (single-call mechanical): `format_violations`, `schema_violations`, `length_overruns`, `refusal_violations`, `citation_structure_errors`
- **Layer B flavor** (single-call judgmental): `faithfulness_failures` / `summary_unfaithfulness` / `rag_citation_grounding`, `helpfulness_failures` / `audience_mismatch`, `calibration_errors` / `over_refusal` / `false_specificity`, `tone_brand_violations`, `edge_case_drift`, `cross_turn_coherence`
- **Layer C flavor** (single-call adversarial / operational): `prompt_injection_resistance`, `jailbreak_resistance`, `pii_leakage`, `secret_leakage`, `tool_arg_exfiltration`, `cost_regressions`, `latency_regressions`, `output_variance`, `audit_trail_loss`. Keep these as their own top-level cluster — runtime gating policy and ownership tend to differ from quality failures.
- **Chain flavor** (cross-call): `cross_call_context_drop`, `cross_call_contradiction`, `cross_call_confidence_drift`, `conditional_gate_misfires`, `cross_call_redundancy`, `stateful_drift`, `tool_argument_incoherence`, `ensemble_disagreement_masked`. Chain failures should *cluster together* rather than getting absorbed into single-call categories — they're a separate concern with different runtime requirements.

Don't force every category to exist — only emit a node when ≥ 1 failure mode lands in it. Reach for the Layer B nodes — judgmental failures are the ones a runtime judge can catch and a linter can't.

Every failure mode must end up under exactly one leaf. Anything you can't place goes under `tax::uncategorized`.

Node IDs: `tax::<slug>` for top-level, `tax::<parent-slug>::<sub-slug>` for subcategories.

**Update the in-memory failure-mode list** in place: set `failure_modes[i].taxonomy_node_id` on every entry. Step 6 subagents read this list and propagate the field onto each grader.

### Step 6 — Synthesize graders + calibrate self-tests (parallel fan-out)

**This step delegates to a grader author** — defined by the contract in `contract/AUTHORING_CONTRACT.md` (v2) and validated by `contract/grader.schema.json` — that owns judge-prompt, rubric, `applies_when`, `applies_when_check`, and self-test authoring (including the new `self_tests[].category` and the required adversarial entry). Do not author those fields inline. Step 6's job is to (a) discover which author to use, (b) drive the fan-out, (c) gate emitted files through `validate.py`, (d) calibrate self-tests *inside the same subagent* so the parent never reads grader bodies, (e) splice orchestrator-owned operational fields (`owner`, `block_on_fail`, `cost/latency budgets`, `dataset_refs`) onto each emitted file, and (f) write the `_meta` provenance block.

#### Author discovery (first action of step 6)

There are two distinct author-invocation models. The discovery logic must branch on them:

1. **`evals-prompt`** — the proprietary skill-based author. Check whether a skill named `evals-prompt` is available in this session. If so, prefer it. (The contract asks skill-based authors to declare `contract_version: 2`; this is currently a documentation contract, not a runtime check — the orchestrator only verifies the skill name. v1 authors remain compatible if they ignore the v2-only fields, per `contract/AUTHORING_CONTRACT.md` § "What changed in v2".) Subagents invoke it via the **Skill** tool.
2. **`authors/default`** — the bundled OSS fallback. Lives at `$PLUGIN/authors/default/AUTHOR.md`. This is **not a skill** — it is a markdown procedure. Subagents read this file and follow its steps inline (no Skill-tool call). This author is always available because it ships with this plugin; if it is missing, the plugin install is broken.

Print one line so the user knows what's running: `Step 6: using grader author <name>` (e.g. `using grader author evals-prompt` or `using grader author default (bundled)`). Note this in `report.md` too (section: Author).

In the rest of this section, `<AUTHOR>` refers to whichever author was selected. The subagent prompt template branches on author type — see below.

#### Fan-out strategy

Spawn **one subagent per call site** (and one per chain) via the Agent tool with `subagent_type: general-purpose`. Send them all in a single message so they run concurrently. **Cap the fan-out at 30 subagents per message** — if you have more call sites + chains than that, send batches of 30 sequentially (parent waits for each batch before launching the next).

Each subagent is self-contained — it has no memory of this conversation. Pass it the prompt template below verbatim, with the angle-bracket placeholders filled in. The template is the load-bearing artifact for this step; don't paraphrase its instructions in surrounding prose.

```
You are synthesizing and calibrating graders for one call site (or chain) as part of a synthesize-graders run.

CONTEXT
- Plugin root: <absolute path; see $PLUGIN from step 0>
- Repo: <target repo abs path>
- Call site (or chain) summary: <one paragraph from step 3 intent + step 2 shape>
- Product profile: <domain, user types, regulatory, brand voice — terse>
- Observed stats for this call site (if any): <yaml from call_sites[].observed: p95 latency / tokens / error_rate / cost>
- Failure modes to grade: <yaml list of {id, name, description, severity, layer, scope, taxonomy_node_id}>
- Existing grader files for this call site, if any (re-run): <list of paths and their _meta.locked_fields>
- Grader author: <AUTHOR>
- Author invocation: <skill | bundled-markdown>
    skill            → invoke `<AUTHOR>` via the Skill tool. Input schema:
                       $PLUGIN/contract/AUTHORING_CONTRACT.md § "Input the orchestrator passes to the author"
    bundled-markdown → Read $PLUGIN/authors/default/AUTHOR.md once and follow it for each failure mode.
                       (Do not invoke via the Skill tool — there is no skill of that name.)

FOR EACH FAILURE MODE
1. If a grader file already exists on disk for this failure mode, load it and read `_meta.locked_fields`.
   Pass the existing body + lock list to the author as `existing_grader` input. The author returns YAML
   that preserves locked fields verbatim and refreshes the rest.
2. Author body via the selected author. The author-owned output shape is documented in the contract
   (v2 — `self_tests[].category` and `applies_when_check` are now author-owned).
3. Splice the orchestrator-owned fields onto the returned body:
     id, scope, failure_mode_id, call_site_id | chain_id, name, taxonomy_node_id   — routing
     owner                                                                          — null or carried from existing file
     block_on_fail                                                                   — null (inherit severity_policy)
     cost_budget_tokens     ≈ observed.p95_tokens_in + observed.p95_tokens_out, when known; else null
     latency_budget_ms_p95  ≈ observed.p95_latency_ms × 2, when known; else null
     dataset_refs           — one entry per call_sites[].source_spans[] for this call site, plus the
                              `jsonl_path: datasets/<call_site_id>.jsonl` if dataset_path is set
     _meta:
       author: <AUTHOR>
       author_contract_version: 2
       synthesized_at: <ISO-8601 now>
       synth_inputs_digest: <sha256 over canonical author input; first 16+ hex chars>
       locked_fields: <carried from existing file, else []>
       human_edited: <carried from existing file, else false>
   Write to evals/graders/<grader_id_safe>.yaml — `::` replaced with `__` in the filename only;
   the id inside the file keeps `::`.
4. Validate:
     python3 "$PLUGIN/validate.py" evals/graders/<file>.yaml
   On failure, retry the author with a `validator_feedback` block (max 3 attempts). After 3 failures,
   write the last attempt with a top-level `_validation_error: <message>` key (see contract § "Retry semantics")
   and move on.
5. Calibrate self-tests in place (skip if `_validation_error` was written):
   - Apply the grader's rubric to each self-test as if you were the runtime LLM judge. First pass.
   - Apply it a second time with self-tests presented in reversed order (or — for chain graders —
     with the call_site_outputs mapping iterated in reversed key order). This is a cheap probe for
     position bias.
   - For self-tests with `category: adversarial`: confirm `expected_verdict: fail` and the rubric
     actually catches the injection — if the rubric passes the adversarial output, mark
     confidence: low and add a `validator_feedback`-style retry hint to your manifest.
   - Compute pass_rate = matches / total (first pass).
   - Compute variance = (count of verdicts that flipped between passes) / total.
   - Set confidence:
       pass_rate >= 0.8 AND variance <= 0.1   → high
       pass_rate >= 0.5 AND variance <= 0.2   → medium
       otherwise                              → low
   - Patch self_test_pass_rate, self_test_variance, and confidence on disk via Read+Edit. Touch no
     other field.

RETURN ONLY this yaml manifest (no prose):
  call_site_id: <id>
  emitted: [<grader_id>, ...]
  failed_validation: [<grader_id>, ...]
  carried_locked: [<grader_id>, ...]     # files where locked_fields were carried forward
  calibration: { <grader_id>: { pass_rate: <float|null>, variance: <float|null>, confidence: <enum>, adversarial_uncaught: <bool> }, ... }
```

The parent (this skill) sees only the returned manifests — never emitted YAML bodies — which keeps the parent context window free for the global write at step 7. The contract is authoritative on the author I/O shape, on the author-owned vs orchestrator-owned field split, and on `_validation_error` semantics; do not duplicate those rules here.

### Step 7 — Write pipeline.yaml and report.md

Output goes to `evals/` in the target repo's working directory.

**`evals/pipeline.yaml`** — everything *except* the per-grader bodies. Use the schema in `output_format.md`. Top-level keys, in order: `version` (currently `"0.3.0"`), `product_hint`, `packs` (from step 0.5), `product_profile`, `implicit_invariants`, `invariant_coverage`, `runtime`, `call_sites` (with `observed.*` from Path A), `chains`, `failure_modes` (post-dedup from step 4.6, with `taxonomy_node_id` populated from step 5, `pack_ids` + `compliance_tags` from step 4), `taxonomy`. Graders are referenced by ID only via `failure_modes[].grader_id` so consumers can join. Use `yaml.safe_dump(..., sort_keys=False)` semantics — preserve insertion order.

**`evals/graders/<grader_id_safe>.yaml`** — one file per grader, already written and calibrated by the step-6 subagents. At step 7, verify every failure mode has a corresponding file (and vice versa — no orphan grader files). Do **not** re-emit or mutate these files. Run the bundle validator (single command, replaces the per-file loop):

```
python3 "$PLUGIN/validate.py" --bundle evals/
```

The bundle validator runs every per-file check, plus global checks: FM↔grader bijection, chain DAG acyclicity, duplicate IDs across files, orphan / unreachable taxonomy nodes, the layer-A/B/C coverage gates from step 4.7, pack-id resolution, dedup uniqueness (step 4.6 invariant), and pack dependency / conflict consistency. Exit code is non-zero on any failure; treat that as a hard stop and surface the errors in `report.md`.

**`evals/.synth-lock.yaml`** — write last (after every grader is finalized). Compute SHA-256 over each grader file's content; record the digest under `graders.<grader_id_safe>`. On re-run, this lock is loaded *before* step 6 so subagents can detect hand-edits (file hash diverged from lock without `_meta.locked_fields` populated) and warn before overwriting. Format documented in `output_format.md`.

**`evals/report.md`** — Format per `output_format.md`. Sections, in order:

1. Header + summary (totals; explicitly broken down by scope: "X single-call graders, Y chain graders"; note which grader-author skill was used and which packs were engaged).
2. **Engaged Packs** — one row per pack with `tier_hint`, `enabled_by`, and a count of contributed failures. Surface the resolved interview Q&A so the user can see what was inferred vs asked.
3. **Product Profile** — domain, users, regulatory context, brand signals.
4. **Implicit Invariants** — table with confidence and evidence.
5. **Failure Taxonomy** — full tree, with each node showing how many single-call vs chain failures it contains.
6. **Chains** — separate top-level section listing each detected chain, the call sites in it, the chain failures, and the chain graders. **Chain content lives only here, not under per-call-site sections.**
7. **Call Sites** — per call site → its single-call failure modes → their graders. Pure single-call content. When `observed.*` stats are present, render them in a small table at the top of each call site.

After writing, print to stdout (one line):
```
evals/ written: <N> call sites | <C> chains | <M+X> failures | <K> graders (<F> failed validation, <L> low-confidence) | <T> taxonomy nodes | <P> packs
```

If `F > 0` (any grader has `_validation_error`), also print:
```
WARN: <F> grader(s) failed schema validation — inspect: evals/graders/<id>.yaml
```

### Step 8 — Build the HTML viewer

After the summary line, run the bundled viewer to produce a self-contained `evals/index.html` for visual browsing:

```
python3 "$PLUGIN/viewer.py" evals
```

The viewer accepts `--cta-url <url>` and `--cta-label <text>` to customize the header CTA button (defaults: `https://evals.tessary.ai` / `Continue on evals.tessary.ai`). Pass these through if the user has asked for a different destination.

Then tell the user how to open it, **matching their platform**. Detect the platform once via `uname -s`:

- macOS (`Darwin`): print `Browse the synthesized pipeline visually: open evals/index.html`
- Linux: print `Browse the synthesized pipeline visually: xdg-open evals/index.html`
- Windows / unknown: print `Browse the synthesized pipeline visually: start evals/index.html`

Then on the next line, print verbatim:
```
The viewer reads only the local files under `evals/` — nothing leaves your machine until you click through the CTA button.
```

The viewer reads `evals/pipeline.yaml`, every `evals/graders/*.yaml`, and `evals/report.md` if present, and emits one fully self-contained HTML file — no server, no network, no build step. If `viewer.py` fails (e.g., missing PyYAML), surface the error but do not block the run; the underlying YAML artifacts are still the source of truth.

The viewer UI is templated — `viewer.py` is a thin loader that composes three editable files in `viewer_template/`:

- `viewer_template/template.html` — page skeleton with mustache placeholders: `{{styles}}`, `{{script}}`, `{{data_json}}`, `{{config_json}}`, `{{cta_url}}`, `{{cta_label}}`. Substitution is single-pass (regex-based) so the order of placeholders, and any incidental occurrences of placeholder-shaped strings in user data, are safe.
- `viewer_template/styles.css` — all CSS
- `viewer_template/app.js` — client-side rendering (vanilla JS, no framework, no build)

To restyle or restructure the viewer, edit these files directly — no Python changes needed. The viewer deliberately ships as plain HTML/CSS/JS rather than a built artifact because the plugin's hard constraint is "runnable with just `python3` + PyYAML"; adding a Node toolchain just to view local YAML would defeat that.

## Stable IDs

Re-running the skill on the same repo + traces produces the same call-site / failure-mode / grader / taxonomy-node IDs. Conventions:

- **Call site ID**: in Path B (static repo), use a source-code label (function name or module symbol), snake_cased. In Path A (traces) there is no standard OTel attribute for "logical use case", so always derive the deterministic synthetic: `sha::<16-hex>` where the hex is the first 16 chars of SHA-256 over the **normalized representative system prompt** — strip leading/trailing whitespace, collapse internal whitespace runs to single spaces, lowercase. (If no system prompt exists on the span, hash the first 512 chars of the first user message instead, and note the fallback.) Document this normalization choice in `report.md` for any synthetic IDs.
- **Failure mode ID**: `<call_site_id>::<snake_case_failure_name>` (single_call), `<chain_id>::<snake_case_failure_name>` (chain).
- **Chain ID**: `chain::<short_snake_case_label>` derived from the call sites it connects (e.g. `chain::rag_then_draft`). Stable as long as the call-site IDs are stable and the chain composition doesn't change.
- **Grader ID**: `<failure_mode_id>::grader`.
- **Taxonomy node ID**: `tax::<slug>` or `tax::<parent>::<sub>`. Choose slug from the node's *category meaning*, not from the specific failures that happen to land in it — that keeps the slug stable across runs even if failure mixes shift.

Filenames substitute `::` → `__`. No other character substitution is performed; if a stable ID would contain `/` or other filesystem-unsafe characters, the skill should fail loudly rather than rewrite silently.

## Constraints

- **No network for synthesis.** The synthesis run makes no API calls and reads no remote URLs — purely local reasoning + files. (The viewer renders a CTA button whose `href` points off-host; that's a click destination, not synthesis I/O.) Don't ask the user to install runtime dependencies as part of this skill.
- **Use the Bash, Read, Grep, Glob tools** to explore the target repo. Use **Write** for `pipeline.yaml` and `report.md`. Per-grader files are written by step-6 subagents. Don't write anything else to the target repo (no caches, no logs). The user can `rm -r evals/` to start over.
- **Stable IDs** as specified above. Re-runs should produce diffable output.
- **No invented sources.** When you list a call site, every field must be grounded in either the traces or the source code. If you can't read the file, say so — don't fabricate surrounding code.
- **Show your work between steps.** After each step, print a one-line status (e.g. `Step 2 done: classified 4 call sites — 3 high, 1 medium confidence`) so the user can interrupt if a step looks off. Don't dump the full intermediate state every time; keep updates terse.
- **Scale gates.** ≤ 30 call sites → just go. 30-50 → confirm with the user. > 50 → ask them to narrow scope. The synthesis quality, not the runtime, is the ceiling — pushing past 50 in one session produces a report too long to review carefully.
- **Subagents ONLY at step 6.** Steps 0-5 and 7-8 run in this session for a coherent audit trail. Step 6 fans out per call site because grader synthesis + calibration is embarrassingly parallel across sites and dominates total token cost. Do not spawn subagents at any other step.

## Verification (what the user should expect)

A clean run on a small repo (3-4 call sites, 1 chain) with all four packs engaged should produce, in roughly this order:

```
Step 0: product profile (B2B sales productivity, sales reps as users); 4 implicit invariants identified
Step 0.5: pack discovery — quality (always-on), security (auto: regulatory_context [HIPAA]), reliability (auto: traces ingested), brand (auto: brand_voice_signals non-empty); 11/18 interview questions pre-filled from product analysis, 7 asked
Step 1: discovered 4 call sites: summarize, rag_answer, extract, draft
Step 2: classified — 4 high confidence
Step 3: extracted intent + constraints for all 4 (informed by step 0 user types)
Step 4: hypothesized 88 raw single-call failure modes across 4 packs (52 quality, 14 security, 12 reliability, 10 brand)
Step 4.5: detected 1 chain (rag-then-draft); 5 chain failure modes added (total 93 raw)
Step 4.6: dedup — 93 raw → 76 canonical (12 exact-merged, 5 semantic-merged, 0 conflict-suffixed); packs contributing: [quality, security, reliability, brand]
Step 4.7: audit passed — all three layers per site, chain failures distinct, every pack contributed
Step 5: clustered 76 failure modes into 13 top-level + 6 sub taxonomy nodes
Step 6: using grader author evals-prompt; fanned out 5 subagents (4 call sites + 1 chain) — synthesized 76 graders (71 single-call, 5 chain); 0 failed validation; calibrated 51 high, 19 medium, 6 low
Step 7: wrote evals/pipeline.yaml, evals/report.md, evals/.synth-lock.yaml; cross-checked 76 grader files via --bundle
evals/ written: 4 call sites | 1 chain | 76 failures | 76 graders (0 failed validation, 6 low-confidence) | 19 taxonomy nodes | 4 packs
Step 8: wrote evals/index.html (HTML viewer)
Browse the synthesized pipeline visually: open evals/index.html
The viewer reads only the local files under `evals/` — nothing leaves your machine until you click through the CTA button.
```

For a 12-call-site repo with traces, expect ~140-200 single-call graders + ~10-30 chain graders depending on how graph-shaped the system is. If your run produces less than ~10 single-call graders per call site on average, you under-explored step 4. If your run produces zero chains in a system that obviously composes LLM calls (LangGraph, agent loops, multi-step pipelines), you under-explored step 4.5 — re-read `prompts/analyze_chains.md`.

**If your output is heavy on schema checks and light on user-centric graders**, you skipped Layer B in step 4. Re-read `prompts/hypothesize_failures.md` § "Layer B" and the per-shape priorities — your failure-mode set should have at least 5 judgmental failures per call site, and the audit in step 4.6 should have caught this.

**If your output is heavy on user-centric graders and light on schema checks**, you skipped Layer A. Mechanical graders are cheap, deterministic, and worth always including. Add 3-8 per call site.

Both layers, every time.
