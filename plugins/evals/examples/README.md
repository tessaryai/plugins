# examples/

Reference showing what a **well-instrumented** GenAI span looks like — the shape the platform needs
in order to bind telemetry to a call site and ground graders in it.

## `sample_traces.jsonl`

Five OpenTelemetry GenAI spans, one per line, following the
[OTel GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

**Every span carries `tessary.call_site.id`.** That attribute is the whole ballgame: it is the only
thing the platform reads to answer *which call site is this?* — there is no filepath, span-name, or
prompt-shape inference. Strip it and these spans still ingest and still show up in the trace viewer,
but they resolve to `null` and grader synthesis cannot see them. Note the value is a **literal**, and
the key is **dotted** (`tessary.call_site.id`, never `tessary.call_site_id`).

The three ids across the five spans are what `/evals:instrument` would have written into the source:

| span | `tessary.call_site.id` |
| --- | --- |
| 1 | `docs.retrieval_planner` |
| 2, 5 | `docs.grounded_answerer` |
| 3, 4 | `support.ticket_classifier` |

The file also demonstrates **both** message shapes real instrumentation emits:

1. **Messages-as-attributes** (newer semconv) — spans 1, 2, 5 carry the conversation under
   `gen_ai.input.messages` / `gen_ai.output.messages` as JSON-encoded arrays of `{role, parts}`.
2. **Messages-as-events** (earlier semconv, still common) — spans 3 and 4 carry it as span events
   named `gen_ai.system.message`, `gen_ai.user.message`, `gen_ai.choice`, each with a `content`
   (or `message`) attribute.

And the structural cases the pipeline cares about:

- **Three call sites, grouped by tag, not by prompt.** Spans 2 and 5 collapse into one call site
  because they carry the same id — not because their system prompts hash alike.
- **A chain** — spans 1 and 2 share `trace_id` `0x4bf92f3577b34da6a3ce929d0e0e4736`, with span 2's
  `parent_id` pointing at span 1. Phase D detects this as a trace-confirmed chain
  (`docs.retrieval_planner` → `docs.grounded_answerer`).
- **Required attributes per span** — `gen_ai.system`, `gen_ai.operation.name`,
  `gen_ai.request.model`. `gen_ai.response.model` and token usage are included where available but
  are not required.

## Trying it

Traces reach the platform over **OTLP** (`POST /v1/traces`); there is no file-import path, and
`/evals:synthesize-graders` no longer accepts a local traces file. To exercise the flow, point your
app's OTLP exporter at your project (`/evals:connect` wires this), tag its call sites
(`/evals:instrument`), run it, then:

```bash
python3 platform.py envs                     # which envs have tagged spans
python3 platform.py coverage --env <slug>    # per-call-site span counts
```

Use this file as the reference for what your exporter should be producing — if your spans don't look
like these, `coverage` will report them under `untagged`.

## Producing your own

Anything that emits OTel GenAI spans works: an OTel SDK, OpenLLMetry, OpenInference, or the
OTel-native instrumentations from Anthropic/OpenAI. Vendor-proprietary attributes (`langfuse.*`,
`langsmith.*`) are ignored — only `gen_ai.*` and the `tessary.*` overlay are read.

The one thing no instrumentation library will add for you is `tessary.call_site.id`. It names a
boundary the library cannot see: *your* call site, not the LLM client call it wrapped. Set it
yourself — in code, or with an OTel Collector transform rule for telemetry you don't own.
