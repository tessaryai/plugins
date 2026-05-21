# Platform handoff — v0.10 grader contract additions

This document is for the **evals-platform** team (the runner that executes graders this plugin
synthesizes). It lists exactly what the platform must implement to consume the three additive
contract changes introduced in plugin v0.10 / on-disk schema `0.10.0`:

1. `scope: trace` — multi-turn graders (final turn judged given the prior n-1 turns).
2. Agent-session ingestion — Claude Code / opencode JSONL transcripts as a dataset source.
3. `kind: agentic` — a binary verdict produced by an agent running in a sandbox.

All three are **additive**. Existing graders are unchanged. `scope` / `kind` are stored as plain
TEXT (no DB enum constraint), so no migration is required unless the platform chooses to persist
`agent_spec` in a typed column. **Until the platform implements an arm below, graders of that shape
are parsed and stored but not executed** — the same status `deterministic` / `execution` have today.

The authoritative schema is `contract/grader.schema.json` in this plugin; the authoritative grader
rules are `contract/AUTHORING_CONTRACT.md` (v4). The platform's vendored copy is refreshed via its
own `scripts/sync-evals-contract.sh` (see `docs/upgrade-evals-contract.md`).

> File/line references below point at evals-platform as surveyed for this handoff. Treat them as
> "start here," not as guaranteed-current line numbers.

## 0. Re-sync the vendored schema

Run `scripts/sync-evals-contract.sh` to pull the updated `contract/grader.schema.json` into
evals-platform, then update the Java model (`backend/.../model/Grader.java`) and the MCP tool's
hardcoded enum list (`backend/.../mcp/McpToolRegistry.java`, the `kind` list ≈ line 128) to include
`agentic`, and the `scope`-aware code paths to accept `trace`.

## 1. `scope: trace` (multi-turn input)

**Contract:** a trace grader anchors to one `call_site_id` (like `single_call`); its self-tests carry
`input_messages: [{role, content, tool_calls?, tool_results?}]` (the prior n-1 turns) + `final_output`
(the graded turn). The grader judges `final_output` *in the context of* `input_messages`.

**Platform work:**
- `RawEntry` (`backend/.../ingest/RawEntry.java`) is single-turn (`input` → `output`). Add a
  `messages: List<Message>` (+ session id) variant so a run can carry conversation history.
- `ContentExtractor` (used in `RunExecutor`, ≈ line 193) and `ChatJudgeRunner`
  (`backend/.../judge/ChatJudgeRunner.java`) must feed the prior turns as judge context and grade the
  final turn.
- Add `trace` to the executable-kind filter (next section) so trace+llm_judge graders actually run.

## 2. Agent-session ingestion

**Contract:** the plugin can emit agent-session dataset rows (see `output_format.md` →
"Agent-session rows"): `{session_id, call_site_id, invocation, messages[], repo_state:{commit,
git_diff}}`. These reconstruct a Claude Code / opencode session as an ordered turn+tool sequence, with
the per-turn git diff captured as text.

**Platform work:**
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
- [ ] `RawEntry` gains multi-message support; `ContentExtractor` / `ChatJudgeRunner` use history.
- [ ] New agent-session `SourceFactory`.
- [ ] Sandbox + opencode execution backend for `kind: agentic`.
- [ ] (Optional) typed `agent_spec` column + migration.
