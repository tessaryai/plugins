# examples/

Reference inputs that show synthesize-graders what a well-formed trace file looks like.

## `sample_traces.jsonl`

A minimal but complete JSONL file of OpenTelemetry GenAI spans, following the [OTel GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). One span per line. The file demonstrates **both** shapes the ingestion logic in `SKILL.md` step 1 (Path A) accepts:

1. **Messages-as-attributes** (newer semconv) — spans 1, 2, 5 carry the full conversation under `gen_ai.input.messages` / `gen_ai.output.messages` as JSON-encoded arrays of `{role, parts}` objects.
2. **Messages-as-events** (earlier semconv, still common in instrumentation libraries) — spans 3 and 4 carry the conversation as span events named `gen_ai.system.message`, `gen_ai.user.message`, and `gen_ai.choice`. Each event has a `content` (or `message`) attribute.

The file also covers the structural cases synthesize-graders cares about:

- **Two distinct logical call sites** — a docs Q&A answerer (spans 1, 2, 5) and a support-ticket classifier (spans 3, 4). They are grouped by the normalized hash of their system prompt, so all three docs-QA spans collapse to one call site with `sample_count: 3`, and the two classifier spans collapse to one with `sample_count: 2`.
- **A chain** — spans 1 and 2 share `trace_id` `0x4bf92f3577b34da6a3ce929d0e0e4736`, with span 2's `parent_id` pointing at span 1. Step 4.5 should detect this as a trace-confirmed chain (retrieval-planner → grounded-answerer).
- **Required attributes per span** — `gen_ai.system`, `gen_ai.operation.name`, `gen_ai.request.model`. `gen_ai.response.model` and token-usage attributes are included where available but are not required for call-site discovery.

## Trying it

From a target repo, point the skill at this file as the traces input:

```
/evals:synthesize-graders --traces /path/to/evals/examples/sample_traces.jsonl
```

You should see step 1 print two call sites and step 4.5 detect one chain.

## Producing your own

Anything that emits OTel GenAI spans to a file works — for example, an OTel SDK with `ConsoleSpanExporter` writing to a file, or an OTLP/JSON file exporter. Vendor SDKs that bridge to OTel (OpenLLMetry, OpenInference, the OTel-native instrumentations from Anthropic/OpenAI) all produce conforming output. Vendor-proprietary attributes (`langfuse.*`, `langsmith.*`, etc.) are ignored — only `gen_ai.*` is read.
