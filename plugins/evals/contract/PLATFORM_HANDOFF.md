# Platform handoff — v0.10 / v0.11 grader contract additions

This document is for the **evals-platform** team (the runner that executes graders this plugin
synthesizes). It lists exactly what the platform must implement to consume the additive
contract changes introduced in plugin v0.10–v0.11 / on-disk schema `0.10.0`–`0.11.0`:

1. `scope: trace` — multi-turn graders (final turn judged given the prior n-1 turns).
2. Agent-session ingestion — Claude Code / opencode JSONL transcripts as a dataset source.
3. `kind: agentic` — a binary verdict produced by an agent running in a sandbox.
4. `default_grade_mode` (v0.11) — a per-call-site flag marking a multi-turn site.

## What changed in v0.11 (read first if you already shipped v0.10)

v0.11 **pins how a `scope: trace` grader's history is sourced** and makes it cheaper to implement:

- **Sourcing = the final turn's self-contained `input`.** With Langfuse / Claude-Code-style
  instrumentation, each turn's logged `input` already contains the whole prior transcript. So the
  runner grades a multi-turn site by **grouping observations by trace, taking the latest turn, and
  judging its `input` (the transcript) + final output** — one verdict per conversation. **This means
  §1's "multi-message `RawEntry`" and §2's "agent-session `SourceFactory`" are NOT required for trace
  `llm_judge` graders** — only group-by-trace + last-turn selection (which evals-platform already has
  as its internal `TraceTransform` / `grade_mode` mechanism). Agent-session ingestion (§2) and the
  multi-message path remain relevant only for `kind: agentic` and for instrumentation that does not
  carry the whole transcript on the final turn.
- **New call-site field `default_grade_mode: per_turn | per_conversation`** (default `per_turn`). The
  orchestrator sets `per_conversation` on multi-turn sites and authors their cross-turn graders as
  `scope: trace`. The platform should treat `scope: trace` as the canonical signal that a site is
  graded per conversation (its per-call-site curation toggle is the user override), and may read
  `default_grade_mode` for display / pre-fill. The field is plain TEXT; no migration is required.

All three are **additive**. Existing graders are unchanged. `scope` / `kind` are stored as plain
TEXT (no DB enum constraint), so no migration is required unless the platform chooses to persist
`agent_spec` in a typed column. **Until the platform implements an arm below, graders of that shape
are parsed and stored but not executed** — the same status `deterministic` / `execution` have today.

The authoritative schema is `contract/grader.schema.json` in this plugin; the authoritative grader
rules are `contract/AUTHORING_CONTRACT.md` (v6). The platform's vendored copy is refreshed via its
own `scripts/sync-evals-contract.sh` (see `docs/upgrade-evals-contract.md`).

> File/line references below point at evals-platform as surveyed for this handoff. Treat them as
> "start here," not as guaranteed-current line numbers.

## 0. Re-sync the vendored schema

Run `scripts/sync-evals-contract.sh` to pull the updated `contract/grader.schema.json` into
evals-platform, then update the Java model (`backend/.../model/Grader.java`) and the MCP tool's
hardcoded enum list (`backend/.../mcp/McpToolRegistry.java`, the `kind` list ≈ line 128) to include
`agentic`, and the `scope`-aware code paths to accept `trace`.

## 1. `scope: trace` (multi-turn input)

**Contract:** a trace grader anchors to one `call_site_id` (like `single_call`); at runtime it is fed
the prior n-1 turns as context plus the final turn it judges. A trace `llm_judge` judges the final turn
*in the context of* the prior conversation; a trace `deterministic` check reads the structured
`input.messages` / `input.tool_uses` the platform builds from the turns (v6). `applies_when` is always
LLM-evaluated — for deterministic graders the platform runs a separate LLM applicability gate before the
gate-free body (no `applies_when_check`). (v7: graders carry no inline self-tests; behavior is calibrated
against golden datasets — real labeled spans — platform-side.)

**Platform work (v0.11 sourcing — much smaller than the original v0.10 plan):**
- Group a multi-turn site's observations by `trace_id`, take the **latest turn**, and feed its
  `input` (the transcript) + final output to the judge. evals-platform already has this as its
  internal `TraceTransform`/`TraceTransformer` (`select: last_turn`); a `scope: trace` grader on a
  call site is the signal to apply it (its per-call-site `grade_mode` curation toggle overrides).
- Calibrate `scope: trace` graders against golden datasets (v7): the golden items are real trace spans
  whose transcript-bearing `input` + final output are fed through the same last-turn judge path; the
  grader carries no inline self-tests to run.
- ~~Add a `messages: List<Message>` variant to `RawEntry`~~ and ~~feed prior turns via
  `ContentExtractor`~~ are **no longer required** for trace `llm_judge` graders under v0.11 sourcing
  (still needed for `kind: agentic` / non-self-contained instrumentation).
- Add `trace` to the executable-kind filter (next section) so trace+llm_judge graders actually run.

## 2. Agent-session ingestion

**Contract:** the plugin can emit agent-session dataset rows (see `output_format.md` →
"Agent-session rows"): `{session_id, call_site_id, invocation, messages[], repo_state:{commit,
git_diff}}`. These reconstruct a Claude Code / opencode session as an ordered turn+tool sequence, with
the per-turn git diff captured as text.

**Platform work** (needed for `kind: agentic` and for instrumentation that does *not* carry the whole
transcript on the final turn — **not** for trace `llm_judge` graders, which use the v0.11 last-turn
sourcing above):
- Add a `SourceFactory` / import adapter (alongside the existing Braintrust / Langfuse sources under
  `backend/.../ingest/`) that parses agent-session JSONL into multi-message `RawEntry`s.
- Surface `repo_state.git_diff` to graders that read it (trace `llm_judge`) and to the agentic runner
  (which may instead recompute it in the sandbox).

## 3. `kind: agentic` (sandbox runner)

**Contract:** an agentic grader carries an `agent_spec`:
```yaml
agent_spec:
  harness: opencode
  sandbox: {image: <string>, network: none|egress|full}
  allowed_tools: [bash, read, git]
  task_prompt: <string>          # grading task; ends in one binary decision
  verdict_contract: <string>     # how the agent prints PASS/FAIL
  budgets: {max_turns, max_cost_usd, timeout_s}   # optional
```
Verdicts are binary (pass/fail) in v0.10. The plugin validates the spec's shape only — it never runs
it.

**Platform work (the largest item — a new execution backend):**
- `RunExecutor` (`backend/.../run/RunExecutor.java`) today filters to executable kinds (≈ line 151:
  `"llm_judge".equals(k) || "score".equals(k)`). Add `agentic` (and `trace`) to what runs.
- Add a dispatch arm that launches the agent per `agent_spec`: provision the `sandbox.image`, mount
  the session repo at the relevant state, restrict to `allowed_tools` and `sandbox.network`, run the
  `harness` (opencode) with `task_prompt`, enforce `budgets`, and parse the result per
  `verdict_contract` into a pass/fail verdict.
- No sandbox/container infra exists in the backend today (no docker/e2b/modal/opencode references), so
  this is net-new: a sandbox abstraction + opencode invocation + verdict extraction.
- Optional: persist `agent_spec` in a typed column (Liquibase changeset on the `grader` table). Not
  required — it can live in the existing JSON/text grader payload.

## Coordination checklist

- [ ] Re-sync `grader.schema.json`; update `Grader.java`.
- [ ] `McpToolRegistry` kind list += `agentic`; scope handling accepts `trace`.
- [ ] `RunExecutor` executable-kind filter += `agentic`, and runs `trace`-scope graders.
- [ ] (`kind: agentic` / non-self-contained instrumentation only) `RawEntry` multi-message support + agent-session `SourceFactory`. Trace `llm_judge` grading uses the v0.11 last-turn sourcing — no multi-message source needed.
- [ ] Sandbox + opencode execution backend for `kind: agentic`.
- [ ] (Optional) typed `agent_spec` column + migration.
