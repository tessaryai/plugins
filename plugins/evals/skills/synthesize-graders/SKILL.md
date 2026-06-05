---
name: synthesize-graders
description: Generate a calibrated eval suite for an LLM product. Point it at the user's repo (with optional production traces) and it produces graders, datasets, and a visual report under `.tessary/`. Use when the user says "synthesize evals", "generate evals", "bootstrap evals for this repo", "create graders", or invokes /evals:synthesize-graders.
---

# synthesize-graders — synthesize an eval pipeline from a real codebase

You are running a phased synthesis pipeline against a target repo. The point of phasing is **time to first artifact**: a working `.tessary/index.html` appears after the first call site is graded, not after every call site is processed. The orchestrator processes one call site at a time. For each site it synthesizes graders for `severity: high` failure modes plus **all of that site's quality dimensions** (the grey-area 1–5 quality scores), and defers the medium/low failure-mode graders to an on-demand `--complete` flow. Deferred failure modes are still hypothesized and written to disk — they just don't get graders until the user asks. Quality dimensions are never deferred.

The orchestrator's job is to plan small fan-outs, run deterministic Python helpers, and read tiny return manifests — it never holds call-site bodies, failure-mode descriptions, taxonomy details, or grader bodies in context.

> **Mandatory stops — read before you start.** This skill MUST hand control back to the user after the first call site and again after the second. "Hand control back" means **end your turn**: print the status line and the gate prompt, then emit no more tool calls and no more output until the user replies. Do not process the whole `priorities.yaml` in one unattended turn — doing so silently consumes the entire session, which is the exact failure this skill is built to avoid. These two stops hold even if the user previously said "go fast" or "don't stop to ask"; an early human preview is the whole point. See Phase C.7 for the full gate. The only zero-gate path is `--complete all` on a run that has already been previewed.

Output goes to a directory in the **target repo's** working directory:

```
.tessary/
  pipeline/
    meta.yaml                         # version, product_hint, runtime, progress
    packs.yaml                        # engaged packs + interview answers
    priorities.yaml                   # ordered list of call_site_ids
    product_profile.yaml              # phase A
    invariants.yaml                   # implicit_invariants + invariant_coverage
    call_sites/<id>.yaml              # one per call site
    chains.yaml                       # all detected chains
    failure_modes/<call_site_id>.yaml # single_call failures per site
    failure_modes/_chains.yaml        # chain failures
    quality_dimensions/<call_site_id>.yaml # 1-5 quality axes per judgment site
    taxonomy.yaml                     # taxonomy tree (populated at end of phase C)
  graders/<grader_id_safe>.yaml       # one file per emitted (non-deferred) grader
  datasets/<call_site_id>.jsonl       # captured inputs (Path A only)
  report.md                           # human-readable walkthrough
  index.html                          # self-contained visual viewer
  .synth-lock.yaml                    # SHA-256 of every shard + grader
```

One grader per file is deliberate: emission failures are isolated (re-run one grader, not the whole batch), diffs are scoped to the grader that changed, and validation happens per file so a single malformed grader doesn't poison the pipeline. The same logic applies to the pipeline itself — sharded across per-artifact files so no single Write call carries the whole synthesis.

## Two grader families

The pipeline produces two complementary kinds of eval, and they must not be conflated:

- **Failure-mode graders** — binary `pass | fail` checks for a specific defect (`kind: llm_judge | deterministic | execution | agentic`). Hypothesized as **failure modes**. Subject to the deferral rule below.
- **Quality-dimension graders** — `kind: score` LLM-judges that assign a 1–5 level on an anchored rubric, tracked as a trend over time (never a gate). Hypothesized as **quality dimensions** (see `prompts/per_site_kit.md` § 4), required for judgment call sites. **Always graded in the first sweep — never deferred.** This is the grey-area "how good is the output" eval that black-and-white failure checks miss.

`kind: agentic` is a failure-mode grader whose verdict is produced by an agent running in a sandbox (via opencode) doing multi-turn analysis — running `git diff`, tests, or file exploration — rather than a single judge call. The plugin only **emits the `agent_spec`**; the runner (evals-platform) executes it. Use it for failures that can only be judged by inspecting the result the agent produced (did the repo end up correct?), typically on `sandbox_agent` / `cli_agent` call sites.

## Deferred failure modes

Every failure-mode entry carries a `grader_deferred: <bool>` field. The orchestrator sets it during phase C:

- `severity: high` → `grader_deferred: false` and a grader is synthesized this sweep.
- `severity: medium | low` → `grader_deferred: true` and `grader_id: null`; the failure is recorded but no grader is emitted yet.

Quality dimensions have no deferral flag — they are always graded. The user can flesh out the deferred *failure modes* later with `/evals:synthesize-graders --complete <call_site_id>` (or `--complete all`). The viewer renders deferred failures with a distinct "deferred" badge and the same hint string.

## Plugin path resolution

All bundled scripts (`validate.py`, `viewer.py`, `dedup.py`, `audit.py`,
`finalize.py`, `pipeline_io.py`) and the OSS fallback author live in this
plugin directory. **Resolve the plugin path once, at the start of the run,
and reuse it.** At the start of Phase A, do this via Bash:

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*synthesize-graders*' 2>/dev/null \
  | xargs -I{} dirname {} | xargs -I{} dirname {} | xargs -I{} dirname {} \
  | sort -V | tail -1)}"
echo "PLUGIN=$PLUGIN"   # surface the resolved version so a stale-cache mismatch is visible
```

Cache the result as `$PLUGIN`. **Never hardcode `.claude/skills/synthesize-graders/`** — that path is not stable across Claude Code plugin layouts.

## Two grader scopes

The pipeline produces graders in two distinct scopes that must remain cleanly separated:

- **`scope: single_call`** — grades one LLM call's output. Layer A (mechanical) and Layer B (judgmental) failures live here.
- **`scope: chain`** — grades a relationship across N **distinct** call-site outputs in the same logical session. Produced by Phase D; requires a runner that can fetch multiple outputs from one trace.
- **`scope: trace`** — grades the **final turn** of a multi-turn session at **one** call site, given the prior n-1 turns as context. Anchored to a `call_site_id` exactly like `single_call` (same id shape, same failure mode). Used for cross-turn coherence failures on `conversational_turn` / `agent_step` sites the orchestrator marked `default_grade_mode: per_conversation`. A repeated same-site conversation is a trace, **not** a chain. **Sourcing (v5):** the runner grades the latest turn per trace and reads the whole transcript from that turn's self-contained `input` — it does not stitch per-turn rows.

## Inputs

- **Repo path** (required) — local directory to analyze. If they don't give one, assume CWD and confirm.
- **Traces file** (optional) — JSONL of OpenTelemetry GenAI spans.
- **Product hint** (optional) — 1-2 sentences describing what the product does.
- **Pack selection** (optional) — `--pack <id>` / `--no-pack <id>`. Without flags, the triage phase auto-discovers from `applies_when` signals. `quality` is always-on.
- **Deep-grade** (optional) — `--complete <call_site_id>` flips that site's deferred medium/low failures to non-deferred and synthesizes their graders. `--complete all` does the same for every site in priority order, reusing the same adaptive approval gate.
- **Pause cadence** (optional) — `--pause-every N` overrides the adaptive gate; the orchestrator pauses after every N sites instead of using the measured per-site budget.
- **Publish** (optional) — `--publish` pre-consents to pushing the bundle to evals.tessary.ai so the user can run these graders on real traces. Without the flag the publish step is offered once at the site-1 gate (Phase C.7) and only runs if the user opts in. See "Publishing to the platform" below.

## Re-run safety

If `.tessary/` already exists in the target repo, load `.tessary/.synth-lock.yaml`
(if present) before doing anything else. The lock now records hashes for
*every shard* under `pipeline/` *and* every grader. Triage:

1. **Load locks.** For each grader file, verify its current SHA against the
   lock. Read `_meta.locked_fields`, `_meta.human_edited`, and `_body_source` per file.
   **Materialized/human bodies are frozen (v9).** If a grader's `_body_source` is
   `platform-materialized` or `human`, its verdict body (`judge_prompt`, and `rubric`
   for `llm_judge`) is **frozen** — never re-author or overwrite it. Carry the existing
   `judge_prompt`/`rubric` + `_body_source` + `_meta` (incl. `materialized_at` /
   `body_digest`) forward verbatim, even under `--force` (which may refresh
   orchestrator-owned fields like `id` / `dataset_refs` but must never touch a
   materialized body). These files land with `_meta.locked_fields: [judge_prompt, rubric]`
   (llm_judge) or `[judge_prompt]` (score), so the SHA-lock already tolerates their
   on-disk divergence. If `validate.py` reports a `body_digest` mismatch on a
   `platform-materialized` grader, a human edited it: promote it to `_body_source: human`
   and set `_meta.human_edited: true` (the platform's GitHub sync, or a curator, applies
   this) so the edit propagates upstream — do not regenerate the body.
2. **Decide the safe path.** Shards under `pipeline/` are orchestrator-owned;
   re-runs overwrite them. Grader files are the human-curatable surface:
   - No grader is `human_edited` and no grader diverges from the lock →
     proceed; carry `_meta.locked_fields` forward.
   - Any grader `human_edited: true` OR diverges without `locked_fields` →
     ask the user:
     1. **Respect locks (default)** — re-synthesize, preserve listed fields,
        skip `human_edited: true` files entirely.
     2. **Diff** — write to `.tessary.new/` instead. Treat that as the output
        directory throughout the run.
     3. **Force overwrite** — `--force`. Destructive; warn explicitly.
     4. **Cancel**.

### Resume from a prior run

When `.tessary/` is present from a previous (possibly interrupted) run, pick up where it left off rather than redoing finished work. The lock file at `.tessary/.synth-lock.yaml` records, per labeled unit of work, the files that unit produced and the SHA-256 of each file's content. A unit is considered complete only when its lock entry exists **and every recorded file is still present with a matching hash** — file existence alone is never enough.

Two helpers drive this; both are CLI shims around `pipeline_io.py`:

```bash
# Exit 0 if <label>'s outputs are recorded and every file's content still matches.
python3 "$PLUGIN/pipeline_io.py" check-step <label> --evals-dir .tessary

# Record the listed paths as outputs of <label>, capturing their current SHA-256.
python3 "$PLUGIN/pipeline_io.py" lock <label> <path>... --evals-dir .tessary

# Per-file check (used inside grader fan-outs for per-grader resume).
python3 "$PLUGIN/pipeline_io.py" check-file <path> --evals-dir .tessary
```

Wrap each unit like this:

```bash
if python3 "$PLUGIN/pipeline_io.py" check-step <label> --evals-dir .tessary; then
  echo "<label>: resumed from prior run; skipping."
else
  # ... run the unit ...
  python3 "$PLUGIN/pipeline_io.py" lock <label> <produced paths> --evals-dir .tessary
fi
```

Lock labels used by the phased flow:

| Label | Paths to record on completion |
| --- | --- |
| `A` — Phase A (discovery) | `pipeline/product_profile.yaml`, `pipeline/invariants.yaml`, every `pipeline/call_sites/<id>.yaml` |
| `B` — Phase B (triage) | `pipeline/packs.yaml`, `pipeline/priorities.yaml` |
| `C-fm-<id>` — Phase C.1 per-site failure modes | `pipeline/failure_modes/<id>.yaml`, the patched `pipeline/call_sites/<id>.yaml`, and (judgment sites) `pipeline/quality_dimensions/<id>.yaml` |
| `D` — Phase D (chains + taxonomy) | `pipeline/chains.yaml`, `pipeline/failure_modes/_chains.yaml`, `pipeline/taxonomy.yaml` |

Grader files are not locked under a step label — they're locked individually as they're emitted, and `check-file` is the per-grader resume check. Partial grader batches resume cleanly from the first missing grader.

`dedup.py`, `audit.py`, `finalize.py`, and `viewer.py` always run — they're deterministic Python, cheap, and `finalize.py` / `viewer.py` must refresh the lock and viewer regardless. `dedup.py` and audit-driven targeted fix subagents rewrite failure-modes shards; re-lock the affected `C-fm-<id>` entries after each rewrite.

`--force` skips every resume check and re-runs every unit from scratch (use after intentional shard deletion, or when a prior run finished but the user wants a clean re-synthesis).

### Targeted regeneration (`--only`)

`--only <grader_id|call_site_id|chain_id>`:

- **`<grader_id>`** — re-synthesize that grader only. Read its call-site shard + the relevant `failure_modes/<call_site>.yaml`. Do not re-run Phases A–B or other sites; do not re-emit any other file. Update the lock entry for that one file.
- **`<call_site_id>`** — re-synthesize every non-deferred grader for that site. Reads the one call-site shard + failure-modes shard. Use `--complete <call_site_id>` instead if you also want the site's medium/low deferred failures fleshed out.
- **`<chain_id>`** — re-synthesize that chain's graders (non-deferred only; `--complete` to include deferred).

`--only` always respects `_meta.locked_fields`. Combine with `--force` to
override locks (rare).

## Pipeline

Five phases. A and B run once. C is the per-site loop with the user-approval gate. D wraps up chains + taxonomy at the end. E is the on-demand deep-grade flow triggered by `--complete`.

```
┌─ Phase A — Discovery (parallel) ────────────────────────────────┐
│  Product profile subagent  ‖  Call-site discovery subagent      │
└──────────────────────────────────┬──────────────────────────────┘
                                   ▼
┌─ Phase B — Triage (main agent, serial) ─────────────────────────┐
│  Pack discovery + interview  →  Rank call sites  →  Confirm     │
└──────────────────────────────────┬──────────────────────────────┘
                                   ▼
┌─ Phase C — Per-site loop ───────────────────────────────────────┐
│   For each call_site_id in priorities.yaml:                     │
│     Per-site subagent (steps 2+3+4)                             │
│     dedup.py (before deferral — settles severity)               │
│     Mark grader_deferred per severity                           │
│     Grader fan-out for non-deferred FMs only                    │
│     audit.py --partial + finalize.py --partial + viewer.py      │
│     Adaptive gate (strict for sites 1–2, then batch budget)     │
└──────────────────────────────────┬──────────────────────────────┘
                                   ▼
┌─ Phase D — Chains + taxonomy (once at end of C) ────────────────┐
│   Chain detection subagent → taxonomy subagent → final pass     │
│   of dedup / audit / finalize / viewer                          │
└─────────────────────────────────────────────────────────────────┘

Phase E (on demand): /evals:synthesize-graders --complete <id>
```

### Phase A — Discovery

#### A.0 — Solicit telemetry (optional, skippable; v9)

Before dispatching discovery, optionally solicit real OpenTelemetry / trace data so span names
are **observed, not guessed**. This runs once, and is purely additive — it never changes the
graders produced, only whether `expected_spans` are verified.

- **If `--traces` (or an agent-session JSONL) was already supplied** → skip the prompt entirely and
  go straight to Path A, which now emits `source: observed` `expected_spans` from the real spans.
- **If no traces were supplied AND the run is interactive** → emit ONE short, skippable prompt:

  > *Optional: paste or point me at OpenTelemetry data so span names are exact instead of inferred
  > from code. I accept any of: an OTLP/JSON or OTLP-export `traces.jsonl` (the `--traces` format);
  > a flat span-name list (one `name` per line, optionally `name<TAB>kind<TAB>metadata.key=val`); or
  > a Langfuse / Phoenix / Jaeger export. Press enter / "skip" to proceed from source code only.*

  - If the user provides full traces → treat as Path A (verified-span extraction).
  - If the user provides a flat span-name list → run Path B discovery, then match each provided name
    to a discovered call site by use-case / enclosing-function correspondence and write it as a
    `source: observed` `name` matcher (superseding any inferred guess for that site); surface any
    names that did not map back to the user rather than dropping them silently.
  - No answer / "skip" → proceed exactly as today: Path B inference, `source: inferred`, real
    `confidence`. Backward-compatible verbatim.

- **MUST be a NO-OP in any non-interactive / subagent / unattended run** — never block the autonomous
  flow on this prompt. When no interactive gate is available (the same condition the site-1 publish
  gate uses), skip A.0 silently and proceed to Path B as today. Graceful degradation is the rule:
  the absence of solicited telemetry only means `expected_spans` stay best-effort `inferred`, which
  the platform already tolerates.

Then run discovery:

Send **one message with two Agent tool calls** so they run in parallel.

1. **Product profile subagent** (`subagent_type: Explore`) — pass `$PLUGIN/prompts/analyze_product.md`, the target repo path, and the absolute `.tessary/` path. Writes `.tessary/pipeline/product_profile.yaml` and `.tessary/pipeline/invariants.yaml`. Returns a manifest with domain, regulatory regimes, data sensitivity kinds, invariant counts, and `coverage_deferred: true` (because call-site discovery may still be running).

2. **Call-site discovery subagent** — choose:

   **Your deliverable is the shard files on disk, not the manifest.** Write each `.tessary/pipeline/call_sites/<id>.yaml` (and any `.tessary/datasets/<id>.jsonl`) directly to disk; the manifest only *summarizes* what you wrote. Before returning, list each file you wrote and confirm it exists — a manifest that names files it did not write is a failure. (Mirrors `analyze_product.md` — "write the shards directly, return a tiny manifest".)

   - **Path A — traces provided**: `subagent_type: general-purpose`. Parse the JSONL (OTLP/JSON or flat Python SDK exporter shape), normalize spans, group by normalized system-prompt hash, write one `.tessary/pipeline/call_sites/<id>.yaml` per group and `.tessary/datasets/<id>.jsonl` per group. Span taxonomy and observability stats (`observed.*` p50/p95/error_rate/refusal_rate/cost) are required. Stratified sampling at up to 10 representative spans per site. Set `invocation: sdk` by default; if span attributes show the model was reached via a shelled-out agent CLI, a raw HTTP gateway, or a sandbox runner (e.g. a `gen_ai.system` / command attribute naming `claude`, `ollama`, an `http.url` to a model host, or a sandbox span parent), set the matching `invocation` instead. Also set `default_grade_mode: per_conversation` when the group is **multi-turn** — ≥ 2 spans for this site share a `trace_id` (or session id) — so its cross-turn graders default to `scope: trace`; otherwise leave it `per_turn` (omit).

     **Emit VERIFIED `expected_spans` from the real spans (v9).** You have the ground-truth telemetry in hand, so write the observed names rather than guessing. For each call-site group, take the span `name` actually present on the grouped spans and write an `expected_spans` entry `{match_field: name, match_pattern: <observed literal>, kind: span, source: observed}` — **no `confidence`** (an observed name is a verified fact, not a guess). Also emit `{match_field: model, match_pattern: <gen_ai.request.model literal>, kind: span, source: observed}` when the spans carry a model, and a `{match_field: metadata.<key>, ..., source: observed}` entry for any stable metadata/tag key present across the group's spans. A `source: observed` entry **supersedes** (replaces, not appends) any Path-B `inferred` guess for the same call site, so the platform's matcher never sees a verified name competing with a guess. Omit entirely when a group's spans carry no usable name.
   - **Path A-agent — agent-session transcripts provided**: a variant of Path A for Claude Code / opencode session JSONL (and similar agent runners). These are conversation transcripts, not OTLP spans: each line is a turn carrying `tool_use`/`tool_result` blocks, file edits, and bash commands. `subagent_type: general-purpose`. Reconstruct the ordered turn+tool sequence per session and group sessions by the agent's task/system identity into call sites (`invocation: cli_agent` or `sandbox_agent`). Write the captured turns to `.tessary/datasets/<id>.jsonl` using the **agent-session row shape** (see `output_format.md`): a `messages` array of `{role, content, tool_calls?, tool_results?}`, plus an optional per-turn `repo_state: {commit?, git_diff?}` so the **git diff between two turns** is captured as text and becomes a gradeable artifact. Sessions reconstructed this way are the natural input for `scope: trace` graders (prior turns → final turn) and `kind: agentic` graders (which re-inspect the repo state). A site reconstructed from multi-turn sessions (≥ 2 turns) is multi-turn by definition — set `default_grade_mode: per_conversation` on its shard.
   - **Path B — static repo**: `subagent_type: Explore`. Grep for LLM-call patterns; write one shard per discovered call site.

     **An LLM call is not always an in-process SDK call.** A call site is any place this repo causes a model to run, however the request leaves the process. Search all four invocation classes and tag each discovered site with `invocation`:
     - **`sdk`** — in-process provider SDK / framework call. The historical default. Patterns: `messages.create`, `chat.completions.create`, `responses.create`, `generate_content`, `client.complete`, `ChatPromptTemplate`, `langchain`/`langgraph`/`llamaindex`/`litellm` call objects, `ai.generateText`/`streamText` (Vercel AI SDK).
     - **`cli_agent`** — the repo shells out to an agent or LLM CLI binary. Patterns: a process spawn (`subprocess.run`/`Popen`/`os.system`/`check_output` in Python; `child_process.exec`/`spawn`/`execa` in JS; backticks/`sh -c`/`bash -c`) whose argv mentions a known agent/LLM CLI — `claude`, `claude-code`, `opencode`, `aider`, `cursor-agent`, `codex`, `goose`, `crush`, `llm` (Simon Willison's CLI), `ollama run`, `gemini`, `q chat`, `sgpt`, `mods`. Also catch wrapper scripts that exec these. The prompt is whatever argv/stdin the repo passes; there is usually **no in-repo system prompt** (it lives inside the external tool) and **no output schema** (free text on stdout).
     - **`http`** — raw HTTP to a model endpoint, bypassing any SDK. Patterns: `requests`/`httpx`/`aiohttp`/`urllib`/`fetch`/`axios` whose URL or path matches an LLM host (`api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com`, `*.openai.azure.com`, `api.mistral.ai`, `api.cohere.ai`, `api.together.xyz`, `*.bedrock.*`, `api.groq.com`) or a model path (`/v1/messages`, `/v1/chat/completions`, `/v1/responses`, `/v1/complete`, `/api/generate`, `/api/chat`) or a local gateway port (`:11434` Ollama, vLLM/LiteLLM proxy ports).
     - **`sandbox_agent`** — an agent/LLM invoked **inside** a sandbox or remote-exec runner. Patterns: `e2b`, `modal`, `daytona`, `microsandbox`, `Sandbox(...)`, `docker run …`, `docker.containers.run`, a remote-exec API whose command carries a prompt or one of the `cli_agent` binaries above. Treat the sandboxed invocation as the call site even though the model runs out-of-process.

     For `cli_agent`/`http`/`sandbox_agent`, record `file_hint`/`line_hint` of the spawn/request, set `provider` from the binary/host when identifiable (`claude`→`anthropic`, `ollama`→`ollama`, else `other`), set `system_prompt: null` when none is visible in-repo, and write a `use_case` describing what the agent is asked to *do* (e.g. `Run the test suite and fix failures`, `Summarize a PR diff`). These indirect sites are often the **highest-risk** calls precisely because they run un-prompted, un-schema'd, and sometimes in a sandbox — do not skip them because they don't look like an SDK call.

     **Extract `expected_spans` (telemetry nomenclature) while you have the code open — schema 0.12.0, OPTIONAL/best-effort.** From the same code you read around each call site (and store as `surrounding_code`), read out what the instrumentation *names* this operation, so the platform can later bind a grader to the right captured spans/traces. Look for explicit instrumentation: OTel `start_span("…")` / `tracer.start_as_current_span("…")`; Langfuse `name=` / `@observe(name=)` / `update_current_observation(name=)`; logger/tracer names; the **enclosing function name** (the SDK default span name when nothing else is set); and provider-SDK default naming. Write each as one `expected_spans` entry (Path B → `source: inferred`):
       ```yaml
       expected_spans:
         - match_field: name            # one of: name | model | trace_id | metadata.<key>
           match_pattern: "checkout_summary"   # exact string or glob (* / ?)
           kind: span                   # span | trace
           source: inferred             # v9 — Path B is static-code inference, so ALWAYS `inferred`
           confidence: high             # high (explicit name=/start_span literal) | medium (enclosing fn / convention) | low (guess)
       ```
     Use `match_field: model` for a pinned model literal, `metadata.<key>` for an explicit metadata/tag the code attaches, `trace_id` only when the code sets a trace-level identifier. **Path B is static inference, so every entry it writes is `source: inferred`** (never `observed` — that is reserved for entries grounded in real telemetry; see Path A and step A.0). **Omit `expected_spans` entirely (or write `[]`) when no instrumentation hint is visible** — never invent a name. This is low-risk metadata: a wrong or missing entry only weakens span binding, it never blocks grading.

     **Confidence rubric — grep-verify before you stamp (do not over-claim).** A `high` confidence span matcher should be trustworthy, so:
     - assign `confidence: high` **only when the literal `match_pattern` string is found verbatim in source** — grep-confirm it appears in a `start_span("…")` / `tracer.start_as_current_span("…")` / `spanBuilder("…")` / Langfuse `name="…"` literal before stamping `high`;
     - a name **derived from a variable / method call / interpolation** (`grader.name()`, `f"{x}"`, a registry key) → `confidence: low`, and **never** a wildcard `name` (`*` / `?`) at `high`;
     - **prefer a grounded `metadata.<key>` matcher over a wildcard `name`** when the code attaches an explicit metadata/tag (a literal `metadata.grader_id` beats a guessed `name`);
     - emit `expected_spans: []` when the call site **bypasses the common instrumented wrapper** — it calls the model SDK directly with no custom span and no metadata. Do not guess entries for a bypassing site.

     **Split on runtime dispatch — a single physical call location is not always a single call site.** A call site is one *(intent, system prompt, output schema)* combination, not one line of code. When a call location selects its prompt or schema from a registry / map / enum / `match` keyed on a parameter, follow the dispatch and emit **one call site per branch** — each branch has its own failure surface and deserves its own graders. Signals that a call location fans out and must be split:
     - the system prompt is loaded by a variable key (`load_prompt(gate.system_prompt_path)`, `PROMPTS[kind]`, `f"{name}.txt"`) rather than a fixed literal;
     - the response schema is chosen per branch (`schema = gate.response_schema`, `SCHEMAS[kind]`);
     - a registry / dispatch table is indexed by the parameter (`REGISTRY.get(name)`, `HANDLERS[kind]`, `match kind:`);
     - the trace label / `use_case` is parameterized (`use_case = f"epistemic-gate:{gate_name}"`) — this is the developer telling you these are distinct operations, so honor it: one call site per concrete label, named after it (`epistemic_gate_memory`, `epistemic_gate_concepts`, …).

     Enumerate the branch keys from the registry definition, the enum, or the call sites that pass the parameter. If a branch set is unbounded or you cannot enumerate it, emit one call site and note the limitation in `use_case`. Conversely, do **not** over-split: parameters that only vary content (the user's text, a temperature, a retry count) are the *same* call site — split only when the prompt or schema or declared trace identity changes per branch.

   Returns a manifest: a list of `{id, use_case, invocation, provider, sample_count, has_system_prompt, redaction_state, file_hint?, expected_spans_count?}` and the overall `runtime.redaction_state` (worst case across sites). `invocation` is one of `sdk | cli_agent | http | sandbox_agent` (default `sdk`); `expected_spans_count` is the number of telemetry matchers extracted for the site (0 / omit when none found).

   **`use_case` is the call site's display name — write it factually.** It names *what the call produces*, in a short noun phrase (≈3–6 words). State the operation and its object; nothing else.
   - **Drop transport/implementation descriptors** — how the call is delivered or stored is not what it does: no `stream`/`streaming`, `async`, `batched`, `cached`, `via cron`, `background worker`, `structured`, `JSON`.
   - **Drop rationale tails** — why it exists is not its name: cut `... to reduce token usage`, `... for downstream analysis`, `... so that ...`.
   - **Drop the input plumbing** — `... from multiple test sessions`, `... about completed sessions` are usually noise; keep an object qualifier only when it distinguishes this call site from a sibling.

   Examples (observed → factual): "Stream conversational chat responses about completed test sessions" → `Answer questions about a test session`; "Summarize conversation history into cached message to reduce token usage" → `Compact conversation history`; "Generate aggregate UX analysis report from multiple test sessions" → `Generate aggregate UX report`; "Extract episodic memories from session action steps via background worker" → `Extract episodic memories`.

After both return, read only the manifests, then **run post-subagent filesystem verification** (see Constraints § "Post-subagent filesystem verification") on the shards they claim to have written — `product_profile.yaml`, `invariants.yaml`, and every `call_sites/*.yaml` — before locking. Print:

```
Phase A done: domain=<x>; <N> invariants (<high>/<medium>/<low>); regulatory: [<regimes>] | <M> call sites (<indirect> indirect: cli/http/sandbox); redaction_state=<>
```

If the product subagent set `coverage_deferred: true`, spawn a tiny serial follow-up subagent that reads `invariants.yaml` and the call-site shards, computes `invariant_coverage`, and rewrites `invariants.yaml` in place. Give it the **exact output shape** — `invariant_coverage` is a **LIST** (per `analyze_product.md` § "Initial coverage assessment" and `output_format.md:157-159`), never a map:

```yaml
invariant_coverage:
  - invariant: <invariant id or text>
    enforced_in: [<call_site_id>, ...]      # sites that already guard it
    likely_gap_in: [<call_site_id>, ...]    # sites that should but don't
```

It **must NOT** emit a `invariant_name: [call_site_ids]` mapping (the platform's `readList` rejects an OBJECT), and it **must** discriminate `enforced_in` vs `likely_gap_in` per invariant from real evidence — do not blanket-list every call site in one bucket. Preserve the existing `implicit_invariants` list unchanged.

Lock phase A:

```bash
python3 "$PLUGIN/pipeline_io.py" lock A \
  .tessary/pipeline/product_profile.yaml \
  .tessary/pipeline/invariants.yaml \
  .tessary/pipeline/call_sites/*.yaml \
  --evals-dir .tessary
```

**Seed `pipeline/meta.yaml` now and lock it**, so the bundle is self-identifying from the end of Phase A (`publish.py` and the viewer key off `meta.yaml`'s existence; without this seed the bundle reads as a non-bundle until the first `finalize.py`). Use `<N>` = number of call-site shards just written and the product hint from the profile manifest (or `None`):

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "$PLUGIN")
from pathlib import Path
import pipeline_io
pipeline_io.write_meta(Path(".tessary"), "0.13.0", "<product_hint or None>", {},
                       progress={"sites_completed": 0, "sites_total": <N>})
PY
python3 "$PLUGIN/pipeline_io.py" lock A .tessary/pipeline/meta.yaml --evals-dir .tessary
```

The seed is later overwritten by `finalize.py`, which **preserves** this `0.13.0` version and the `product_hint` when run flag-bare (see Step C.5) — so the version never regresses.

### Phase B — Triage

**Pack discovery + interview.** Stays in main context. Bundle paths:

```bash
for f in "$PLUGIN/packs"/*/pack.yaml; do ... ; done
for f in "$REPO/.tessary/packs"/*/pack.yaml 2>/dev/null; do ... ; done
```

Evaluate `applies_when.always` / `applies_when.auto_signals` against `product_profile.yaml` summary fields and the call-site manifest. Categorize each pack: **always-on** (`quality`), **auto-recommended**, **opt-in**, **explicit override**. Print one line per pack.

For each engaged pack, read its `interview.md`, apply pre-fill rules against the phase-A artifacts, batch every genuinely-needed question into a single dialog turn. Compute each pack's `content_digest` (sha256 of `pack.yaml + interview.md + failures.md`, first 16 hex chars). Verify pack manifests against `$PLUGIN/contract/pack.schema.json`. Check `dependencies` / `conflicts`.

Write `.tessary/pipeline/packs.yaml`:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "$PLUGIN")
from pathlib import Path
import pipeline_io, json
pipeline_io.write_packs(Path(".tessary"), json.loads('''<packs json>'''))
PY
```

**Rank call sites.** Main-agent inline reasoning over the phase-A manifest. Signals, in order of weight:

1. **Trace anchoring** — Path A sites outrank Path B sites; among Path A, higher `observed.sample_count` wins.
2. **User-facing surface** — sites whose use_case / file_hint indicate a user-visible surface (UI chat, transactional email, support response) outrank purely-internal helpers.
3. **Data sensitivity / regulatory exposure** — sites whose surrounding code touches `product_profile.data_sensitivity` kinds or `regulatory_context` regimes get a bump.
4. **Path-prominence heuristic for Path B** — public route paths (`/api/v1/...`), exported top-level functions, and modules referenced from the repo's entrypoint outrank deeper utility modules.

Produce a full ordering. Print the top 3 with one-line reasons and a single y/n prompt:

```
Top call sites by impact:
  1. <id_a> — <reason>
  2. <id_b> — <reason>
  3. <id_c> — <reason>
I'll process them in this order; proceed? (y / "start with <id>" / "reorder")
```

Write `.tessary/pipeline/priorities.yaml` as `{"call_site_ids": [<id_a>, <id_b>, ...]}` and lock phase B:

```bash
python3 "$PLUGIN/pipeline_io.py" lock B \
  .tessary/pipeline/packs.yaml .tessary/pipeline/priorities.yaml \
  --evals-dir .tessary
```

### Phase C — Per-site loop

For each `call_site_id` in `priorities.yaml`, in order. **Track wall time for each iteration** — sites 1 and 2 set the per-site cost baseline used by the adaptive gate.

**Step C.1 — Per-site subagent (steps 2+3+4 for this one site).** One Agent call (not a fan-out batch). Subagent reads `prompts/per_site_kit.md` and follows it end-to-end. The kit hypothesizes all 11–26 failure modes **and** (for judgment call sites) 2–5 quality dimensions, writing both the `failure_modes/<id>.yaml` and `quality_dimensions/<id>.yaml` shards. The orchestrator decides which failure modes get graded now; **all quality dimensions for this site are graded this iteration** (they're the grey-area quality trends — never deferred).

Subagent prompt template:

```
You are a per-call-site subagent for synthesize-graders. Your instruction
document is at $PLUGIN/prompts/per_site_kit.md — read it once and follow it
end-to-end for the single call site assigned below.

CALL SITE: <id>

INPUT PATHS
- Plugin root:        <abs $PLUGIN>
- Repo root:          <abs repo>
- Call-site shard:    <abs path to .tessary/pipeline/call_sites/<id>.yaml>
- Product profile:    <abs path to .tessary/pipeline/product_profile.yaml>
- Invariants:         <abs path to .tessary/pipeline/invariants.yaml>
- Packs:              <abs path to .tessary/pipeline/packs.yaml>
- Pack failures.md:   <list of abs paths to each engaged pack's failures.md>

Return ONLY the manifest specified at the bottom of per_site_kit.md.
```

When it returns, **run post-subagent filesystem verification** (see Constraints) on this site's `failure_modes/<id>.yaml` (and `quality_dimensions/<id>.yaml` for judgment sites) — confirm they exist, parse, and that each failure-mode entry carries `call_site_id` — before dedup. On a miss, re-dispatch this site's subagent once.

**Step C.2 — Dedup (deterministic) — before marking deferred or grading.** Run `python3 "$PLUGIN/dedup.py" .tessary/`. Dedup is intra-site (it only merges failures that share a `call_site_id` / `chain_id`, never across sites) and byte-stable on already-deduped shards, so re-running it each iteration leaves prior sites untouched. **Order matters:** dedup can merge failures and bump severity, so it must run *before* you derive `grader_deferred` (which depends on severity) and *before* grading (so a failure that gets merged away never gets an orphaned grader file).

**Step C.3 — Mark deferred.** Read the deduped `failure_modes/<id>.yaml`. For each entry:

- `severity: high` → set `grader_deferred: false`.
- `severity: medium` or `severity: low` → set `grader_deferred: true` and `grader_id: null`.

Patch the shard in place via Read + Edit, then re-lock (include the quality-dimensions shard):

```bash
python3 "$PLUGIN/pipeline_io.py" lock C-fm-<id> .tessary/pipeline/failure_modes/<id>.yaml \
  .tessary/pipeline/call_sites/<id>.yaml \
  .tessary/pipeline/quality_dimensions/<id>.yaml --evals-dir .tessary
```

(Quality dimensions aren't deduped or deferred — skip them in C.2/C.3 and lock them here as-is.)

**Step C.4 — Grader synthesis for this site.** Fan out grader subagents in parallel inside a single Agent message, **scoped to this one call site** — never a project-wide sweep. Two kinds of grader come out of this step:

- one per **non-deferred failure mode** → a failure-catching grader (`kind: llm_judge | deterministic | execution`);
- one per **quality dimension** of this site → a `kind: score` grader (always — quality dimensions are never deferred).

Author discovery and both per-grader templates are under "Grader subagent template" below. Before spawning each subagent, run `python3 "$PLUGIN/pipeline_io.py" check-file .tessary/graders/<grader_id_safe>.yaml --evals-dir .tessary` — if exit 0, skip (already emitted in a prior partial run).

**Step C.4 (and D.5) — orchestrator stamps `_meta`.** `_meta` is orchestrator-owned (contract Roles table), not authored by the subagent. After each grader file returns and **before** locking it, the orchestrator stamps the provenance block deterministically:

```bash
python3 "$PLUGIN/pipeline_io.py" stamp-meta .tessary/graders/<grader_id_safe>.yaml \
  --author "<resolved author name>" --synth-inputs-digest "<digest>" \
  --author-contract-version 8 --evals-dir .tessary
```

`stamp_meta` fills `author`, `synthesized_at`, `synth_inputs_digest`, `author_contract_version`, and **preserves** any existing `_meta.locked_fields` / `_meta.human_edited` on re-run (so it never clobbers human edits). Then lock each emitted grader file as the subagent returns.

**Step C.5 — Bookkeeping.** Run, in order:

```bash
python3 "$PLUGIN/audit.py"    .tessary/ --partial
python3 "$PLUGIN/finalize.py" .tessary/ --partial
python3 "$PLUGIN/viewer.py"   .tessary
```

`audit.py --partial` is informational only — it never exits non-zero and suppresses checks that need every call site to be processed (generic-failure-repeated and pack_no_contribution). `finalize.py --partial` threads through to the embedded `validate.py --bundle` call so deferred failure modes don't trip the FM↔grader bijection check, and writes `sites_completed` / `sites_total` / `deferred_failure_count` into `pipeline/meta.yaml`.

**If this run has been published** (the user opted in at the site-1 gate, or `--publish` was passed), re-push the regenerated bundle after the viewer rebuild — silently, no re-prompt:

```bash
python3 "$PLUGIN/publish.py" upload --evals-dir .tessary
```

This upserts the new graders into the linked project. It's a no-op-safe call: if no link exists for this repo it prints a one-line "not linked" and exits without affecting the run.

**Step C.6 — Status line.** Print exactly one line:

```
Phase C site <i>/<n> [<id>]: <H> high-severity graders emitted; <D> failures deferred. Viewer: .tessary/index.html
```

**Step C.7 — Approval gate. This is a HARD STOP, not a printed question.**

The gate only works if you actually return control to the user. Printing a question and then continuing in the same turn is the bug this step exists to prevent — it silently burns the whole session. To stop correctly you must **end your turn**: print the status line and the prompt, then **emit no further tool calls and produce no further output**. Do not pre-fetch the next site, do not spawn the next subagent, do not "keep going while waiting." The run resumes only when the user sends their next message.

Mechanically:

1. After the gated site/batch finishes (status line already printed in C.6), print the gate prompt for that boundary (below).
2. **Stop. End the turn. Wait for the user.** The next site does not begin until the user replies.
3. When the user replies, honor it: `y`/`yes`/`continue` → proceed; a number `N` → process the next N sites then gate again; `pause`/`stop`/`no` → exit cleanly (the SHA-verified lock lets them resume next session); `start with <id>` / `reorder` → adjust `priorities.yaml` and continue.

Gate boundaries (where you must stop):

- **After site 1 completes** — always. Prompt: `Site 1 of <n> done. Continue to <next_id>? (y / pause) — or "publish" to push these graders to evals.tessary.ai and run them on real traces.`. If the user replies `publish`, run the publish flow below, then re-print this same prompt and wait again (publishing doesn't advance the gate).
- **After site 2 completes** — always. Compute `mean_sec = (t1 + t2) / 2` and `K = min(remaining, max(1, floor(600 / mean_sec)))`. Prompt: `Sites 1 & 2 averaged ~<round(mean_sec)>s each. I can do the next K sites in ~<round(K * mean_sec / 60)> min before checking in again. Proceed? (y / pick N / pause)`.
- **After each subsequent batch of K sites** — re-measure mean per-site wall time on the batch just finished, re-propose K, stop again.
- `--pause-every N` overrides the adaptive batch: stop every N sites regardless.

The first two stops (sites 1 and 2) are non-negotiable even if the user earlier said "go fast" or "don't ask me" — the whole point is an early preview before committing the session. If the user wants zero gates, that is the `--complete all` flow on an already-previewed run, not the first sweep.

Never process the entire `priorities.yaml` in one unattended turn. If you ever find yourself about to start site 2's work without having stopped after site 1, that is the bug — stop instead.

### Publishing to the platform (opt-in, asked once)

The local `.tessary/index.html` is the offline preview. To actually *run* these graders against real traces and share results with a team, the bundle goes to evals.tessary.ai. This is the **only** network egress in the skill and never happens without explicit consent: it runs when the user replies `publish` at the site-1 gate, or when they passed `--publish`. Once published, later sites re-upsert silently (see Step C.5).

When publish is requested, run these two steps and report the printed URL:

```bash
# 1) Connect this session to a project (device-code handshake; opens a browser).
#    Skips automatically if this repo is already linked with a valid token.
python3 "$PLUGIN/publish.py" link --evals-dir .tessary

# 2) Push the bundle (pipeline + graders) and any captured datasets/*.jsonl.
python3 "$PLUGIN/publish.py" upload --evals-dir .tessary
```

`link` prints a short code + URL and waits for the user to confirm in their browser (signing up if needed), then stores a project-scoped token under `~/.config/tessary-evals/`. `upload` imports the graders, then uploads captured trace rows so the graders run immediately. The final printed URL lands the user on the project's **Connect traces** step, where they connect more traces and see verdicts — the aha moment. If `link` is declined or times out, report it and resume the gate; do not retry unprompted.

Optionally, after a successful publish, rebuild the viewer so its header CTA deep-links straight to the user's project instead of the generic homepage — pass the Connect-traces URL `upload` printed:

```bash
python3 "$PLUGIN/viewer.py" .tessary --cta-url "<connect-traces URL>" --cta-label "Open in Tessary"
```

After a successful publish, treat this run as published for the rest of the session: re-run the `upload` step (Step C.5) after each subsequent site's viewer rebuild and after Phase D, so the platform always reflects the latest graders.

### Phase D — Chains + taxonomy (end-of-Phase-C wrap-up)

Run only after Phase C has processed every site in `priorities.yaml` (not after each site). Mid-stream chain detection and taxonomy re-clustering just churn the shards.

**D.1 — Chain detection** (skip if `priorities.yaml` length < 2). One subagent (`subagent_type: general-purpose`) passing plugin root, repo root, `.tessary/` root, the list of call-site shard paths, and `$PLUGIN/prompts/analyze_chains.md`. Writes `chains.yaml` + `failure_modes/_chains.yaml`. When it returns, **run post-subagent filesystem verification** (see Constraints) on `chains.yaml` and `failure_modes/_chains.yaml` (each chain failure carries `chain_id`) before dedup; re-dispatch once on a miss.

**D.2 — Dedup.** Run `python3 "$PLUGIN/dedup.py" .tessary/`. As in Phase C, dedup runs before deferral and grading so it can settle chain-failure severities and merges without orphaning graders.

**D.3 — Mark deferred for chain failures.** Apply the same rule to `failure_modes/_chains.yaml`: `severity: high` → `grader_deferred: false`; medium/low → `grader_deferred: true` and `grader_id: null`.

**D.4 — Taxonomy.** One subagent reads every failure-modes shard, clusters all failure modes (single_call + chain) into a 2-level taxonomy with 6–15 top-level nodes, writes `taxonomy.yaml`, and patches `taxonomy_node_id` back onto each failure-mode entry shard-by-shard via Read + Edit. (Single_call graders were already emitted at Phase C with `taxonomy_node_id: ""`; their taxonomy is resolved at the final gate via their `failure_mode_id` → the patched FM entry, so it is *not* re-spliced onto them here. Only chain graders — synthesized next at D.5, after this clustering — carry the value spliced directly.) When it returns, **run post-subagent filesystem verification** (see Constraints) on `taxonomy.yaml` (parses, has `taxonomy:`) before locking; re-dispatch once on a miss.

**D.5 — Grader synthesis for chains** (skip if no chains). Same fan-out pattern as C.4, applied to chain-scope failure modes that are not deferred.

**D.6 — Final pass.**

```bash
python3 "$PLUGIN/audit.py"    .tessary/ --partial
python3 "$PLUGIN/finalize.py" .tessary/ --partial
python3 "$PLUGIN/viewer.py"   .tessary
```

(Audit and finalize stay in `--partial` mode while any failure mode remains deferred; the bundle is consistent, just not exhaustively graded.)

If this run has been published, re-push the final bundle (no-op-safe if not linked):

```bash
python3 "$PLUGIN/publish.py" upload --evals-dir .tessary
```

Lock phase D:

```bash
python3 "$PLUGIN/pipeline_io.py" lock D \
  .tessary/pipeline/chains.yaml \
  .tessary/pipeline/failure_modes/_chains.yaml \
  .tessary/pipeline/taxonomy.yaml \
  --evals-dir .tessary
```

Print:

```
Synthesis complete: <K> graders emitted across <S> sites; <D> failures deferred. Run /evals:synthesize-graders --complete <call_site_id> to flesh out deferred failures for a site.
```

Then the platform-specific viewer-open line (see "Viewer open command" below).

### Phase E — Deep grade on demand

Triggered by `/evals:synthesize-graders --complete <call_site_id>` or `--complete all`.

1. For each targeted site: read `failure_modes/<id>.yaml`, flip `grader_deferred: true → false` for medium/low entries. Patch via Read + Edit; re-lock the shard.
2. Re-run Step C.4 (grader fan-out) for that site. `check-file` already skips emitted graders, so this only spawns subagents for the freshly-undeferred failures. The failures already carry a `taxonomy_node_id` from Phase D — splice the existing value; do **not** re-cluster the taxonomy (the failure set isn't changing, only the deferred flag, so re-clustering would only risk making already-emitted graders' `taxonomy_node_id` stale). Dedup is likewise unnecessary — these failures already survived it.
3. Run `audit.py` + `finalize.py` + `viewer.py` (`--partial` if other sites still have deferrals; otherwise plain).
4. `--complete all` iterates over `priorities.yaml` and applies the same adaptive approval gate as Phase C.

When the final remaining site has zero `grader_deferred: true` failures, `finalize.py` runs in non-partial mode and `validate.py --bundle` is the authoritative gate.

### Grader subagent template (used by C.4 and D.5)

Author discovery — **the orchestrator resolves the author ONCE, in its own context**, then passes the result explicitly to every grader subagent via the `Grader author` / `Author invocation` fields below. Subagents do not re-resolve.

1. **`evals-prompt`** skill — use only if the orchestrator has **positively confirmed** `evals-prompt` is invocable *inside a subagent*. If confirmed, pass `Author invocation: skill` and the author name `evals-prompt`.
2. **`authors/default`** — the bundled default, the **deterministic default**. Unless (1) is confirmed, resolve to this: pass `Author invocation: bundled-markdown` and the absolute path `$PLUGIN/authors/default/AUTHOR.md`. Both authors declare contract v8, so the version-in-force is identical either way; default to bundled for determinism.

**A subagent must NOT call the Skill tool for the bundled author** — there is no skill by that name, so the call fails (see `contract/AUTHORING_CONTRACT.md` § "Author invocation"). A subagent uses the Skill tool **only** when the orchestrator passed `Author invocation: skill`; for `bundled-markdown` it reads the `AUTHOR.md` at the given path inline.

Print `Using grader author <name>` once at first use, driven by the resolved value. Per-subagent prompt:

```
You are synthesizing graders for one call site (or chain) as part
of a synthesize-graders run. (Behavioral calibration is no longer done here; v7
graders carry no self_tests and are calibrated platform-side against golden datasets.)

CONTEXT
- Plugin root: <abs $PLUGIN>
- Repo: <abs repo>
- Call-site shard path: <abs .tessary/pipeline/call_sites/<id>.yaml>     (single_call)
- Failure-modes shard path: <abs .tessary/pipeline/failure_modes/<id>.yaml> (single_call)
- Quality-dimensions shard path: <abs .tessary/pipeline/quality_dimensions/<id>.yaml> (single_call)
- Chains shard path: <abs .tessary/pipeline/chains.yaml>                  (chain)
- Chain-failures shard: <abs .tessary/pipeline/failure_modes/_chains.yaml> (chain)
- Product profile path: <abs .tessary/pipeline/product_profile.yaml>
- Existing grader files for this call site, if any: <list of paths and locks>
- Grader author: <AUTHOR>
- Author invocation: <skill | bundled-markdown>

PART 1 — FAILURE-MODE GRADERS. For each failure mode where grader_deferred is falsy
(skip deferred ones):
1. If a grader file already exists, load it; pass _meta.locked_fields to the author
   as existing_grader. **v9 freeze:** if the existing grader's `_body_source` is
   `platform-materialized` or `human`, SKIP body authoring entirely — carry its
   `judge_prompt`/`rubric` + `_body_source` + `_meta` forward verbatim and go to the
   splice step; the materialized body is frozen and must never be regenerated.
2. Author body via the selected author (pass the failure_mode block). Author-owned
   output shape: $PLUGIN/contract/AUTHORING_CONTRACT.md. **v8: for kind=llm_judge the
   author emits `_body_source: platform` and NO judge_prompt/rubric — the platform
   expands the judge body on import; for kind=deterministic/execution/agentic the body
   is plugin-authored exactly as before.** Pick scope and kind from the failure mode:
   - **scope** — `single_call` by default; **`trace`** when the failure can only be judged
     with conversation history (the failure description says so — cross-turn coherence on
     `conversational_turn`/`agent_step` sites). A trace grader is judged against the final
     turn given the prior n-1 turns as context at runtime. The site that gets trace graders
     is the one step 1 marked `default_grade_mode: per_conversation` (multi-turn — turns share
     a trace); a site left `per_turn` stays `single_call`.
   - **kind** — `llm_judge`/`deterministic` as usual; **`agentic`** when judging requires
     inspecting the result the agent produced (run `git diff`/tests in a sandbox), typically
     on `sandbox_agent`/`cli_agent` sites. An agentic grader carries an `agent_spec`
     (harness=opencode, sandbox, allowed_tools, task_prompt, verdict_contract, budgets);
     it is binary pass/fail and needs no judge_prompt/rubric (and no `_body_source`).
     A `kind=llm_judge` grader is platform-deferred (v8): the author returns
     `_body_source: platform` and the definition, not a hand-written judge_prompt/rubric.
3. Splice orchestrator-owned fields onto the body (id, scope, failure_mode_id,
   call_site_id|chain_id, name, taxonomy_node_id; block_on_fail=null; dataset_refs).
   (v9 removed the grader-level owner, cost_budget_tokens, and latency_budget_ms_p95 —
   do not splice them.)
   Do NOT write `_meta` — it is orchestrator-owned and stamped after you return
   (see "Step C.4/D.5 — orchestrator stamps _meta" below). Leave it absent.
4. Write to .tessary/graders/<grader_id_safe>.yaml.
5. Validate: python3 "$PLUGIN/validate.py" .tessary/graders/<file>.yaml --pipeline .tessary/
   On failure, retry author up to 3x with validator_feedback; after 3 failures,
   write _validation_error and move on.
   (v7: graders carry no self_tests; behavioral calibration is done later, platform-side,
   against golden datasets — not here.)

PART 2 — QUALITY-DIMENSION SCORE GRADERS. For EVERY quality dimension in the
quality-dimensions shard (none are deferred):
1. Pass the quality_dimension block to the author (see AUTHORING_CONTRACT § "Score
   graders"). The author returns kind: score with `_body_source: platform`,
   rubric_levels, and score_scale — and NO judge_prompt (v8: the platform expands the
   scoring judge prompt on import from the rubric_levels/score_scale definition).
   **v9 freeze:** if the existing score grader's `_body_source` is `platform-materialized`
   or `human`, SKIP body authoring — carry its `judge_prompt` + `_body_source` + `_meta`
   forward verbatim (its body is frozen); still refresh orchestrator-owned fields.
2. Splice orchestrator-owned fields (id = <quality_dimension_id>::grader, scope,
   quality_dimension_id, call_site_id|chain_id, name, eval propagation;
   block_on_fail=FALSE — score graders are report-only trends; dataset_refs).
   (v9 removed grader-level owner / cost / latency budgets — do not splice them.)
   Do NOT write `_meta` (orchestrator-stamped after you return), and do NOT set
   failure_mode_id or taxonomy_node_id on score graders.
3. Write and validate (same retry loop). No self-test calibration (v7).

RETURN ONLY this YAML manifest (no prose):
  call_site_id: <id>  # or chain_id
  emitted: [<grader_id>, ...]            # both failure and score graders
  score_graders: [<grader_id>, ...]      # subset that are kind: score
  failed_validation: [<grader_id>, ...]
  carried_locked: [<grader_id>, ...]
```

The orchestrator sees only the manifests — never grader bodies. The contract is authoritative on the author I/O shape; do not duplicate those rules here.

### Viewer open command

After every viewer rebuild in C.4 and D.4, detect the platform via `uname -s` and print the matching open command:

- macOS (`Darwin`): `Browse the synthesized pipeline visually: open .tessary/index.html`
- Linux: `Browse the synthesized pipeline visually: xdg-open .tessary/index.html`
- Windows / unknown: `Browse the synthesized pipeline visually: start .tessary/index.html`

Then on the next line, print verbatim:

```
The viewer reads only the local files under `.tessary/` — nothing leaves your machine until you click through the CTA button.
```

`viewer.py` reads the shards under `.tessary/pipeline/`, every `.tessary/graders/*.yaml`, and `.tessary/report.md` if present, and emits a single self-contained HTML file. The template files under `viewer_template/` are the editable surface.
## Stable IDs

Unchanged from v0.3.

- **Call site ID**: Path B → source-code label, snake_cased. Path A → `sha::<16-hex>` over the normalized representative system prompt.
- **Failure mode ID**: `<call_site_id>::<name>` (single_call), `<chain_id>::<name>` (chain).
- **Chain ID**: `chain::<short_snake_case_label>`.
- **Grader ID**: `<failure_mode_id>::grader`.
- **Taxonomy node ID**: `tax::<slug>` or `tax::<parent>::<sub>`.

Filenames substitute `::` → `__`. This applies to grader files and to shard
files under `pipeline/call_sites/` and `pipeline/failure_modes/`.

## Constraints

- **No network for synthesis.** Purely local reasoning + files.
- **Use the Bash, Read, Grep, Glob tools** to drive the helpers. Subagents are responsible for writing shards; the orchestrator never directly writes shards under `pipeline/` (except via `pipeline_io.write_packs` for `packs.yaml`, which is orchestrator-owned).
- **Stable IDs.** Re-runs produce diffable output.
- **No invented sources.** Every field must be grounded in traces or source code.
- **Show your work between phases.** One-line status per phase and per per-site iteration; the per-site status line format is fixed (see Phase C.6).
- **Stop after site 1 and after site 2 — always.** End the turn and wait for the user; never run the whole priority list unattended. This overrides any prior "go fast / don't ask" instruction. See Phase C.7.
- **Subagents** at Phase A (product profile + call-site discovery), Phase C.1 (one per site), Phase C.4 (one per non-deferred failure group per site), Phase D.1 (chains), Phase D.4 (taxonomy), Phase D.5 (chain graders), and audit-driven targeted fixes. Every other step is deterministic Python or main-agent dialogue.

### Post-subagent filesystem verification

**Verify the filesystem, not just the manifest.** A subagent's manifest is a *summary*; the deliverable is the shard files on disk. After **every** shard-producing fan-out — Phase A (call sites + product profile), Phase C.1, Phase D.1 (chains), Phase D.4 (taxonomy) — and **before** locking, the orchestrator must confirm, for each path the returned manifest names (and the deterministic set the step is contracted to produce):

1. the file **exists** on disk — `test -f <path>`;
2. it **parses as YAML** and carries the expected top-level key — `python3 -c "import yaml; d=yaml.safe_load(open('<path>')); assert '<key>' in d"`, where `<key>` is `product_profile` / `implicit_invariants`+`invariant_coverage` / `failure_modes` / `quality_dimensions` / `chains` / `taxonomy` for the respective shard;
3. for `call_sites/*.yaml` and `failure_modes/*.yaml`, that each entry carries the keys the next step keys on — notably **`call_site_id` / `chain_id`** on failure-mode entries (missing these silently breaks dedup grouping and per-site coverage gates);
4. **on any miss → do NOT lock. Re-dispatch that subagent once** and re-verify; never lock, grade, or publish on an unverified shard.

This is the earliest catch for a "perfect-looking manifest, zero files" subagent failure, and it also surfaces a missing `call_site_id` (otherwise only caught at `validate.py`) and a missing seeded `meta.yaml` long before platform import.

## Verification (what the user should expect)

A clean run on a small repo (3–4 call sites, 1 chain) with all four packs engaged:

```
Phase A done: domain=B2B sales productivity; 4 invariants (2/2/0 high/medium/low); regulatory: [] | 4 call sites; redaction_state=none
Phase B: pack discovery
  - quality       (always-on) -- engaged
  - security      (auto: regulatory_context [HIPAA]) -- engaged
  - reliability   (auto: traces ingested) -- engaged
  - brand         (auto: brand_voice_signals non-empty) -- engaged
Top call sites by impact:
  1. summarize_meeting_notes — user-facing, 1.2k traced calls/day
  2. extract_action_items — downstream of #1
  3. classify_intent — high-frequency router
I'll process them in this order; proceed? (y / "start with <id>" / "reorder")
> y

Phase C site 1/4 [summarize_meeting_notes]: 6 high-severity graders emitted; 14 failures deferred. Viewer: .tessary/index.html
Continue to extract_action_items? (y / pause)
> y

Phase C site 2/4 [extract_action_items]: 5 high-severity graders emitted; 12 failures deferred. Viewer: .tessary/index.html
Sites 1 & 2 averaged ~72s each. I can process the next 2 sites in ~3 min. Proceed? (y / pick N)
> y

Phase C site 3/4 [classify_intent]: 4 high-severity graders emitted; 9 failures deferred. Viewer: .tessary/index.html
Phase C site 4/4 [render_email_draft]: 5 high-severity graders emitted; 11 failures deferred. Viewer: .tessary/index.html

Phase D: detected 1 chain (trace_confirmed); 5 chain failures (3 high → graded, 2 deferred)
Phase D: 18 taxonomy nodes (13 top-level + 5 sub)
Synthesis complete: 23 graders emitted across 4 sites; 48 failures deferred. Run /evals:synthesize-graders --complete <call_site_id> to flesh out deferred failures for a site.
Browse the synthesized pipeline visually: open .tessary/index.html
The viewer reads only the local files under `.tessary/` — nothing leaves your machine until you click through the CTA button.
```

On a 12-call-site repo with traces, the first sweep typically emits 40–80 high-severity graders (≈25–35% of full-coverage output) and defers the rest. Time-to-first-HTML on site 1 should be 2–3 minutes; the per-site cost stabilizes after sites 1 & 2 and the adaptive gate keeps each batch under roughly 10 minutes wall. Users who want exhaustive coverage run `--complete all` after the first sweep finishes, and the same adaptive gate paces it.
