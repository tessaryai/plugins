# evals

A Claude Code plugin that connects your repo to [evals.tessary.ai](https://evals.tessary.ai) and lets
you work with your evals **from the coding agent** — assess call sites, inspect graders, query
failing traces, and run triage, all as native tools. When you have no evals yet, it can bootstrap a
calibrated starter suite straight from your code.

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
> → exercise your app → [`/evals:synthesize-graders`](#bootstrap-a-starter-suite-greenfield). Grader
> generation reads your project's real traces, so it needs a link and tagged telemetry before it can
> produce anything worth running.

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

Run your app and traces appear in the project — ready to `assess`, or to calibrate graders against.
If your app has no OpenTelemetry yet, follow the project's **Connect traces** step for the setup
guide; any OpenTelemetry-capable emitter works.

## Bind your call sites (`/evals:instrument`)

Traces arriving is not the same as traces being *usable*. The eval machinery is call-site-keyed, and
the platform learns a span's call site from exactly one thing — the explicit **`tessary.call_site.id`**
span attribute. There is no filepath or span-name inference: an untagged span ingests fully, shows up
in the trace viewer, and is **invisible to grader generation**.

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

## Bootstrap a starter suite (greenfield)

If the repo has **no evals at all** and you want a full starter suite — graders, datasets, and a
self-contained visual report — run the heavier bootstrap:

```
/evals:synthesize-graders --env prod
```

It **requires a linked project with tagged telemetry**, and grades only the call sites your traces
actually exercised. A grader written from source alone is a guess about what your model does; one
written against real spans is a measurement. Call sites discovered in code but never observed are
dropped and listed in `.tessary/pipeline/skipped_sites.yaml` with a reason, so the gaps are visible
rather than silent.

`--skip-trace-grounding` waives the trace requirement (never the link). It warns loudly and stamps
every grader with `_meta.grounding: none`, because those graders are a starting point for human
editing, not an instrument.

The run synthesizes a `.tessary/` bundle locally, one call site at a time, with a preview after the
first site, and can publish it back with `--publish`. This is the one-time greenfield path;
**`/evals:connect` is the ongoing front door** once a project exists.

Everything the bootstrap produces lands in `.tessary/` in your repo:

| Path | What it is |
| --- | --- |
| `.tessary/index.html` | Self-contained visual report — open it in a browser, no server needed. |
| `.tessary/report.md` | Human-readable walkthrough of every grader. |
| `.tessary/graders/*.yaml` | One grader per failure mode. Run these on the platform against golden datasets. |
| `.tessary/datasets/*.jsonl` | Replayable input rows captured from the traces fetched for each call site. |
| `.tessary/pipeline/` | Call sites, failure modes, taxonomy. |
| `.tessary/pipeline/instrumentation.yaml` | `call_site_id` → file/line/method, written by `/evals:instrument`. |
| `.tessary/pipeline/skipped_sites.yaml` | Call sites found in code but **not** graded, and why (`not_instrumented`, `no_observed_traces`). |
| `.tessary/.cache/` | Traces fetched from the platform. Gitignore it; never uploaded. |

### Targeted regeneration

After a code change makes specific graders stale and you already know which ones:

```
/evals:regenerate-grader <grader_id|call_site_id|chain_id>
```

Re-authors just the named graders in place — no discovery, triage, or approval gates.

## Validating a bundle

```bash
python3 validate.py --bundle .tessary/
```

Runs every check on a generated bundle: failure-mode coverage, schema conformance, dedup uniqueness,
lock consistency.

## License

MIT — see `LICENSE`.
