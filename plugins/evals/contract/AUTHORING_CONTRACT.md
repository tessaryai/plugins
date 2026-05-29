# Grader-author contract (v7)

This document defines the interface between **synthesize-graders** (the orchestrator) and any **grader author** invoked during the grader-synthesis phase. It exists so that the author is swappable: the bundled `authors/default/` is the OSS fallback; closed-source or third-party authors (e.g. `evals-prompt`) declare conformance to this contract and become drop-in replacements.

- **Authoritative schema**: [`grader.schema.json`](./grader.schema.json) — the on-disk grader YAML.
- **Authoritative enforcer**: `validate.py` (at the plugin root) — runs the schema rules plus cross-field invariants, per-file and `--bundle` cross-references.
- **Contract version**: 7. v7 **removes per-grader `self_tests` entirely** (§ "What changed in v7"): the author no longer emits hand-authored self-test cases, the `self_test_pass_rate` / `self_test_variance` calibration fields, or the `applies_when ↔ not_applicable` self-test invariant. A grader's behavior is now validated **platform-side against golden datasets** — reusable, real captured spans associated with the grader and labeled per `(grader, dataset_item)` in evals-platform. The author emits only the verdict body, `applies_when`, `confidence`, and `rationale`.

## What changed in v7

- **`self_tests` are gone.** Authors no longer hand-write sample outputs + expected verdicts. Behavioral calibration moves to **golden datasets**: a curator associates a golden dataset (real captured spans) with a grader in evals-platform and labels each item with the expected verdict/level per `(grader, dataset_item)`; the platform runner then scores the grader against those real spans. This removes the duplicated, buried, hard-to-grow per-grader test suite.
- **`self_test_pass_rate` / `self_test_variance` are removed.** There is no step-6 self-test calibration. Calibration signal now comes from golden-dataset runs on the platform.
- **The `applies_when ↔ not_applicable` self-test invariant is removed.** Out-of-scope items are surfaced as `not_applicable` by the platform runner at golden-run time; the author no longer asserts a `not_applicable` self-test. `applies_when` itself is unchanged (still author-owned, still always LLM-evaluated).
- Everything else the author owns (the per-`kind` verdict body, `applies_when`, `confidence`, `rationale`) is unchanged from v6.

## What changed in v6

- **`applies_when` is always evaluated by an LLM at runtime.** For `kind=llm_judge`/`score` it rides inline in the judge prompt, as before. For `kind=deterministic` the platform now runs a **separate LLM applicability gate** before the body and skips out-of-scope outputs — so the `deterministic_check` is **gate-free**: it must implement only the failure check and assume the input is in scope (never decide applicability itself).
- **`applies_when_check` is removed.** It was the code-evaluable mirror compiled into a deterministic body; the gate is never compiled now, so do not emit it. `validate.py` flags it.
- **Trace deterministic checks receive structured input.** A `scope: trace` deterministic check runs against `input.messages` (turns of `{ role, content, tool_uses: [{ name, input }] }`) and `input.tool_uses` (every tool call across turns, flattened) — not just a flattened transcript string. The platform supplies this structured shape from the golden dataset's real trace spans.

## What changed in v5

- Call sites carry a new orchestrator-owned field **`default_grade_mode: per_turn | per_conversation`** (default `per_turn`). The orchestrator sets `per_conversation` when it detects a multi-turn site (turns sharing a trace at a `conversational_turn` / `agent_step` site) and then authors that site's failure-mode graders as `scope: trace`. Authors do not set this field.
- **Trace-grader history sourcing is pinned to the final turn's self-contained input** (the whole transcript lives in the last turn's `input`; the runner grades the latest turn per trace). This is a runner/contract clarification. See § "Trace graders".

## What changed in v4

- A new grader **`scope: trace`** grades the **final turn** of a multi-turn session at one call site, given the prior n-1 turns as context. It anchors to a `call_site_id` exactly like `single_call`. Used for cross-turn coherence failures.
- A new grader **`kind: agentic`** produces a **binary verdict** by running an agent in a sandbox (via opencode) — e.g. running `git diff` / tests / file exploration — instead of a single judge call. The author emits an **`agent_spec`**; the runner (evals-platform) executes it. The plugin never runs an agentic grader. Use it when the verdict requires inspecting the result the agent produced, not just the output text.
- Both are additive: a v3 author remains conformant for everything else; the orchestrator only needs a v4 author when it requests a trace or agentic grader.

## What changed in v3

- A new grader **`kind: score`** scores a **quality dimension** on an anchored 1–5 rubric, instead of returning a binary verdict. These are the subjective grey-area quality evals — tracked as a pass-rate/level trend over time, never a pass/fail gate.
- The orchestrator passes a `quality_dimension` block (instead of `failure_mode`) when it wants a score grader. The author returns `kind: score` with `rubric_levels` and `score_scale`.
- An author that cannot produce `kind: score` should still accept the `quality_dimension` input but may decline; the orchestrator then falls back to the bundled author for that grader.

## What changed in v2

- `applies_when_check` is a new author-owned field: a code-evaluable mirror of `applies_when` required when `kind=deterministic` AND `applies_when` is non-empty. (`applies_when_check` was later removed in v6; the per-grader self-test fields were removed in v7.)
- The orchestrator writes a `_meta` provenance block onto every grader file and respects `_meta.locked_fields` on re-run. Authors should not touch `_meta`.
- Per-grader operational fields (`owner`, `block_on_fail`, `cost_budget_tokens`, `latency_budget_ms_p95`, `dataset_refs`) are optional and orchestrator-owned by default; authors may emit `cost_budget_tokens` / `latency_budget_ms_p95` if they can reason about them, but the orchestrator fills in operational fields from the call site's `observed.*` stats when authors omit them.

## Roles

| Field on the on-disk grader | Who fills it in |
| --- | --- |
| `id` | orchestrator (derived from `failure_mode_id` / `chain_id`) |
| `scope` | orchestrator |
| `failure_mode_id` | orchestrator |
| `call_site_id` / `chain_id` | orchestrator |
| `name` | orchestrator |
| `taxonomy_node_id` | orchestrator (step 5 — clustering, before grader synthesis) |
| `owner`, `block_on_fail`, `dataset_refs` | orchestrator (sourced from call-site observed stats / curator input) |
| `cost_budget_tokens`, `latency_budget_ms_p95` | orchestrator (default: p95 stats from observed); author may override |
| `_meta` | orchestrator |
| `kind` | **author** |
| `applies_when` | **author** (always LLM-evaluated at runtime) |
| `judge_prompt` | **author** (when `kind=llm_judge`) |
| `rubric` | **author** (when `kind=llm_judge`) |
| `deterministic_check` | **author** (when `kind=deterministic`) |
| `execution_spec` | **author** (when `kind=execution`) |
| `agent_spec` | **author** (when `kind=agentic`) |
| `confidence` | **author** |
| `rationale` | **author** |

The orchestrator does **not** edit author-owned fields after they're written. If a returned grader looks wrong on inspection, the orchestrator re-invokes the author with refined context — it does not patch the YAML. Behavioral calibration happens later and separately, platform-side, by running the grader against its associated golden datasets (real labeled spans) in evals-platform.

## Input the orchestrator passes to the author

```yaml
failure_mode:
  id: <string>            # e.g. checkout::extraneous_action_items
  name: <string>          # short human-readable
  description: <string>   # 1-2 sentences — what failure looks like in production
  severity: low | medium | high
  layer: A | B | C | null # A = mechanical, B = judgmental, C = adversarial/operational
  scope: single_call | chain | trace

scope: single_call | chain | trace
# scope=trace is anchored to one call site (like single_call) but grades the final turn
# given prior turns; the call_site block below is supplied just as for single_call.

# When scope = single_call or scope = trace:
call_site:
  id: <string>
  intent: <string>
  constraints: [{kind, description, enforcement}]
  prompt_text: <string>
  shape: summarize | extract | rag_answer | classify | draft | route | tool_call
       | agent_step | conversational_turn | embedding | rerank | guardrail
       | moderation | ensemble_vote | other
  sample_count: <int | null>
  observed: <observed stats block from pipeline.yaml, optional>
  sample_outputs: [<string>, ...]  # optional; up to ~5 representative captured outputs

# When scope = chain:
chain:
  id: <string>
  call_site_ids: [<string>]
  detection_method: trace_confirmed | state_mediated | sequential_composition | ensemble
  rationale: <string>
call_sites: [<call_site>...]   # one per id, in chain order

product_context:           # optional but recommended
  domain: <string | null>
  brand_voice_signals: [{label, evidence}]
  regulatory_context: [{label, evidence}]

existing_grader:           # optional — present only when regenerating
  judge_prompt: <string>
  rubric: <string>
  applies_when: <string | null>
  locked_fields: [<field>, ...]    # author MUST preserve these verbatim

validator_feedback:        # optional — present on retry after a validate.py failure
  attempt: <int>           # 1-based; only set on retries (so attempt >= 2)
  errors: [<string>]       # stderr lines from validate.py
```

## Output the author returns

Raw YAML, ready for the orchestrator to splice into the on-disk grader file. **No prose around it.** Only the author-owned fields:

```yaml
kind: llm_judge | deterministic | execution | agentic
applies_when: |                  # OMIT entirely when always applicable. Always LLM-evaluated:
                                 # inline for llm_judge/score, a separate LLM gate for deterministic.
  natural-language predicate deciding whether the check is in scope
judge_prompt: |                  # required for kind=llm_judge
  the full system prompt the LLM judge runs at runtime
rubric: |                        # required for kind=llm_judge
  - bulleted pass/fail criteria
deterministic_check: |           # required for kind=deterministic. GATE-FREE: implement only the
                                 # failure check; assume the input is in scope (the applies_when LLM
                                 # gate filters out-of-scope outputs first). For scope=trace, reason
                                 # over input.messages / input.tool_uses, not a flattened string.
  precise rule a code function can implement
execution_spec: |                # required for kind=execution
  how to run the output and what counts as pass/fail
agent_spec:                      # required for kind=agentic (see § "Agentic graders")
  harness: opencode
  sandbox: { image: <string>, network: none | egress | full }
  allowed_tools: [bash, read, git]
  task_prompt: <string>          # the grading task; ends in one binary decision
  verdict_contract: <string>     # how the agent emits PASS/FAIL the runner can parse
  budgets: { max_turns: <int>, max_cost_usd: <float>, timeout_s: <int> }   # optional
confidence: high | medium | low
rationale: <string>              # one sentence — user impact, not mechanics
```

> **No `self_tests` (v7).** Authors no longer emit per-grader self-test cases. A grader's behavior is calibrated platform-side against **golden datasets** — real captured spans associated with the grader and labeled per `(grader, dataset_item)` in evals-platform — not against hand-authored samples in the grader file.

### Invariants the author must satisfy

1. **Gate-free deterministic body** (v6): `applies_when` is always evaluated by an LLM — never compiled. Do **not** emit `applies_when_check`, and do **not** make `deterministic_check` decide applicability (it must assume the input is in scope; the LLM gate filters out-of-scope outputs first). `validate.py` flags a stray `applies_when_check`.
2. **`kind` body match**: `kind=llm_judge` requires `judge_prompt` + `rubric`; `kind=deterministic` requires `deterministic_check`; `kind=execution` requires `execution_spec`; `kind=agentic` requires `agent_spec` (and no `judge_prompt`/`rubric`).
3. **Locked fields**: if `existing_grader.locked_fields` is present on the input, the returned YAML must reproduce the listed fields **verbatim** (the orchestrator double-checks and rejects mutated locked fields).

Everything else (id shape, taxonomy node, cross-reference against `pipeline.yaml`, `_meta` provenance) is the orchestrator's responsibility.

## Trace graders (v4)

When the orchestrator passes `scope: trace`, the failure can only be judged with the conversation
history (a cross-turn coherence failure on a `conversational_turn` / `agent_step` site). The author
produces the **same author-owned fields as a single_call grader** (any failure-catching `kind`); the
difference is purely in how the platform feeds the grader at runtime (the prior n-1 turns as context
plus the final turn it judges), not in anything the author writes.

For a **trace `llm_judge`** grader, write the `judge_prompt` so it judges the final turn **in the context of** the prior conversation — e.g.
"Given the conversation so far, does the final assistant turn stay consistent with commitments and
constraints established earlier?" That contextual framing is the whole point of the scope.

For a **trace `deterministic`** grader, the `deterministic_check` runs against the structured trace —
`input.messages` (each turn `{ role, content, tool_uses: [{ name, input }] }`) and `input.tool_uses`
(every tool call flattened) — so reason over those, not a flattened transcript string. Keep the body
gate-free (the `applies_when` LLM gate handles scope).

**History sourcing (v5).** In production the runner does not stitch per-turn rows: it groups a
multi-turn site's observations by trace, takes the **latest turn**, and judges its `input` (which
already carries the whole transcript) plus its final output. The author is unaffected. The call site
that gets these graders is the one the orchestrator marked `default_grade_mode: per_conversation`.

## Agentic graders (v4)

When a failure can only be judged by inspecting the **result the agent produced** — did the repo end
up correct, does the `git diff` implement the request, do the tests pass — a static judge reading text
can't decide. The author emits `kind: agentic` with an `agent_spec` describing an agent the runner
launches in a sandbox. **The plugin only emits the spec; evals-platform executes it.** Verdicts are
binary (pass/fail) in v4.

```yaml
kind: agentic
agent_spec:
  harness: opencode              # the only harness today
  sandbox:
    image: <string>              # e.g. the project's CI image, or opencode/base:latest
    network: none                # most restrictive the task allows: none | egress | full
  allowed_tools: [bash, read, git]
  task_prompt: |                 # self-contained; ends in one binary decision
    Check out the session's repo at the final turn. Run `git diff <base> <head>` and decide
    whether the change correctly implements the user's request from the conversation. ...
  verdict_contract: |            # how the agent signals its result so the runner can parse it
    Print exactly one line `VERDICT: PASS` or `VERDICT: FAIL` as the last line of output.
  budgets: { max_turns: 20, max_cost_usd: 0.50, timeout_s: 600 }
confidence: high | medium | low
rationale: <string>
```

### Agentic-grader invariants

1. **`agent_spec` required**: `harness` (`opencode`), `sandbox.image`, `task_prompt`, and
   `verdict_contract` are all non-empty; `allowed_tools` is a list when present.
2. **Binary only (v4)**: the agent produces a `pass` / `fail` verdict. No 1–5 scoring in v4.
3. **No judge body**: do not emit `judge_prompt` / `rubric` / `deterministic_check` /
   `execution_spec` — the `agent_spec.task_prompt` is the grading instruction.
4. **Least privilege**: pick the most restrictive `sandbox.network` the task allows and the minimal
   `allowed_tools`. A grader that doesn't need network must set `network: none`.

## Score graders (v3)

When the orchestrator wants a quality-dimension score grader, it passes a `quality_dimension` block in place of `failure_mode`:

```yaml
quality_dimension:
  id: <string>                 # e.g. persona_decision::basis_selection_relevance
  name: <string>               # snake_case axis name
  description: <string>        # what this axis measures
  why_it_matters: <string>     # why a sustained dip hurts the product
  rubric_levels:               # anchored 1–5, each a concrete observable description
    "5": <string>
    "4": <string>
    "3": <string>
    "2": <string>
    "1": <string>
  scope: single_call

scope: single_call
call_site: { ... }             # same call_site block as for failure modes
product_context: { ... }       # optional, same as above
existing_grader: { ... }       # optional, on regeneration
```

The author returns the score-grader author-owned fields:

```yaml
kind: score
judge_prompt: |                # the prompt the judge runs; it must instruct the judge to
                               # return one integer level in [score_scale.min, max] + a
                               # one-line justification, scoring strictly against rubric_levels
rubric_levels:                 # carry forward (or sharpen) the dimension's anchored levels
  "5": <string>
  "4": <string>
  "3": <string>
  "2": <string>
  "1": <string>
score_scale: { min: 1, max: 5 }
confidence: high | medium | low
rationale: <string>            # one sentence — why this axis matters for the product
```

### Score-grader invariants

1. **`expected_level` range** (golden labels): when a curator labels a golden item for a score grader, the expected level is an integer within `score_scale` `[min, max]`. The platform enforces this at label time, not the author.
2. **Rubric fidelity**: `rubric_levels` keys must be the stringified integers covering `[min, max]`; each anchor must be concrete and observable.

Score graders never use `applies_when` / `not_applicable` (they always apply when the call site fires), and `block_on_fail` is always `false` (orchestrator sets it) — a score grader is a trend, never a gate.

## Retry semantics

The orchestrator (or its step-6 subagents) runs `validate.py` on every emitted grader. On failure it re-invokes the author with the original input **plus** a `validator_feedback` block (see input schema above). Up to **3 retries** total. After the third failure, the orchestrator writes the last attempt to disk with a top-level `_validation_error: <message>` key and continues — the operator handles it during review.

When `_validation_error` is set on a grader file, `validate.py` returns exit 0 on subsequent runs (it short-circuits all other rules). This is intentional: the operator-facing `report.md` "Validation warnings" section and the `<F> failed validation` count in the summary line already surface these files; a later `--pipeline` cross-check pass should not double-flag them.

Authors should treat `validator_feedback.errors` as the primary signal for what to change on retry; the orchestrator does not paraphrase or filter the validator output.

## Declaring conformance

An author conforms to this contract when:

1. It accepts the input schema above (extra fields ignored).
2. It returns YAML matching the author-owned fields above.
3. Its output passes `validate.py` once the orchestrator splices in the orchestrator-owned fields.
4. It declares the contract version it conforms to via `contract_version:` — in its SKILL.md frontmatter for skill-based authors, or in its top-level markdown for bundled-procedure authors. The **current contract version is 7**; an author fully caught up declares `7`. The version requirement is a **minimum, evaluated per feature**: the orchestrator requires *at least* `3` for `kind: score`, and *at least* `4` for `scope: trace` or `kind: agentic`. v6 is NOT transparent for deterministic graders with a gate: a `< 6` author still emits the removed `applies_when_check` and may bake applicability into `deterministic_check`, which now fails `validate.py` / produces a double-gate. So for `kind: deterministic` with an `applies_when`, the orchestrator requires `6`. **v7 is author-transparent in the safe direction**: it only *removes* the self-test fields, so a `< 7` author that still emits `self_tests` is no longer conformant in form, but the orchestrator simply drops any stray `self_tests` it returns (the platform ignores the key). New authors must declare `7` and emit no self-tests.

The orchestrator discovers authors by **two distinct invocation models**:

- **Skill-based authors** (e.g. `evals-prompt`) — invoked through the Skill tool. Preferred when available.
- **Bundled markdown author** (`authors/default/AUTHOR.md`) — read as a procedure and followed inline by the step-6 subagent. Always available because it ships with this plugin. No Skill-tool call.

This distinction matters: subagents that try to invoke the bundled author via the Skill tool will fail because there is no skill of that name. The orchestrator's subagent prompt must branch on author type. See `SKILL.md` § "Author discovery" for the exact branching logic. Future versions may surface explicit selection.
