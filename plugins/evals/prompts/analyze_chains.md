You are analyzing relationships **across** LLM call sites. Per-site failure modes (step 4) are about each call in isolation. This step is about how calls compose: when LLM B's input depends on LLM A's output (directly or through state), what coherence properties should hold across that pair, and which ways the chain can break that no per-site grader would catch.

Chain-scoped failures are a **separate category** from single-call failures. They produce graders with `scope: chain` (vs `scope: single_call`) and require a runner that can fetch N call-site outputs from one logical session. Do not bury chain failures in the per-site list.

## Step 0 — Build the trace tree (when traces are provided)

Before applying detection methods, **build a tree of spans per `trace_id`** using each span's `parent_id`. Real agent traces are tree-shaped, not linear — a parent span may have many children that run in parallel, sequentially, or both. The shape of the tree is the primary detection signal:

- **Sequential parent→child** edges: child span depends on parent span's output. Strong chain candidate.
- **Sibling spans with identical normalized prompts** under the same parent: parallel ensemble (self-consistency, voting, n>1 sampling). Detection method = `ensemble`; combined shape = `ensemble_vote`. Not a sequential chain.
- **Sibling spans with different prompts** under the same parent and overlapping payloads: independent fan-out (e.g. a router invoking multiple specialists). Each child may form its own sub-chain with the parent.
- **Spans sharing `trace_id` but no causal ancestry**: unrelated work in the same session. Do **not** chain these.

If `parent_id` is missing on all spans (some exporters drop it), fall back to start_time ordering within `trace_id` plus payload overlap — but lower the chain's `confidence` by one level.

## What counts as a chain

Two ≤ N ≤ 5 call sites that participate in one logical flow. Detection methods, in priority order:

1. **Trace-confirmed** (highest confidence, only when traces are provided): spans linked by `parent_id` in the same `trace_id`, where output of the parent span appears in the input of a child span (payload overlap). Use the trace tree built in step 0.
2. **Ensemble** (high confidence, only when traces are provided): N ≥ 2 sibling spans under the same `parent_id` with **identical normalized prompts** but potentially different outputs. The combined unit is one chain whose `call_site_ids` is the same id repeated; the runner grades disagreement across the siblings. Use `detection_method: ensemble` and emit `ensemble_span_ids: [<hex>, ...]` in the chain record.
3. **State-mediated** (medium confidence, static): A's output type or output state-field name appears in B's input via grep — e.g. A returns `WebsiteRef` stored to `state.website_ref`, and B's surrounding code reads `state.website_ref` to construct its prompt.
4. **Sequential composition** (low confidence, static): A and B are called in the same function in obvious order, A's return value passed as B's input.

Skip pairs that are clearly not coupled (e.g. two summarizers in different request handlers that never share data). Better to detect five strong chains than twenty speculative ones.

## What you produce

### `chains`

```yaml
- id: chain::<short snake_case label, stable across re-runs>
  name: <human-readable, e.g. "website-extraction → asset-generation">
  call_site_ids: [<id_a>, <id_b>, ...]   # ordered, A first; for ensemble, the same id repeated
  detection_method: <trace_confirmed | ensemble | state_mediated | sequential_composition>
  confidence: <high | medium | low>
  rationale: <one sentence — what data flows from A to B; cite file paths or trace evidence>
  ensemble_span_ids: [<hex>, ...]        # only when detection_method == ensemble
```

Stable IDs: pick a label that reflects intent, not call-site IDs (e.g. `chain::url_extract_then_asset_gen`, not `chain::callsite42_to_callsite43`). For ensembles, use `chain::<call_site_id>__ensemble`. Re-runs on the same repo + traces should produce the same chain IDs.

### Per-chain failure modes

For each chain, hypothesize **3-8 cross-call failure modes** drawn from the categories below. These are *in addition to* the per-site failures from step 4 — they're things only visible when you read multiple outputs together.

Failure mode IDs: `<chain_id>::<failure_name>`. Chain failure modes always have `scope: chain` and reference the `chain_id`.

## Cross-call failure categories

Use these as the primary lens. Per-shape priorities still apply (e.g. RAG chains skew toward faithfulness propagation).

### 1. Context drop — B doesn't use what A surfaced

The most common chain failure. B receives A's output structurally (the field is populated), but B's reasoning treats it as boilerplate or generic input rather than meaningful product context.

- **Example**: A extracts `WebsiteRef(domain="acme-clinic.health")`. B receives the crawl + the domain but generates assets that could be for any business — color scheme, copy, CTAs all generic. Grader: "given B's output and A's output, do B's brand decisions reflect A's specific extracted brand/domain context, or are they generic?"
- **Example**: A classifies an inbound message as `"refund_request"`. B drafts the response acknowledging the issue but never proposes a refund.

### 2. Context contradiction — B disagrees with A's interpretation

B's output is internally coherent but contradicts a fact or framing established by A. Particularly damaging because the chain looks clean — both calls "succeeded" in isolation.

- A's parsed intent: "user wants to cancel". B's drafted response: "thanks for upgrading."
- A says the website is a clinic. B's generated copy positions it as a fitness studio.

### 3. Confidence not propagated — B over- or under-commits relative to A

A surfaced uncertainty (`unknown`, `low_confidence`, missing required field). B should bound its commitment accordingly. Most agentic systems silently strip confidence when passing data downstream.

- A: `"contact_email: null (not found in input)"`. B drafts an email and includes the email field in the salutation as if it were known.
- A: `confidence: 0.4`. B states the conclusion as fact.

### 4. Conditional gate misfire — B runs when it shouldn't, or doesn't when it should

In conditional flows (e.g. B fires only when A returned a URL), the gate can fail in either direction.

- B fires on an empty/null A output it should have skipped (wastes tokens, produces nonsense or hallucinates input).
- B fails to fire on a non-null A output it should have processed (silent dropout).
- Gate logic is right, but A's output shape pretends to be present (empty string vs. null).

### 5. Information redundancy — B re-derives what A already extracted

B does the work A's output already encodes, often because the prompt doesn't cleanly forward A's structured output. Symptom: B's reasoning re-asks "what is the website?" and answers from the crawl text rather than using A's structured `WebsiteRef.domain`.

### 6. Stateful drift (3+ call chains) — intermediate state contradicts itself

In a chain A → B → C, B updates state in a way that conflicts with the snapshot C receives. Often a side effect of state mutation in async systems.

### 7. Tool/argument coherence (tool-call chains) — argument values inconsistent with A's output

Tool call B is invoked with arguments that don't reflect A's extracted entities (looks-up a different ID, passes the wrong filter, uses a default value when A surfaced a specific one).

### 8. Cumulative bias / drift (long chains in agent loops) — subtle errors compound

Each step is "fine" but the cumulative trajectory diverges from the user's request. Hard to grade per step; only visible across the chain.

### 9. Ensemble disagreement masked (only for `detection_method: ensemble`)

N sibling outputs disagree materially, but the chosen output silently overrides the majority. The choice rule (often "pick first" or "pick longest") hides real model uncertainty.

- All 3 siblings classify a ticket as `refund`; the chosen output says `general_inquiry`.
- 4 of 5 siblings refuse a request; the chosen output answers it.

Severity tied to the downstream impact of the chosen output. Almost always `high` when present.

### 10. Ensemble majority wrong (only for `detection_method: ensemble`)

The majority agrees and is wrong; the minority is correct. Self-consistency masks model bias. Harder to grade without ground truth — usually surface as a `kind: llm_judge` chain grader that flags ensembles where the majority's confidence is low.

## Output format

Print under the heading `## Step 4.5 — chain analysis`:

```yaml
chains:
  - id: chain::...
    name: ...
    call_site_ids: [...]
    detection_method: ...
    confidence: ...
    rationale: ...
    ensemble_span_ids: [...]    # only when detection_method == ensemble

chain_failure_modes:
  - id: <chain_id>::<failure_name>
    chain_id: <chain_id>
    name: <snake_case>
    description: <one or two sentences, specific to this chain>
    severity: <low | medium | high>
    layer: null               # layer is single-call concept; null for chain failures
    scope: chain
```

## Anti-patterns

- ❌ Generic "outputs disagree" failures with no specific contract violation.
- ❌ Failures that are really per-site (e.g. "B hallucinates a field" — that's a step-4 failure on B alone, not a chain failure).
- ❌ Inventing chains that aren't grounded in code or traces. If you can't cite the data flow, don't propose the chain.
- ❌ Producing chain failures for shapes that don't compose (two independent classifiers running on different data are not a chain).
- ❌ Modelling parallel siblings as a sequential chain. If `parent_id` is the same for both spans, the relationship is `ensemble` or independent fan-out — never `trace_confirmed` sequential.
- ❌ More than 8 failures per chain. If you have that many, the chain is over-coupled — re-examine whether you're describing real cross-call failures or just per-site ones with extra steps.

## When chain detection should fail open

If the system has clearly independent call sites (a webhook handler that calls one summarizer and never composes outputs), produce **zero chains** rather than fabricating coupling. An empty `chains: []` is a valid and useful output.
