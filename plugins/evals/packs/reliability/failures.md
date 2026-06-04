# reliability pack — failure synthesis

Reliability failures are operational. Every failure produced here is **Layer C** and carries:

```yaml
pack_ids: [reliability]
compliance_tags: [NIST-AI-RMF.MS-2.5]   # only attach when synchronicity is "synchronous" or
                                         # cost_of_wrong (from quality interview) is harm/lost_revenue
layer: C
```

Failures are anchored to `call_sites[].observed.*` whenever possible — the budgets in the rubric should reference concrete numbers, not vague "high" / "low".

## Mapping interview answers → failures

### From `synchronicity`

| Answer | Emit |
|---|---|
| synchronous | `latency_regression_p95`, `cold_start_latency_user_visible` — `severity: high` |
| async | `latency_regression_p95` — `severity: medium` |
| batch | `total_runtime_blows_window` — `severity: low`; **skip cold-start failures** |

### From `latency_budget`

For each call site, produce one budget-anchored failure:

```yaml
- name: latency_regression_p95
  description: "p95 end-to-end latency for this call exceeds {budget_ms} ms (anchored to observed.p95_latency_ms × 1.2, or user-specified)."
  layer: C
  severity: high           # if synchronicity == synchronous, else medium
  kind: deterministic      # timer at runtime
```

If `observed.p95_latency_ms` is null and the user gave a budget, use the user value. If both are null, skip the failure with a warning logged to the run log.

### From `cost_ceiling`

```yaml
- name: cost_regression_per_call
  description: "Cost per call (input + output tokens × model price) exceeds {ceiling_usd}."
  layer: C
  severity: medium
  kind: deterministic
```

Plus, for `draft` / `summarize` / `agent_step` shapes — failure modes that catch verbosity-induced cost blow-ups:

```yaml
- name: output_token_count_runaway
  description: "Output is materially longer than the prompt requested (>2× the observed.p95_tokens_out anchor)."
  layer: C
  severity: medium
  kind: deterministic
```

### From `variance_tolerance`

| Answer | Emit |
|---|---|
| none | `output_byte_identical_across_reruns` — `severity: high`, `kind: deterministic` (re-run twice at temp 0; hash). |
| semantically-equivalent | `output_semantically_drifts_across_reruns` — `severity: medium`, `kind: llm_judge` (judge compares two runs). |
| free | skip the variance failure category entirely |

For `classify`, `route`, `tool_call` shapes when variance_tolerance is not `free`, also emit:

```yaml
- name: gate_decision_flips_across_reruns
  description: "Re-running the same input produces different downstream gate decisions (route taken / tool selected / label assigned)."
  layer: C
  severity: high
  kind: deterministic
```

### From `fallback`

| Answer | Emit |
|---|---|
| hard_fail | (nothing extra — error surfacing is the runtime's job) |
| silent_fallback | `refusal_rate_unmonitored`, `error_rate_unmonitored`, `fallback_response_indistinguishable_from_real` — `severity: high` (silent fallbacks make production breakage invisible) |
| retry | `retry_storm_under_provider_outage` — `severity: medium` |
| degrade | `degraded_response_unmarked` — `severity: medium` |

### From `observed.error_rate` (when traces were ingested)

If `observed.error_rate > 0.01` for any call site, emit:

```yaml
- name: observed_error_rate_already_elevated
  description: "Observed error_rate in the trace window exceeds 1% — a baseline grader to monitor and alert on, anchored at the current rate."
  layer: C
  severity: medium
  kind: deterministic
```

This isn't really a failure-mode hypothesis — it's a guardrail anchored to current production reality. Useful for catching regressions later.

## Output

Emit as regular step-4 contributions in the **canonical failure-mode entry shape** documented in `prompts/per_site_kit.md` (§ "Required fields" / "single_call entry") — every entry must carry the full schema (`id`, `scope`, **`call_site_id`**, `chain_id: null`, `name`, `description`, `severity`, `layer`, `pack_ids`, `compliance_tags`, `taxonomy_node_id: ""`, `grader_id`, `grader_deferred`), not just `pack_ids`. Step 4.6 dedup rarely affects reliability failures (the failure names are operationally specific and don't usually collide with quality/security).

## Anti-patterns

- ❌ Emitting cost/latency failures without numeric anchors — graders that say "latency too high" without a threshold are useless.
- ❌ Emitting variance failures when the user said `free` — skip.
- ❌ Emitting cold-start failures for batch jobs — irrelevant.
- ❌ Inflating Layer A — reliability failures are almost entirely Layer C. The pack's `default_layer_distribution` reflects this.
