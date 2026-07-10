---
name: instrument
description: Stamp `tessary.call_site.id` onto the spans your LLM calls already emit, so production telemetry binds to the call sites graders are keyed on. Run after /evals:connect and before /evals:synthesize-graders. Use when the user says "instrument my call sites", "tag call sites", "why are my traces unassigned", "my call sites are empty", or invokes /evals:instrument.
---

# instrument — bind this repo's LLM calls to call sites

The eval machinery is **call-site-keyed**: graders bind to call sites, synthesis grounds per call
site, the observer reasons per call site. So an ingested span must answer *which call site am I?*

The platform answers that from exactly one thing — the explicit **`tessary.call_site.id`** span
attribute. There is no filepath, span-name, or prompt-shape inference. An untagged span ingests
fully and is visible in the trace viewer, but it is **invisible to grader generation**: it resolves
to `null` and every call-site-scoped feature skips it. Explicit-or-nothing, deliberately — guessing
mis-attributes production traffic against an authoritative source.

This skill closes that gap: discover the repo's LLM call sites, give each a stable id, and write
that id into the code as a span attribute. Afterwards the tagged call sites **materialize
themselves** in the project the first time a tagged span arrives — no upload, no `.tessary/`
bundle, no pipeline import.

## What this skill changes

It **edits source files**. That is the point, and it is the only skill here that does. Every edit
is shown as a diff and confirmed before it is written. It never touches prompt text, model
parameters, or control flow — it adds one attribute to a span that already exists, or wraps a call
in a span when none does.

## Prerequisites

- The repo is linked (`/evals:connect`). Tagging without a project to send spans to is busywork.
- The repo emits OpenTelemetry, or can. `/evals:connect` step 2 wires the OTLP export.

**OTLP is the only supported ingestion path, and this skill installs no SDK.** The tag is a plain
OpenTelemetry span attribute; it needs nothing beyond the tracer the repo already has. Never propose
adding a client library to make tagging work.

## Resolve the plugin path once

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*/evals/skills/instrument/*' 2>/dev/null \
  | xargs -I{} dirname {} | xargs -I{} dirname {} | xargs -I{} dirname {} \
  | sort -V | tail -1)}"
echo "PLUGIN=$PLUGIN"
```

## Flow

### 1 — Require a link

```bash
python3 "$PLUGIN/platform.py" status
```

Exit `1` means the repo isn't linked. **Stop** and tell the user to run `/evals:connect` first.
Do not proceed to edit their code for a project that doesn't exist.

### 2 — Read the existing instrumentation manifest

If `.tessary/pipeline/instrumentation.yaml` exists, load it first. It is the record of what this
skill has already tagged:

```yaml
version: 1
call_sites:
  support.answer:
    file: src/support/answer.py
    line: 84
    method: otel_attribute      # otel_attribute | wrapped_span
    tagged_at: "2026-07-10T09:14:02Z"

  support.legacy_reply:
    file: src/support/legacy.py
    line: 12
    state: stale                # the tag is still in the code, but the code path is gone (§2)
    tagged_at: "2026-06-02T11:00:00Z"

  billing.dunning_notice:
    file: src/billing/dunning.py
    line: 51
    state: skipped              # proposed and declined; do not re-propose (§5)
    reason: user_declined
```

An entry carries `state` only when it is *not* a live tag: omit it for the normal case. `stale` and
`skipped` entries are never deleted — a `stale` id may still be arriving on production spans, and a
`skipped` one records a decision, so removing either would make the next run re-litigate it.

**An id in this file is frozen.** Re-running must never rename an existing call site: the id is a
foreign key held by every grader, every failure mode, and every already-ingested span. Renaming
`support.answer` orphans all of them silently. If a tagged call site has moved file or line,
update `file`/`line` and leave `id` alone. If its code is gone, leave the entry, set `state: stale`,
and report it — do not delete it, because production spans carrying that id may still be arriving.

### 3 — Discover call sites

Dispatch a discovery subagent (`subagent_type: Explore`). This is the same static analysis
`synthesize-graders` Path B performs — an LLM call is **any place this repo causes a model to
run**, however the request leaves the process. Search all four invocation classes:

- **`sdk`** — in-process provider SDK / framework call: `messages.create`,
  `chat.completions.create`, `responses.create`, `generate_content`, `ai.generateText`/`streamText`,
  `langchain`/`langgraph`/`llamaindex`/`litellm` call objects.
- **`cli_agent`** — the repo shells out to an agent/LLM CLI: a process spawn
  (`subprocess.run`/`Popen`, `child_process.spawn`/`execa`, `sh -c`) whose argv names `claude`,
  `opencode`, `aider`, `codex`, `goose`, `llm`, `ollama run`, `gemini`, `sgpt`, `mods`.
- **`http`** — raw HTTP to a model endpoint: `requests`/`httpx`/`fetch`/`axios` against
  `api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com`, `*.bedrock.*`,
  a model path (`/v1/messages`, `/v1/chat/completions`, `/api/generate`), or a local gateway
  (`:11434`).
- **`sandbox_agent`** — an agent invoked inside a sandbox/remote-exec runner: `e2b`, `modal`,
  `daytona`, `Sandbox(...)`, `docker run`, whose command carries a prompt or a `cli_agent` binary.

**Split on runtime dispatch.** A call site is one *(intent, system prompt, output schema)*
combination, not one line of code. When a call location selects its prompt or schema from a
registry/map/enum keyed on a parameter, follow the dispatch and emit **one call site per branch** —
each gets its own tag. Do not over-split: parameters that only vary content (the user's text, a
temperature) are the same call site.

For each discovered site the subagent returns `{proposed_id, use_case, invocation, file, line,
enclosing_span}` where `enclosing_span` describes what OTel span, if any, already covers the call.

### 4 — Assign ids

`proposed_id` names what the call *produces*. Short, factual, no transport descriptors
(`streaming`, `async`, `cached`) and no rationale tails.

The platform treats the id as an opaque string, so pick the shape that reads best for the repo and
then hold it constant. A dotted namespace groups a feature's calls and is the convention worth
defaulting to — `support.answer`, `support.web.llm`, `currency.draft_answer` — with a flat
snake_case label (`checkout_summarizer`) fine for a repo with a handful of sites. **Do not mix both
shapes in one project**; the id is what a human scans in the Pipeline view.

This id is the **canonical `call_site_id` everywhere downstream**: in the code, on the span, on the
materialized `call_site` row, on every grader bound to it. Choose it once and never churn it.

Collisions with an existing manifest entry that points at *different* code are a hard error — ask
the user to disambiguate rather than silently reusing an id.

### 5 — Write the tag

Show the user a **single consolidated diff** of every proposed edit, then confirm before writing.
Pick the method by what the call site already has:

**`otel_attribute`** — an OTel span already wraps the call. Set the attribute on it:

```python
span.set_attribute("tessary.call_site.id", "support.answer")
```

```typescript
span.setAttribute("tessary.call_site.id", "support.answer");
```

**`wrapped_span`** — no span covers the call. Open one around it, using the tracer the repo
already configures (never construct a second `TracerProvider`):

```python
with tracer.start_as_current_span("support_answer") as span:
    span.set_attribute("tessary.call_site.id", "support.answer")
    ...
```

Rules that are not negotiable:

- **The attribute key is `tessary.call_site.id`, dotted.** It roots the expandable
  `tessary.call_site.*` namespace and is the only spelling the platform reads. An underscore
  variant (`tessary.call_site_id`) is silently ignored — the span will look tagged and resolve to
  `null`.
- **The value is a literal**, never an f-string, variable, or enum lookup. A tag computed at
  runtime cannot be statically correlated back to code, and a refactor can change it without
  anyone noticing.
- **Tag the span that covers the model call**, not a parent request/handler span. A handler that
  makes three different LLM calls is three call sites, and one tag on the handler collapses them.
- Do not add a tag to a call site the user declines. Record the decline in the manifest as
  `state: skipped` / `reason: user_declined` (§2) so the next run doesn't re-propose it.

For `cli_agent` / `http` / `sandbox_agent` sites there is often no span at all — these need
`wrapped_span`. They are frequently the **highest-risk** calls precisely because they run
un-prompted and un-schema'd, so do not skip them for being awkward to instrument.

### 6 — Write the manifest

Write `.tessary/pipeline/instrumentation.yaml` with an entry per tagged call site (§2 shape).
This file is the handshake with `synthesize-graders`: it is how the generator knows which
statically-discovered call sites are *supposed* to have telemetry, and therefore which missing
traces are a real gap rather than dead code.

Commit it. Also make sure the repo ignores the fetch cache, which `synthesize-graders` fills with
traces pulled back down from the platform:

```bash
grep -qxF '.tessary/.cache/' .gitignore 2>/dev/null || echo '.tessary/.cache/' >> .gitignore
```

### 7 — Hand off

Tell the user, plainly:

1. What was tagged, and what was skipped and why.
2. **Exercise the app.** A tag only becomes telemetry when the code runs. Nothing appears in the
   project until a tagged span is exported — running the test suite is usually enough.
3. Then check it landed:

   ```bash
   python3 "$PLUGIN/platform.py" envs
   ```

   Each environment prints its tagged-span count and distinct call sites. A row reading `0 0`
   means no tagged span has arrived in that env yet.

4. Then run `/evals:synthesize-graders`, which will refuse to generate for any call site with no
   observed traces.

## When traces arrive but stay untagged

`platform.py coverage --env <slug>` prints an `untagged` line. A large untagged count next to zero
call sites means spans are reaching the platform but carrying no tag. In order of likelihood:

- The attribute is spelled `tessary.call_site_id` (underscore). It must be dotted.
- The tag is set on a span that is never exported (a non-recording span, or one created from a
  different `TracerProvider` than the one wired to OTLP).
- The value is empty or whitespace — the platform treats a blank tag as absent.
- The app didn't reload after the edit.

## Telemetry you cannot edit

If the spans come from a third-party app or an instrumentor you don't own, you cannot add the
attribute at the source. The tag is a plain span attribute, so an OTel **Collector** transform rule
can stamp it fleet-wide instead:

```yaml
processors:
  transform:
    trace_statements:
      - context: span
        statements:
          - set(attributes["tessary.call_site.id"], "support.answer")
            where attributes["gen_ai.request.model"] != nil and name == "support_answer"
```

This is a documented workaround, not a supported inference path — you are still naming the call
site explicitly, just one layer out. Everything else in this plugin behaves identically.
