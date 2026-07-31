# evals

A Claude Code plugin that connects your repo to [evals.tessary.ai](https://evals.tessary.ai) and lets
you work with your evals **from the coding agent** — assess call sites, inspect graders, query
failing traces, and run triage, all as native tools. Grader authoring itself lives on the platform:
its observer reads your repo, proposes the `.tessary/` eval bundle as a draft PR, and keeps it
current as your code changes.

## Install

In any Claude Code session:

```
/plugin marketplace add tessaryai/plugins
/plugin install evals@tessary
```

## Connect (start here)

```
/evals:connect
```

> **Start here, always.** The order is `/evals:connect` → [`/evals:instrument`](#bind-your-call-sites-evalsinstrument)
> → exercise your app → [connect the repo on the platform](#how-graders-come-to-exist). Grader
> authoring reads your project's real traces and your code, so it needs a link, tagged telemetry,
> and a readable repo before it can produce anything worth running.

This links the current repo to a project on evals.tessary.ai (a one-time device-code handshake in
your browser), then registers the platform's authenticated tools into Claude Code — privately, scoped
to this repo. After you reconnect the session, just ask the agent things like:

- **"assess my call sites"** — it lists them and flags gaps, risky calls, and missing coverage
- **"what's failing this week?"** — it queries real observations and verdicts
- **"run triage on `<failure mode>`"** — it traces a failure to its root cause
- **"show the grader for `<call site>`"** — it pulls the definition and recent verdicts

The link stores a project-scoped token under `~/.config/tessary-evals/credentials.json` and, because
the MCP server is registered at **local scope** (`~/.claude.json`), the token is never written into a
committed file. Reconnect once after connecting so the tools load. To disconnect a repo later, run
`python3 platform.py unlink` (removes the local registration + stored credential).

### What you get natively after connecting

The platform exposes these as MCP tools the agent calls directly — no local files, no Python per read:

| Tool | What it does |
| --- | --- |
| `list_call_sites`, `list_graders`, `list_failure_modes`, `list_quality_dimensions` | Inventory the project's pipeline |
| `get_grader`, `propose_grader_edit` | Read a grader's definition; propose a change |
| `query_count`, `query_search`, `query_facets`, `query_timeseries` | Query real observations, tool calls, feedback, and signal events |
| `run_triage`, `latest_triage`, `get_triage` | Trace a failure mode to its root cause |
| `reload_pipeline` | Refresh after an import |

## Make traces flow (OTLP)

Connecting only gives you *read* access — it's useful once traces are actually reaching your
project. **Ingestion is OpenTelemetry over OTLP** (`POST /v1/traces`) — there is no JSON upload,
and the plugin does not install any SDK. `/evals:connect` detects whether your repo already emits
OpenTelemetry and, if so, wires its export to the project.

If your app already emits OpenTelemetry, point its OTLP exporter at your project with the standard
env vars (the token comes from the device link, kept out of version control):

```
OTEL_EXPORTER_OTLP_ENDPOINT=https://evals.tessary.ai
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <your link token>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

Run your app and traces appear in the project — ready to assess, or to author graders against.
If your app has no OpenTelemetry yet, follow the project's **Connect traces** step for the setup
guide; any OpenTelemetry-capable emitter works.

## Bind your call sites (`/evals:instrument`)

Traces arriving is not the same as traces being *usable*. The eval machinery is call-site-keyed, and
the platform learns a span's call site from exactly one thing — the explicit **`tessary.call_site.id`**
span attribute. There is no filepath or span-name inference: an untagged span ingests fully, shows up
in the trace viewer, and is **invisible to every call-site-scoped feature**.

```
/evals:instrument
```

finds the LLM call sites in your repo, gives each a stable id, and writes that id into your code as a
span attribute (showing you the diff first). The tagged call sites then materialize themselves in the
project the first time a tagged span arrives — no upload required.

Check what landed:

```
python3 platform.py envs                     # tagged spans + call sites, per environment
python3 platform.py coverage --env prod      # per-call-site counts, plus the untagged residue
```

## How graders come to exist

There is no local generation step. Once the three preconditions hold —

1. the repo is **linked** (`/evals:connect`),
2. its call sites are **tagged and producing traffic** (`/evals:instrument`, then exercise the app),
3. the repo is **connected on the platform** (Settings → Git integration — the GitHub App),

— the platform's **observer** authors the eval bundle for you, on your org's schedule: it reads the
code, writes the `.tessary/` bundle (call-site shards, code-tracked facts like output schemas and
tool declarations, failure modes, quality dimensions, grader definitions), and opens a **draft PR**
against your repo. You review and merge; the merge imports the bundle into the platform. The
imported graders are definitions without verdict bodies yet — generate the bodies from real traces
with the **Generate** action on the project's Pipeline page (a deliberate, spend-incurring step, so
it is yours to trigger, not automatic). The same loop keeps the bundle current as your code
changes — every update arrives as a PR, never a silent write.

The `.tessary/` directory in your repo is the **source of truth**: you can edit any of it directly
(adjust a grader's gate, retire a failure mode, fix a description) and the platform imports your
version on push. The bundle's format is documented in [`output_format.md`](output_format.md); grader
authoring rules live in [`contract/AUTHORING_CONTRACT.md`](contract/AUTHORING_CONTRACT.md).

## License

MIT — see `LICENSE`.
