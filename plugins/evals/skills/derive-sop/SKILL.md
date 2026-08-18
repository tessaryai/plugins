---
name: derive-sop
description: Derive a v3 SOP-conformance file for a call site — read the agent's whole instruction surface and distill it into intents, an atomic observation vocabulary, and rules, then lint it with the bundled validator. Run after /evals:instrument so the SOP names a real call site. Use when the user says "derive an SOP", "author the SOP", "write the conformance policy for this agent", "SOP this call site", or invokes /evals:derive-sop.
---

# derive-sop — distill a call site's instructions into a v3 SOP

The platform runs an **SOP-conformance classifier**: it watches a call site's production traffic
and reports when the agent drifts from its own standing procedure. The customer-side artifact that
feeds it is one **v3 SOP file per call site** — seven concepts, authored here, kept true by
`/evals:reconcile-sop`:

```yaml
agent: <call-site id>                   # the tessary.call_site.id, verbatim

intents:                                # demand-side: what the USER comes for
  <intent-id>:
    means: "<one sentence of demand-side meaning>"

observations:                           # the vocabulary: agent acts, member acts, world-states
  <obs-id>: "<one atomic sentence>"
  <obs-id>:                             # optional frame-exemplar form (judgement observations)
    is: "<one atomic sentence>"
    counts:                             # 2–3 adjudicated mini-scenarios TOTAL across both lists
      - "<a scenario this observation covers>"
    counts_not:
      - "<a near-miss it does not cover>"

rules:
  - in: <intent-id | [ids] | any>       # owed-scope
    when: <obs-id>                      # optional trigger
    unless: <obs-id>                    # optional negated condition
    at: <session-start | session-end>   # optional positional anchor
    expect: <obs-id | {tool: t, before: it|t2, paired_by: k, within: conversation|turn}>
    # — or —
    never: <obs-id | {tool: t}>
    # optional: either: [a, b]  (alternative satisfaction) · of: <delegate-role>  (orchestrators)
```

**Pure meaning, zero mechanism.** No detectors, thresholds, regexes, label files, file paths, line
numbers, or provenance anchors — ever. Routing, detector synthesis, and bindings are compiled
**server-side** by the platform; nothing mechanical belongs in the customer's repo, and nothing in
this file may assume how it will be measured. The schema and its measured basis live in the
evals-platform repo's `classifiers/experiments/SCHEMA-V3.md`; the short version: the repo's own
instruction text routes and compiles most observations on its own, and the frame conventions
exemplars carry are the measured remainder.

## The style laws (all lintable — the validator enforces them)

1. **Atomicity.** A sentence containing *without / unless / before / after / instead of* is
   smuggling rule structure. Split it: the condition moves to `when:`/`unless:`/`at:`/ordering;
   the atom stays. (`"asks for the id without repeating it"` → observation `asks_for_id` +
   the repetition as its own rule.)
2. **Specificity.** Judgement observations name their mechanism. Hedge words — *properly,
   appropriately, correctly, adequately, timely* — are warnings: `"handles the refund properly"`
   compiles to nothing; `"confirms the refund amount before issuing it"` names what to check.
3. **Frame exemplars.** For the residue of judgement observations where no mechanism can be named,
   carry the adjudicated convention as 2–3 `counts:`/`counts_not:` mini-scenarios — plain English,
   meaning-level. This is where "a coverage question the agent deflects is still owed" lives.
   A complete frame answers three questions, not one: what **opens** the obligation (a member ask
   the agent engages substantively — or the agent **volunteering** the position unasked; openings
   can be agent-side), how long it **persists** (typically until discharged or the conversation
   ends — follow-ups, pushback, process questions and even wrap-up turns inside an opened
   interaction stay owed), and the **carve-outs** (e.g. conversations where no position is taken
   never open it; a refusal doesn't open it; an out-of-scope topic doesn't). Frames are
   **per-rule** — two rules in the same SOP can carry different opening conditions and different
   carve-outs, so derive each from its own instruction text rather than reusing a sibling's.
   Exemplars attach to observations, so when two rules need different frames for the same
   behavior, split the observation rather than blending the frames.
4. **Prohibitions name atomic acts.** A `never:` target is one act (`gives_outcome_guarantee`),
   not a compound (`refunds_and_apologizes`); rare compound violations decompose into `when:` +
   an obligation.

## Resolve the plugin path once

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*/evals/skills/derive-sop/*' 2>/dev/null \
  | xargs -I{} dirname {} | xargs -I{} dirname {} | xargs -I{} dirname {} \
  | sort -V | tail -1)}"
echo "PLUGIN=$PLUGIN"
```

Two worked examples ship with the plugin: `$PLUGIN/sop_examples/policy_gpt.yaml` (valid, shows the
exemplar form) and `$PLUGIN/sop_examples/broken.yaml` (every lint class). Read the valid one before
authoring your first SOP.

## Flow

### 1 — Pick the call site

The SOP is **per call site**; its `agent:` value is the `tessary.call_site.id`, verbatim. Read
`.tessary/pipeline/instrumentation.yaml` for the repo's tagged call sites and confirm with the user
which one to derive (or iterate over several — one file each). If nothing is instrumented yet,
stop and route to `/evals:instrument`: an SOP for a call site the platform can't see in telemetry
has nothing to bind to.

### 2 — Read the whole instruction surface

Read **everything that instructs the agent at this call site**: system prompts (including
composed/templated fragments), tool definitions and their descriptions, routing rules, few-shot
examples, guardrail config, retrieval-injected policy documents checked into the repo — wherever
instructions live. In real repos they live **duplicated and disjoint**: the same rule stated in
the system prompt and again, differently, in a tool description. Read all copies.

Do **not** record where anything came from. The SOP carries no provenance anchors, by design —
pointers rot the moment the prompt file is refactored; `/evals:reconcile-sop` re-reads the whole
surface each time instead. Evidence belongs in your conversation with the user, never in the file.

### 3 — Derive the intents, demand-side

Intents are **what the member/user comes for**, not what the agent does: id plus a one-line
`means:`. Derive them from the instruction surface's own routing/segmentation language and from
what the rules will need as owed-scope — an intent no rule scopes to is dead weight. A mode-scoped
agent (tutor with open/closed question modes) may use modes as intents, with the caveat that mode
evidence is partially agent-declared; note that caveat in a comment.

### 4 — Derive the observation vocabulary

One atomic sentence per observation, obeying the style laws. Three kinds share the one vocabulary —
**agent acts**, **member acts**, **world-states evidenced by tool results** — and the sentence
names the actor ("asks the member for…" vs "the member provides…"); bindings differ automatically
server-side.

**Harvest exemplars from the prompt's own clarifying asides.** Instruction authors write the frame
convention down without knowing it: "a general question does not trigger it" is a `counts_not:`
exemplar, near-verbatim; "even if the member is only asking hypothetically" is a `counts:`
exemplar. These asides are adjudications the product team already made — capture them rather than
inventing scenarios. Reserve the exemplar form for judgement observations that need it; plain
behavioral atoms stay bare sentences.

**Cover opening AND persistence, not just triggering.** Measured on real annotation gaps
(style-law 3's frame dimensions): the costly mislabels are rarely about what triggers an
obligation — they're persistence turns (the member's wrap-up "ok, will call the agent" after an
unresolved coverage question is still owed) and agent-side openings (the agent volunteering a
coverage position opens the obligation exactly as an ask does). When harvesting exemplars for an
obligation-shaped observation, make at least one `counts:` a persistence or agent-side-opening
scenario and at least one `counts_not:` a no-position/never-opened scenario, if the instruction
surface supports them.

### 5 — Author the rules — every instruction lands somewhere

Walk the instruction surface instruction by instruction. Each one is either:

- **enforced** — expressed as a rule (`in`/`when`/`unless`/`at` + `expect:` or `never:`), with a
  `# enforced:` comment naming the instruction it carries in your own words; or
- **deferred** — not expressible in the schema (escalating-exception conduct, tone, pure style),
  recorded as a `# deferred: <instruction> — <reason>` comment at the foot of the file.

Nothing gets silently dropped: the comments are how a reviewer — and the reconciliation flow —
sees that the mapping was total. Comments carry meaning-level phrasing only, never file paths or
quoted prompt text.

### 6 — Lint, and fix errors

```bash
python3 "$PLUGIN/sop_lint.py" .tessary/sops/<call_site_id>.yaml
```

Errors (atomicity, unknown refs, exemplar shape, structure) must go to zero — split sentences,
fix ids, reshape exemplars. Warnings (hedge words, never-polarity, exemplar count) are judgement
calls: resolve them or justify keeping them to the user, never ignore them silently. Exit codes:
`0` clean, `1` errors, `2` unreadable/invalid YAML.

### 7 — Surface contradictions as findings

When duplicated instruction sources **disagree** — the system prompt says "always verify before
quoting policy" while a tool description says verification is optional for renewals — do not pick
a winner. Author the rule from the stricter reading, and report the contradiction to the user as
an explicit finding: the two positions (quoting each source in the chat), and which reading the
SOP currently encodes. Contradictions are product decisions, not authoring decisions.

### 8 — Write, commit, hand off

Write the file to **`.tessary/sops/<call_site_id>.yaml`** (a call-site id containing `::` nests as
folders, `::` → `/`, matching the bundle's shard convention). Show the user the full file plus the
lint output and the findings from step 7, then commit it with the rest of `.tessary/`.

Tell the user plainly: **the deliverable is the authored, linted file in the repo.** Upload to the
platform is currently an ops-side seam — there is no tenant-facing endpoint yet — so the platform
team wires it in from the repo; nothing further to run here. When the instructions change later,
`/evals:reconcile-sop` keeps the file true.

## What never goes in the file

Detector types, thresholds, regexes, model or encoder names, label files, corpus references,
file paths, line numbers, commit SHAs, quoted prompt text, supply/coverage status. If it describes
*how conformance is measured* rather than *what the procedure means*, it is the platform's
compile output, not this file. A reviewer holding only the product spec must be able to read
every line.

## Constraints

- **One SOP per call site**; `agent:` is the call-site id, verbatim, never invented.
- **Never author from memory of what agents usually do** — every intent, observation, and rule
  traces to something the instruction surface actually says. Gaps are findings, not fill-ins.
- **Observation and intent ids are stable identifiers** — the platform's server-side bindings key
  on them. Choose them once, snake_case observations, kebab-case intents (match the examples).
- **This skill writes exactly one artifact**: the SOP file. It never edits source code, prompts,
  or other `.tessary/` shards.
