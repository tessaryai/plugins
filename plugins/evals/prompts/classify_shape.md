You are classifying the *shape* of work each LLM call site in the target repo performs. Shape determines which baseline grader templates apply downstream and which failure modes are likely.

For each call site, choose exactly one shape from:

### Generation shapes (the bulk of LLM calls)

- `summarize` — condense input into a shorter form (meeting summary, doc summary, thread summary, etc.).
- `extract` — pull structured data out of unstructured text (entities, fields, JSON from a doc).
- `rag_answer` — answer a question grounded in retrieved documents; citations expected.
- `classify` — assign a label or category to input.
- `draft` — produce a long-form artifact for the user to edit (email draft, PRD section, code comment).
- `route` — decide which downstream tool, branch, or path to take.
- `tool_call` — invoke external tools/functions; success measured by correct tool + args.
- `agent_step` — one step inside a multi-step agent loop; success measured against trajectory.
- `conversational_turn` — multi-turn dialog where context across turns matters.

### Retrieval / safety shapes (added in v0.2 to model RAG and safety chains end-to-end)

- `embedding` — turn text into a vector for similarity search. No textual output; failures are upstream (input chunking, model choice). Usually no judge grader; surface only cost/latency/error-rate observability.
- `rerank` — reorder candidate passages by query relevance. Output is a ranked list. Failures: top-k precision, position bias, monotonicity (relevance score consistent with rank).
- `guardrail` — a pre- or post-call check that blocks/allows content (e.g. a safety classifier wrapping a primary LLM call). Failures: false positives (over-blocks benign content), false negatives (lets harmful content through), latency tail.
- `moderation` — provider-side moderation API call (OpenAI Moderations, Azure Content Safety, etc.). Treat like `guardrail` but separately so the failure mode catalog can differentiate vendor moderation drift from custom guardrail drift.
- `ensemble_vote` — N parallel sibling LLM calls with the same prompt (self-consistency, ensemble voting). Failures: ensemble disagreement masked (chosen output silently overrides majority), majority-wrong-but-confident. Pairs with the `ensemble` chain detection method.

### Catch-all

- `other` — none of the above.

Confidence levels:
- `high` — the prompt and surrounding code make the shape obvious.
- `medium` — the shape is the most likely interpretation but other shapes are plausible.
- `low` — the call site is ambiguous; flag for manual review.

## Disambiguation rules (run in this order)

1. A "summarize" that produces a JSON object with structured fields is `extract`, not `summarize`.
2. A "draft an answer" that is grounded in retrieved docs with citations is `rag_answer`, not `draft`.
3. A call site whose only output is a numeric vector or `list[float]` is `embedding`, not `extract`.
4. A call site that orders/scores candidates and emits a sorted list is `rerank`, not `classify`.
5. A safety classifier that runs before/after a primary call to gate it is `guardrail`, not `classify`.
6. Multiple identical sibling spans in a trace (same prompt, same `parent_id`, runtime decides among them) are `ensemble_vote`, not `agent_step`.
7. A vendor moderation API call (OpenAI/Azure/Anthropic-provided) is `moderation`, not `guardrail`.
