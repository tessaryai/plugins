---
name: connect
description: Connect this repo to your evals.tessary.ai project and wire the platform's tools into Claude Code, so you can assess call sites, inspect graders, query failing traces, and run triage natively. Use when the user says "connect to evals", "link this repo to Tessary", "connect to evals.tessary.ai", "set up the evals platform", or invokes /evals:connect.
---

# connect — link this repo to evals.tessary.ai and load its tools

This is the **front door** to the Tessary evals platform for a coding agent. It does four
things and then gets out of the way:

1. **Link** this repo to a project (a one-time device-code handshake in the browser).
2. **Detect** whether this repo already emits OpenTelemetry and, if so, **wire its OTLP export**
   to the project (point it at `POST /v1/traces` with the link token). OTLP is the only supported
   ingestion path. This is the "detect the setup in the project and wire it to tessary" step.
3. **Register** the platform's authenticated MCP server into Claude Code (privately, per-repo)
   so *you* — the coding agent — get native tools:
   `list_call_sites`, `list_graders`, `list_failure_modes`, `list_quality_dimensions`,
   `query_count` / `query_search` / `query_facets` / `query_timeseries` (over observations,
   tool calls, feedback, signal events), `run_triage` / `latest_triage` / `get_triage`,
   `get_grader`, `propose_grader_edit`, `reload_pipeline`.
4. **Report** what's in the project so the user knows what they can do next.

After this, the user assesses/creates call sites by *talking to you* — you call the platform
tools directly. No local synthesis pipeline, no `.tessary/` bundle, no Python per read. (The
heavier `/evals:synthesize-graders` bootstrap still exists for greenfield repos with no
project yet — see "When to bootstrap instead" below.)

## The only network egress

Two calls, both to the platform origin the user is linking to:
`POST /auth/link/start` + `/auth/link/poll` (the device handshake) and, after that, whatever
MCP tool calls *you* make once the server is registered. Nothing leaves the machine before the
user confirms the link in their signed-in browser.

## Resolve the plugin path once

All bundled scripts live in this plugin directory. Resolve it once at the start:

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*/evals/skills/connect/*' 2>/dev/null \
  | xargs -I{} dirname {} | xargs -I{} dirname {} | xargs -I{} dirname {} \
  | sort -V | tail -1)}"
echo "PLUGIN=$PLUGIN"
```

`platform.py` is the thin client; it reuses `publish.py`'s device-link/TLS/credentials plumbing,
so the stored token is shared with the synthesis path (link once, use everywhere).

## Flow

Run these from the **repo the user wants to connect** (default: the current working directory —
confirm it if ambiguous). Pass `--repo <path>` to `platform.py` to target a different root, and
`--base-url <url>` (or `EVALS_PLATFORM_URL`) only for a non-production platform.

### 1 — Link

```bash
python3 "$PLUGIN/platform.py" link
```

This prints a short code + URL and opens the browser. The user signs in (or signs up), picks the
org/project to link, and confirms. On success it stores a project-scoped **ADMIN** token under
`~/.config/tessary-evals/credentials.json` (chmod 600) and prints `Linked to <org>/<project>`.

- **Already linked** → the command is a no-op and prints the existing `<org>/<project>`; skip to
  step 3 (the MCP registration may still be missing).
- **Headless / no browser** (SSH, CI) → it prints the URL + code for the user to open elsewhere,
  then polls. Relay the URL and code and wait.
- **Declined / timed out** → report it plainly and stop; do not silently retry. The user can
  re-run `/evals:connect`.

### 2 — Detect observability & wire OTLP ingestion

Connect gives you *read* access to the project. It's only useful if traces are actually flowing
into it. **The only supported ingestion path is OTLP** — the platform accepts OpenTelemetry over
`POST /v1/traces`. So before registering tools, quickly detect whether this repo already emits
OpenTelemetry, then wire its OTLP export at the project:

```bash
# Does the repo already have an OpenTelemetry / OTLP setup?
grep -rInE "opentelemetry|OTEL_EXPORTER_OTLP|OTLPSpanExporter|TracerProvider|@opentelemetry/sdk" \
  --include=*.py --include=*.ts --include=*.js --include=*.toml --include=*.txt --include=*.env --include=package.json . 2>/dev/null | head
# Any LLM calls worth capturing?
grep -rInE "messages\.create|chat\.completions|generate_content|anthropic|openai|@ai-sdk|langchain|litellm" \
  --include=*.py --include=*.ts --include=*.js . 2>/dev/null | head
```

The OTLP export target for this project is the platform's receiver, authenticated with the stored
link token (an OTLP ingest header). Resolve them without printing the token:

```bash
BASE="$(python3 "$PLUGIN/platform.py" --repo . status >/dev/null 2>&1 && \
  python3 - <<'PY'
import publish; from pathlib import Path
p = publish.linked_project(Path('.').resolve()/'.tessary') or {}
print(p.get('base_url') or publish.DEFAULT_BASE_URL)
PY
)"
echo "OTLP endpoint:  $BASE/v1/traces"
echo "OTLP headers:   Authorization=Bearer <your link token>   # from: python3 \"$PLUGIN/platform.py\" token"
```

Classify what you find and act. **Wiring means editing OTLP config/env — propose it as a concrete
change and let the user apply it; never write the raw token into a committed file.**

- **OpenTelemetry / OTLP already set up** → point it at the project. The standard OTEL env vars do
  it with no code change:
  ```
  OTEL_EXPORTER_OTLP_ENDPOINT=<BASE>          # the OpenTelemetry SDK appends /v1/traces
  OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <link token>
  OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
  ```
  These are vanilla OpenTelemetry env vars — no tessary package or tessary-specific exporter is
  involved; the repo keeps whatever OTel SDK it already uses. Offer to add them to the repo's
  `.env` / process env (secret kept out of version control), or, if the exporter is constructed in
  code, to add a **second standard OTLP exporter pointing at `<BASE>/v1/traces`**. If another
  vendor OTLP backend (Langfuse/Phoenix/Arize) is present, add that second OTLP exporter alongside
  theirs rather than replacing it — just another OTLP endpoint, not a tessary library.
- **LLM calls but no OpenTelemetry at all** → there's nothing to point yet. Tell the user plainly:
  to get traces in, the app needs to emit OpenTelemetry GenAI spans over OTLP to `<BASE>/v1/traces`.
  Point them at the project's **Connect traces** step (URL printed in step 4) for the setup guide.
  Do **not** add an instrumentation library to their code in this flow.
- **no LLM code found** → note it; the user may be connecting to work with an existing project's
  data, not to emit new traces. Don't push ingestion setup.

> Ingestion is **OTLP only** (`POST /v1/traces`, protobuf). There is no JSON upload endpoint. Any
> OpenTelemetry-capable emitter works — the plugin does not install or require a specific SDK.

### 3 — Register the platform MCP server

```bash
python3 "$PLUGIN/platform.py" mcp-add --run
```

This runs `claude mcp add --transport http --scope local tessary-evals <base>/mcp` with the stored
token as an `Authorization: Bearer` header. **`local` scope** keeps the registration (and the
token) private to this repo in `~/.claude.json` — it is never written into a committed file. Re-running
refreshes the token idempotently (it removes any prior registration first).

If the `claude` CLI isn't on PATH, the command fails with a clear message; fall back to printing the
command for the user (`python3 "$PLUGIN/platform.py" mcp-add`, which masks the token) and let them run
it, or point them at their MCP settings.

### 4 — Report project state

```bash
python3 "$PLUGIN/platform.py" status
```

Prints the linked `<org>/<project>` and counts of call sites / graders / failure modes / quality
dimensions. Relay it. If the pipeline isn't available yet (a brand-new project with nothing
synthesized), say so and offer to bootstrap (below).

### 5 — Hand off

The MCP tools load on the **next** session/reconnect, not mid-turn. Tell the user exactly that,
then show what they can now ask you to do. Print something like:

```
Connected to <org>/<project>. I registered the Tessary tools with Claude Code — reconnect
(or restart this session) so they load. Then just ask me things like:
  • "assess my call sites"            → I list them and flag gaps/risks
  • "what's failing this week?"       → I query real observations + verdicts
  • "run triage on <failure mode>"    → I trace a failure to its root cause
  • "show the grader for <call site>" → I pull its definition and recent verdicts
  • "add a call site for <the LLM call in foo.py>"  → I register it on the platform
```

Do **not** claim the tools are usable in the current turn — they aren't until the client reloads
its MCP config. If the user asks you to use them immediately, remind them to reconnect first.

## When to bootstrap instead

`/evals:connect` assumes a project exists (or the user will create one during the link). If the
repo has **no evals at all** and the user wants a full starter suite generated from their code
(graders, datasets, a visual report), that's the heavier `/evals:synthesize-graders` bootstrap —
it synthesizes a `.tessary/` bundle locally and can publish it to a new project. Connect is the
lean, ongoing front door; synthesize is the one-time greenfield bootstrap. Offer synthesize only
when `status` shows an empty/absent pipeline and the user wants graders generated, not when they
just want to work with an existing project.

## Constraints

- **Confirm the target repo** before linking if the cwd is ambiguous — the credential is keyed by
  repo root.
- **Never print the raw token** in normal output. `platform.py mcp-add` (without `--run`) masks it;
  `platform.py token` prints it raw and is for scripting only — don't surface it to the user.
- **The link is user-consented, per-session, per-project.** Do not re-link a different project
  without the user asking. One confirmation in the browser authorizes one project.
- **Assessing call sites needs no new skill** — once connected, you list and evaluate them with the
  registered MCP tools (`list_call_sites` + `query_*` + `run_triage`) directly.
- **Creating a call site is a write** the platform exposes through `import` (there is no MCP create
  tool yet), so it goes through a separate import path — not this skill.
