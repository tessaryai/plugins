# default — bundled grader author for synthesize-graders (v8)

This is the OSS fallback grader-author. It implements the contract in `../../contract/AUTHORING_CONTRACT.md` (v8) and is selected when no higher-priority author skill (e.g. `evals-prompt`) is available in the session.

> **Judge body is platform-deferred (v8).** For `kind=llm_judge` and `kind=score` this author no longer writes the `judge_prompt` / `rubric`. It emits the grader *definition* — `kind`, `applies_when` (llm_judge), `rubric_levels`+`score_scale` (score), `confidence`, `rationale` — plus a top-level marker **`_body_source: platform`**, and the platform synthesizes the runtime judge body on import. `kind=deterministic`/`execution`/`agentic` bodies are unchanged (still authored here). Skip steps 3–4 below for `llm_judge`; emit `_body_source: platform` instead.

It is **deliberately minimal**. It produces graders that pass `validate.py` and are readable for review. For `kind=llm_judge`/`score` the judge body is platform-deferred (v8), so this author only writes the definition; for `deterministic`/`execution`/`agentic` it authors the body, but with generic, light-touch checks a dedicated authoring skill would sharpen.

> **No `self_tests` (v7).** This author does not emit per-grader self-test cases. A grader's behavior is calibrated platform-side against **golden datasets** — real captured spans associated with the grader and labeled per `(grader, dataset_item)` in evals-platform — not against hand-authored samples in the grader file. Author only the verdict body, `applies_when`, `confidence`, and `rationale`.

## Invocation

Unlike a Claude Code skill, this author is not invoked via the `Skill` tool — `synthesize-graders`'s step-6 subagents read this file and follow it inline when no skill-based author is available. The subagent passes the same input the contract specifies; the procedure below produces the same author-owned YAML body the contract specifies.

## Inputs received

Exactly the input documented in `contract/AUTHORING_CONTRACT.md` § "Input the orchestrator passes to the author". Treat missing optional fields as absent (do not fabricate). On retry, read `validator_feedback.errors` and address every reported issue before re-emitting.

When the input includes `existing_grader.locked_fields`, you MUST reproduce those fields verbatim in your output. The orchestrator double-checks and rejects mutated locked fields.

## Output

The author-owned YAML body documented in the contract — **no surrounding prose**. The orchestrator splices the routing fields, the `_meta` block, and the operational fields on top.

## Procedure

### 1. Pick `kind`

- `deterministic` — the failure can be checked by a regex, JSON-schema validator, parser, or simple Boolean predicate on the output. Layer A failures (format, structural invariants, refusal-condition breaches) are usually this kind. Many Layer C failures (token-count budgets, latency timers, PII regex matches) also land here.
- `llm_judge` — the failure requires reading the output for meaning. Layer B failures (faithfulness, helpfulness, calibration, tone, edge-case judgment) and Layer C judgment failures (jailbreak resistance, prompt-injection resistance) are usually this kind. Default to `llm_judge` when in doubt.
- `execution` — the output is code or a tool call that can be executed and checked mechanically. Use only when this is obvious from the call-site shape.
- `agentic` — the verdict requires **inspecting the result the agent produced** (run `git diff` / tests / explore files), not just reading the output text. Typical on `sandbox_agent` / `cli_agent` call sites and failures flagged as needing environment inspection. Produces a binary pass/fail via an `agent_spec` the runner executes — follow § "Agentic graders" below for the `agent_spec` (steps 3–4 about judge_prompt/rubric do not apply).
- `score` — **only when the input is a `quality_dimension` block, not a `failure_mode`.** The grader assigns a 1–5 level on an anchored rubric instead of a pass/fail verdict. Follow § "Score graders" below instead of steps 2–9.

If the input's `scope` is `trace`, author exactly as for `single_call` (see § "Trace graders") — the `kind` choice above is unchanged; only the runtime input framing differs.

When the input is a `quality_dimension` (not a `failure_mode`), always use `kind: score` and follow the Score graders section. Everything in steps 2–8 is for failure-mode graders.

### 2. Set `applies_when` (or omit)

If the failure mode's description names a precondition for the failure to be possible (e.g. "memory citation" only applies when the output claims to recall earlier info; "tool argument validity" only applies when the output contains a tool_call), set `applies_when` to a one-sentence predicate phrased as a positive condition on the output. Otherwise omit the field entirely.

`applies_when` is **always evaluated by an LLM** at runtime (v6): inline in the judge prompt for `kind=llm_judge`/`score`, and via a separate LLM applicability gate for `kind=deterministic`. So there is **no** `applies_when_check` to write (it was removed in v6 — `validate.py` flags it), and a `deterministic_check` must be **gate-free**: implement only the failure check and assume the input is in scope; the gate filters out-of-scope outputs first.

### 3–4. Defer the judge body to the platform (only when `kind=llm_judge`) — v8

For a `kind=llm_judge` grader you do **not** author the `judge_prompt` or the `rubric` anymore. Emit the top-level marker `_body_source: platform` and stop — the platform synthesizes the judge body (the injection-hardened system prompt with the inline `applies_when` gate and the JSON verdict contract, plus the pass/fail rubric) on import, from the failure-mode definition this grader links to.

```yaml
kind: llm_judge
_body_source: platform
applies_when: |          # OMIT when always applicable (see step 2)
  <one-sentence positive precondition for the failure to be in scope>
# NO judge_prompt, NO rubric — the platform authors them.
confidence: high | medium | low
rationale: <one sentence — user impact>
```

Do **not** emit a `judge_prompt`/`rubric` alongside `_body_source: platform`; `validate.py` rejects a grader that sets the marker but still carries a non-empty body (it means you forgot to actually defer it). The `applies_when` precondition (step 2) is still author-owned and is what the platform folds into the judge body's in-scope gate, so phrase it well.

(For `scope=chain` and `scope=trace` the body is likewise deferred; the platform builds the multi-output / contextual judge prompt from the chain/trace definition. The author still picks `kind` and writes `applies_when` exactly as for `single_call`.)

### 5. Author `deterministic_check` (only when `kind=deterministic`)

A single precise sentence a developer can implement as a function returning `pass` or `fail`. Refer to concrete fields/patterns. Example: "Parse the output as JSON; pass if it parses and contains exactly the keys `summary` and `action_items`; fail otherwise."

### 6. Author `execution_spec` (only when `kind=execution`)

A single precise sentence describing how to execute the output and what counts as pass/fail. Example: "Run the emitted SQL against the read-only fixture DB; pass if it returns at least one row and does not error; fail otherwise."

### 6b. Author `agent_spec` (only when `kind=agentic`)

Emit an `agent_spec` instead of `judge_prompt`/`rubric`. The runner launches an agent in a sandbox to reach a binary verdict. Required fields:

- `harness: opencode`.
- `sandbox`: `{ image: <string>, network: none | egress | full }`. Pick the project's CI image when known, else a sensible base. Choose the most restrictive `network` the task allows — `none` unless the task genuinely needs to fetch something.
- `allowed_tools`: the minimal list, e.g. `[bash, read, git]`.
- `task_prompt`: self-contained grading instructions that end in **one binary decision**, e.g. "Check out the repo at the session's final turn, run `git diff <base> <head>`, and decide whether the change correctly implements the user's request from the conversation. Run the test suite if present."
- `verdict_contract`: how the agent signals its result so the runner can parse it, e.g. "Print exactly `VERDICT: PASS` or `VERDICT: FAIL` as the final line."
- `budgets` (optional): `{ max_turns, max_cost_usd, timeout_s }` — set conservative caps.

Do **not** emit `judge_prompt`, `rubric`, `deterministic_check`, or `execution_spec` for an agentic grader. The `agent_spec.task_prompt` is the entire grading instruction.

### 6c. Trace graders (`scope: trace`)

When the input `scope` is `trace`, author exactly as for `single_call` (any failure-catching kind). Nothing about the author-owned fields changes; only how the platform feeds the grader at runtime differs — it supplies the prior n-1 turns as context plus the final turn the grader judges.

The judge body is platform-deferred (v8): emit `_body_source: platform` and no `judge_prompt`/`rubric`. The platform builds a judge prompt that judges the **final turn in the context of** the prior conversation — catching a final turn that looks fine alone but is wrong given the history (it contradicts a constraint the user set three turns earlier). That contextual framing is the reason the scope exists, and the platform encodes it from the trace-scope failure-mode definition.

### 7. Set `confidence`

- `high` — rubric uses unambiguous criteria; you had enough context (real sample outputs, product profile) to author this well.
- `medium` — the rubric makes judgment calls; some criteria are borderline.
- `low` — sparse context (no call-site sample outputs, no product profile); the grader needs manual review.

When in doubt and you are the default author, prefer `medium`. Behavioral calibration happens later, platform-side, by running the grader against its associated golden datasets — your `confidence` is the author's initial signal, not the final word.

### 8. Author `rationale`

One sentence in user-impact terms. State *why this matters in production*, not what the rubric mechanically checks.

Good: "RAG answers in this codebase frequently cite documents not in the retrieval set, which would mislead the user about the source of the information."

Bad: "Checks citations."

## Score graders (input is a `quality_dimension`)

Produce `kind: score`. Do not use steps 2–8; there is no `applies_when`, no binary verdict.

1. **`score_scale`**: `{ min: 1, max: 5 }`.
2. **`rubric_levels`**: carry forward the dimension's `rubric_levels`. You may sharpen the wording so each level is concrete and observable, but keep five levels and keep them monotonic (5 = best). Do not invent a different axis than the dimension describes.
3. **`_body_source: platform`** (v8): emit this marker and do **NOT** write a `judge_prompt`. The platform synthesizes the scoring judge prompt on import from `rubric_levels` + `score_scale` — it instructs the judge to read the output, score strictly against the anchored levels, and return exactly one integer in `[score_scale.min, max]` plus a one-sentence justification (defaulting to the lower of two adjacent levels when uncertain). Your job is the crisp, observable `rubric_levels`; the platform owns the prompt prose. `validate.py` rejects a score grader that sets the marker but still carries a `judge_prompt`.
4. **`confidence`**: `high` only if the rubric levels are crisp and you expect the judge to score repeatably; `medium`/`low` when the axis is genuinely fuzzy.
5. **`rationale`**: one sentence on why this quality axis matters for the product over time.

Behavioral calibration (does the judge actually score golden spans at the expected levels?) happens platform-side: a curator labels golden dataset items with the expected level per `(grader, dataset_item)` and the platform runs the grader against them.

The orchestrator sets `block_on_fail: false` and the routing/`_meta` fields; you only emit the author-owned body above.

## Retry behaviour

On retry, the input carries `validator_feedback.errors`. Read every error, identify which output field caused it, and fix it before re-emitting. Common failures and fixes:

| Validator error | Fix |
| --- | --- |
| `kind=llm_judge requires non-empty judge_prompt` / `rubric` | v8: do not author these — set `_body_source: platform` so the platform expands the body on import. (Only seen if you also omitted the marker.) |
| `_body_source=platform defers the body ... judge_prompt`/`rubric` `must be omitted/empty` | You set `_body_source: platform` but still emitted a `judge_prompt`/`rubric`. Delete the body; keep only the definition + marker. |
| `_body_source is only valid for kind in ['llm_judge', 'score']` | You put `_body_source` on a deterministic/execution/agentic grader. Remove it — only `llm_judge`/`score` defer the body. |
| `applies_when_check was removed in v6` | Delete `applies_when_check`; keep the `deterministic_check` gate-free (the applies_when LLM gate handles scope). |
| `kind=agentic requires a non-empty agent_spec mapping` | Emit `agent_spec` per § 6b; remove any `judge_prompt`/`rubric`. |
| `agent_spec.harness must be 'opencode'` / `sandbox` / `task_prompt` / `verdict_contract` ... | Fill the missing/invalid `agent_spec` field per § 6b. |
| `locked field <X> was mutated from existing_grader` | Restore `<X>` verbatim from `existing_grader.<X>`. |

If after fixes the validator still complains about something you cannot satisfy in this attempt, return your best-effort YAML — the orchestrator will write it with `_validation_error` and surface it to the operator.
