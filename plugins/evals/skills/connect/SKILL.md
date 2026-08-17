---
name: connect
description: Connect this repo to your evals.tessary.ai project and wire the platform's tools into Claude Code, so you can assess call sites, inspect graders, query failing traces, and read the cases and root-cause reports it has opened, natively. Use when the user says "connect to evals", "link this repo to Tessary", "connect to evals.tessary.ai", "set up the evals platform", or invokes /evals:connect.
---

# connect — link this repo to evals.tessary.ai and load its tools

This is the **front door** to the Tessary evals platform for a coding agent. It does four
things and then gets out of the way:

1. **Link** this repo to a project (a one-time device-code handshake in the browser).
2. **Detect** whether this repo already emits OpenTelemetry and, if so, **wire its OTLP export**
   to the project (point it at `POST /v1/traces` with the link token). OTLP is the only supported
   ingestion path. This is the "detect the setup in the project and wire it to tessary" step.
3. **Register** the platform's authenticated MCP server into Claude Code (privately, per-repo)
   so *you* — the coding agent — get native tools. **Every one of them reads; there is no write,
   nothing that spends, and nothing that starts an agent run.** Roughly: `get_project` (what this
   token is bound to, plus whether anything is arriving at all), `list_cases` / `get_case` (what is
   wrong right now — and `get_case` carries the root-cause report inline once one has finished),
   `list_findings` / `get_finding` (classifier drift), `list_call_sites` / `list_failure_modes` /
   `list_quality_dimensions` (the imported taxonomy), `list_traces` / `get_trace`, `list_spans` /
   `get_span`, `list_sessions` / `get_session` (find the traffic, then read it — the `get_*` half is
   where the raw conversation text lives), `describe_dataset` plus `query_count` /
   `query_timeseries` / `query_facets` / `query_search` (aggregates over tool calls, classifier
   events and usage rollups), and `list_graders` / `get_grader` where the org holds the graders
   capability.

   **Do not treat that as a fixed list — read `tools/list` and report what it actually
   returns.** That instruction is the durable part of this step; the paragraph above it is a hint
   about shape and it will drift again. Every tool declares a capability the org must hold to be
   offered it, so the real catalogue is per-token and shorter for most projects; a tool the org does
   not hold reads as an unknown tool, not a permission error. Naming tools from memory is how this
   skill spent two releases telling the agent to call a tool that had become a no-op while never
   mentioning `get_span` / `get_trace` — and then, one release later, still named five triage and RCA
   tools the platform had deleted. Twice now the prose was wrong and `tools/list` was right.

   **If the user asks for something no offered tool answers, say so — do not reach for a name you
   remember.** Concretely: starting a triage run and editing a grader are not tools, by design.
   Those are platform UI actions; your part is to read the result afterwards (a finished report
   arrives inline on `get_case`).
4. **Report** what's in the project so the user knows what they can do next.

After this, the user assesses call sites by *talking to you* — you call the platform tools
directly. No local synthesis pipeline, no Python per read. The `.tessary/` bundle itself is
**authored and maintained by the platform's observer**: once tagged traffic is flowing and the
repo is connected on the platform (Settings → Git integration), the observer reads the code on the org's
schedule and proposes the bundle — call sites, failure modes, grader definitions — as a draft
PR the user reviews and merges. There is no local bootstrap step anymore.

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

`platform.py` is the whole client — device-link, TLS, credentials, status and coverage in one
stdlib-only file. The stored token is keyed by repo root (link once, use everywhere).

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
- **No project yet (new account)** → connect links a repo to an *existing* project. The browser
  flow lets the user create one during confirmation, so tell them: "pick a project — or create one
  — on the confirmation screen." A brand-new project starts empty; graders arrive via the
  platform's observer once traffic flows (see "How graders come to exist" below).
- **Headless / no browser** (SSH, CI) → it prints the URL + code for the user to open elsewhere,
  then polls (resilient to transient blips, up to ~10 min). Relay the URL and code, say you're
  waiting for their confirmation, and end your turn — don't spin.
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
link token (an OTLP ingest header). Resolve the base URL **locally** (no network call, no token
printed):

```bash
BASE="$(PYTHONPATH="$PLUGIN" python3 - <<'PY'
import platform as p  # the plugin's platform.py (via PYTHONPATH), not the stdlib module
from pathlib import Path
proj = p.linked_project(Path('.').resolve() / '.tessary') or {}
print(proj.get('base_url') or p.DEFAULT_BASE_URL)
PY
)"
echo "OTLP endpoint:  $BASE/v1/traces"
echo "OTLP headers:   Authorization=Bearer <your link token>   # the USER runs: platform.py token --reveal (keep it out of the chat)"
```

The greps above are a **heuristic, not a verdict** — a config-driven OTel setup or GenAI-only
instrumentation can hide from a keyword search, and commented/dead code can false-positive. **State
your classification and how confident you are, and confirm with the user before proposing any
`.env`/config edit.** Wiring means editing OTLP config/env — propose it as a concrete change and let
the user apply it; never write the raw token into a committed file, and **never fetch or echo the
token yourself** — the user runs `platform.py token --reveal` and pastes it into their own `.env`.

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
refreshes the token: it **first checks `claude` is on PATH**, then removes any prior registration and
re-adds, so a PATH problem never leaves the repo with zero tools.

If the `claude` CLI isn't on PATH, `mcp-add --run` **fails fast without touching any existing
registration** and tells the user to fix PATH (usually a version-manager shim or devcontainer) and
re-run `/evals:connect`. Do **not** have the user hand-assemble the `claude mcp add` command with a
raw token — that leaks it into shell history. (`python3 "$PLUGIN/platform.py" mcp-add` without `--run`
prints only a masked, non-runnable preview.)

### 4 — Report project state

```bash
python3 "$PLUGIN/platform.py" status
```

Prints the linked `<org>/<project>` and counts of call sites / graders / failure modes / quality
dimensions. Relay it. If the pipeline is empty/unavailable (a brand-new project), say so plainly —
"this project has no graders yet" — and explain how they arrive: tag the call sites
(`/evals:instrument`), exercise the app so tagged traffic flows, and connect the repo on the
platform (Settings → Git integration); the platform's observer then authors the starter bundle as a draft PR
to review and merge. No local generation step.

Then check whether any telemetry is actually bound to a call site:

```bash
python3 "$PLUGIN/platform.py" envs
```

Each `env` line carries the environment's tagged-span count and distinct call sites. If every
environment reads `0 0`, nothing in this repo is instrumented yet: spans may be arriving, but none
carry the `tessary.call_site.id` tag, so they are invisible to every call-site-scoped feature. Say
so and point the user at **`/evals:instrument`**, which tags the call sites in their code. Do not
treat this as a failure of `connect` — it is the expected state of a freshly-linked repo, and it is
the next step.

### 5 — Hand off

**The MCP tools are NOT usable this turn** — they load only after the client reloads its MCP config.
The hand-off must lead and close with that. Do not claim the tools work now; if the user asks you to
use them immediately, remind them to reconnect first. Print something like:

```
Connected to <org>/<project>. ✅

⚠️ Reconnect (or restart) this session once so the Tessary tools load — they are not available yet.

After you reconnect, just ask me things like:
  • "assess my call sites"            → I list them and flag gaps/risks
  • "what's failing this week?"       → I query real spans + classifier events
  • "run triage on <failure mode>"    → I trace a failure to its root cause
  • "show the grader for <call site>" → I pull its definition and recent verdicts

(These use the Tessary tools, so they only work after you reconnect.)
```

## How graders come to exist

There is no local generation step. The full path, in order:

1. **`/evals:connect`** (this skill) — link, wire OTLP, register the MCP tools.
2. **`/evals:instrument`** — stamp `tessary.call_site.id` onto the repo's LLM call spans, then
   exercise the app so tagged traffic reaches the platform. Call sites materialize from real
   spans; nothing is inferred from code alone.
3. **Connect the repo on the platform** (Settings → Git integration — the GitHub App). This is what lets the
   platform read the code and open PRs against it.
4. **The platform's observer does the rest**, on the org's schedule: it reads the repo, authors
   the `.tessary/` bundle — call-site shards, code-tracked facts, failure modes, grader
   definitions — and proposes it as a **draft PR**. The user reviews and merges; the merge imports
   the bundle. The same loop keeps the bundle current as the code changes, and the user can always
   edit `.tessary/` directly — the repo is the source of truth.
5. **Generate the verdict bodies.** Imported graders are definitions with `_body_source: platform`
   and no body yet — they cannot grade until the user triggers **Generate** on the project's
   Pipeline page, which authors each body from real traces. This is deliberately manual (it incurs
   LLM spend), so when you relay the hand-off, say it explicitly: "after you merge the bundle PR,
   hit Generate on the Pipeline page to bring the graders to life."

If `status` shows an empty pipeline, the answer is always a missing step in that chain — usually
step 2 (nothing tagged yet) or step 3 (repo not connected on the platform).

## Constraints

- **Confirm the target repo** before linking if the cwd is ambiguous — the credential is keyed by
  repo root.
- **Never print the raw token.** `platform.py mcp-add` (without `--run`) masks it; `platform.py token`
  now refuses unless given `--reveal`, and even then it is the *user's* action for their own `.env` —
  never run `token --reveal` on the user's behalf or echo the value into the chat.
- **To disconnect a repo**, use `python3 "$PLUGIN/platform.py" unlink` — it tears down both the local
  MCP registration and the stored credential together. (The server-side token still needs revoking in
  the platform UI.)
- **The link is user-consented, per-session, per-project.** Do not re-link a different project
  without the user asking. One confirmation in the browser authorizes one project.
- **Assessing call sites needs no new skill** — once connected, you list and evaluate them with the
  registered MCP tools (`list_call_sites` + `query_*` + `list_traces`/`list_spans` to find the
  traffic + `get_span`/`get_trace` for the raw text) directly. For "what is actually wrong with this
  project", start at `list_cases` rather than reconstructing it from aggregates.
- **Read `get_project`'s `watching` block before calling an empty case list an all-clear.** It
  reports how many classifiers are enabled, how many call sites they sweep, and how many traces
  arrived in the last 24h. `traces_last_day: 0` means nothing is *arriving* — a different answer from
  nothing being wrong, and the one that routes to `/evals:instrument`.
- **The MCP surface writes nothing.** Creating a call site reaches the platform through `import`;
  editing a grader, resolving a case and starting a triage run are UI actions. Each records a human
  judgement or spends the platform's money, so none of them is a tool — do not look for one.
