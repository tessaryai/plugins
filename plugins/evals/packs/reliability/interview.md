# reliability pack — interview

Skip every question that step 0 already answered or that the trace `observed.*` stats can answer.

## How to run

Same pre-fill protocol. **The reliability pack has the strongest pre-fill story** because `call_sites[].observed.{p50,p95}_latency_ms`, `cost_estimate_usd`, and `error_rate` answer most of the operational questions directly when traces are provided. If the run has no traces, fall back to user dialogue.

## Q1.synchronicity — Is the LLM call user-facing-synchronous, async, or batch?

**Pre-fill rules.** Look at surrounding code:
- The call site is invoked from an HTTP request handler (FastAPI, Flask, Express, Next.js route) → synchronous.
- The call site is invoked from a Celery / RQ / Sidekiq / Cloud Run job / cron handler → async.
- The call site is invoked from a batch script or notebook → batch.

If multiple call sites have different answers: ask per call site (or accept the user's blanket policy).

**Question (when ambiguous).**

> "For each call site (or as a blanket policy): is the LLM call synchronous user-facing (user is waiting), async (user-triggered but completes in the background), or batch (no user waiting)?"

**Why it matters.** Determines whether latency regressions are user-visible. A 30s p95 on a sync call is a hair-on-fire bug; on a batch job it's fine.

## Q2.latency_budget — What is the p50 / p95 latency budget?

**Pre-fill rules.** When `call_sites[].observed.p95_latency_ms` is present, propose `current_p95 × 1.2` as a soft budget and confirm. The 1.2 factor leaves headroom for natural variance without being a guarantee. If `observed` is absent: ask.

**Question (only when no observed data).**

> "What's the latency budget for this LLM call? Provide p50 and p95 targets in milliseconds. Common anchors: in-product chat = 2s p50 / 5s p95; email draft = 5s p50 / 15s p95; async = 30s p95; batch = no budget."

**Why it matters.** Anchors Layer C `latency_regression` failures. Without a budget, the grader can't make a verdict.

## Q3.cost_ceiling — What is the cost ceiling per call?

**Pre-fill rules.** When `observed.cost_estimate_usd` and `sample_count` are present, propose `current_avg × 1.5` as a soft ceiling. If `observed` is absent: ask.

**Question (only when no observed data).**

> "What's the cost ceiling per call in USD? Common anchors: cheap classification = $0.001; mid-weight summarization = $0.01; long-context RAG with citations = $0.05. Or pass if you'd rather budget at the run level (`runtime.budget_usd_per_run` in pipeline.yaml)."

**Why it matters.** Anchors `cost_regression` failures. Output verbosity blowing the budget is a high-severity Layer C issue in production.

## Q4.variance_tolerance — How much output variance is acceptable across re-runs?

**Pre-fill rules.** No code signal — always ask. But infer a default:
- Output shape is `classify` or `extract` (deterministic-ish): default `low_variance`.
- Output shape is `draft`, `summarize`, `conversational_turn`: default `high_variance`.
- Output shape is `route` or `tool_call` (gates downstream): default `low_variance`.

Confirm the default.

**Question.**

> "How much variance is acceptable when the same input is run twice at temperature 0? Options: none (output must be byte-identical), semantically-equivalent (different wording is fine, different decisions are not), free (variance is acceptable as long as quality bar is met). Most classify/route/tool_call should be 'semantically-equivalent'; drafts/summaries are typically 'free'."

**Why it matters.** Drives `output_variance` (non-determinism) failures. Skip the variance grader category when the answer is "free".

## Q5.fallback — What happens when the LLM call fails?

**Pre-fill rules.** Inspect call-site surrounding code for `try/except`, `.catch`, fallback constants, default responses, circuit-breaker patterns. If a fallback is visible: confirm. Otherwise: ask.

**Question (when ambiguous).**

> "When the LLM call fails (timeout, refusal, content-filter trip, transient error), what does the product do? Options: hard fail (surface error to user), silent fallback (return a constant or rule-based answer; user doesn't know), retry (with backoff), degrade (return a thinner answer)."

**Why it matters.** A silent-fallback design needs `refusal_rate` and `error_rate` graders specifically — production breakage is invisible without them.

## Output

```yaml
packs:
  - id: reliability
    interview_answers:
      synchronicity: {answer: synchronous, source: product_profile, evidence: "src/api/routes.py: handler"}
      latency_budget: {answer: {p50_ms: 1800, p95_ms: 4400}, source: observed, evidence: "call_sites[*].observed.p95_latency_ms"}
      cost_ceiling: {answer: 0.018, source: observed}
      variance_tolerance: {answer: free, source: user}
      fallback: {answer: silent_fallback, source: code}
```
