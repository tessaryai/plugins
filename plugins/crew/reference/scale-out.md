# crew scale-out — fanning huge-scope work across a Claude Workflow

The orchestrator (`/crew:run`) normally drives work as a **serial loop of `Task` subagents**,
bounded by `orchestrator.max_items` and `concurrency`. That is the right tool for a feature or
a handful of issues. It is the **wrong** tool when triage or analysis reveals the real scope is
enormous — a module-by-module rewrite, a repo-wide cleanup that genuinely spans dozens of
files, a migration across many call sites. Grinding through that serially is slow and loses the
structure of the work.

**Scale-out** is the escape hatch: decompose the work into independent units, **confirm with
the user**, then fan it out across a single Claude **Workflow** that runs one
implement→review pipeline per unit, each in its own isolated workspace. This file is the
contract for when and how to do that.

The serial loop stays the default. Scale-out is a deliberate, **always-confirmed** escalation —
never automatic.

## 1. When to escalate

Reach for scale-out only when **both** hold:

1. A primitive (triage-bug / triage-task / spring-cleaning / implement-issue analysis) reported
   **`scale-out-recommended`** with a decomposition plan, *or* your own survey makes the same
   call — the work plainly spans many modules or needs a broad rewrite, far more than one
   review-ready PR.
2. The decomposition yields **more independent units than `orchestrator.scale_out`** (the floor,
   default 8). At or below the floor, stay in the serial loop — fanning out a few units isn't
   worth a Workflow's overhead.

`orchestrator.scale_out` is both the floor and the on/off switch: set it to `0` (or `false`) to
disable scale-out entirely; crew then always uses the serial loop and notes oversized work in
its report for a human to split.

Above the floor it is still a **judgment call**, not a reflex — prefer scale-out when the units
are genuinely independent and the total clearly overruns what `max_items` can chew through in a
reasonable run.

## 2. The decomposition plan (the contract)

A clean, explicit list. Each **unit** is:

```
{
  id:          "u1",                       # stable within this plan
  description: "Rewrite the auth module's token store",
  target:      "src/auth/** (token store + its tests)",   # module / files this unit owns
  primitive:   "implement-issue",          # implement-issue | spring-cleaning | update-docs | …
  depends_on:  []                          # ids that must finish first (usually empty)
}
```

The primitive that flagged huge scope produces this and returns it to the orchestrator. The
orchestrator may **refine, split, or merge** units, but owns the final list. Units should be
**disjoint in the files they touch** — that's what makes parallel workspaces safe (and, under
jj, keeps concurrent workspaces from rewriting a shared ancestor and staling each other).

## 3. The confirmation gate — MANDATORY

**Never spawn a Workflow without explicit user approval.** Before calling the `Workflow` tool,
present the plan with `AskUserQuestion`, showing:

- the **unit list** (id, description, target, primitive);
- the **split shape** — what runs in parallel vs. what's pipelined or deferred to a later wave;
- an **estimate**: agent count (≈ 2 per unit — implement + review — plus any fix rounds) and a
  rough token cost, so the user decides with eyes open;
- the **branch-per-unit** strategy and the reminder that crew **still never merges**.

If the user declines, fall back to the serial loop (bounded by `max_items`, noting the
remainder) or stop. The human confirmation **is** the cost ceiling — crew sets no hard agent
cap.

## 4. Running the Workflow — default is the shipped script

crew ships `workflows/scale-out.js`, a reviewed, parameterized Workflow. Don't re-author it;
build its `args` and invoke it:

1. For each unit, derive a kebab-case **slug** (work-model.md §3) and **pre-create its ledger
   folder** (`<ledger.dir>/<slug>/task.md` with the unit's description and `status: new`) so the
   unit-agents resume cleanly and you can read their results afterward.
2. Resolve the **absolute** plugin root (you know `${CLAUDE_PLUGIN_ROOT}`) and the **mode**, then
   call:

   ```
   Workflow({
     scriptPath: "<ABS_PLUGIN_ROOT>/workflows/scale-out.js",
     args: {
       pluginRoot: "<ABS_PLUGIN_ROOT>",
       mode: "<github|local>",
       units: [ { id, slug, description, primitive, target }, … ],
       isolation: "<jj|kosho|git-worktree|none>",   // local mode: the resolved local.isolation (work-model.md §4)
       maxReviewIterations: <guardrails.max_review_iterations>
     }
   })
   ```

   Use **`scriptPath`**, not a workflow name — it's robust regardless of plugin→workflow
   registration. Workflow scripts have no env/fs access, so *everything* travels through `args`.

The shipped script handles the rest: one `pipeline()` per unit (implement → review), per-unit
isolation so parallel edits never collide, structured results, and **one branch/PR per unit**.
For git-native isolation (kosho/git-worktree/none, and github mode) it uses the harness
`isolation: 'worktree'`. Under **`isolation: "jj"`** it instead has each unit-agent create its
own **jj workspace** (work-model.md §4.1) — colocated jj at the repo root makes a harness
`git worktree add` fail (detached HEAD), and the agent runs `jj workspace update-stale`
defensively since parallel workspaces share one backend. Keep units **disjoint in files** so
those concurrent workspaces never rewrite a shared ancestor. The dispatch prompt it builds is byte-for-byte the
contract of `run/SKILL.md` step 5, so each unit-agent behaves exactly like a Task-dispatched
primitive — same mode, same work item, same guardrails, same never-merge ceiling.

### Dependencies and the bounded fix loop

The shipped script treats units as **independent** (the common case for module-wide work). When
the plan has real `depends_on` chains, **do not** smuggle ordering into one Workflow run —
instead run dependent units in a **separate, separately-confirmed wave** after the first wave
lands, or use the fallback below. Never silently reorder.

The script's pipeline is implement → review. To also run the bounded fix loop
(`respond-to-review`, capped by `guardrails.max_review_iterations`) on units that came back
`request_changes`, gather those after the run and dispatch `respond-to-review` for them — as
normal `Task` steps, or as a follow-up scale-out wave if there are many. Still one branch/PR per
unit; still never merge.

## 5. Dynamic fallback

Only when a plan's shape genuinely doesn't fit the shipped template — e.g. a deep `depends_on`
graph that can't be split into independent waves — may you author a **bespoke inline**
`Workflow({ script })`. If you do, it **must** reuse the same contract this file defines: the
identical dispatch prompt (§4 / run/SKILL.md step 5), `isolation: 'worktree'` for mutating
agents, one branch/PR per unit, and **never merge**. The
shipped script is the reference implementation; a bespoke one must not drift from it.

## 6. Synthesis and report

The Workflow runs in the background and notifies you on completion. Then:

- Read its return value (`{ units: [...] }`) and update each unit's ledger folder
  (`decision.md` / `review.md` / status) from the structured results.
- Fold the outcome into the orchestrator's final report: units **implemented**, units that came
  back **request_changes** (and whether a fix wave ran), units that **escalated**
  (`needs_human`), and any that **failed**.
- Surface the branch/PR per unit. The user reviews and merges — crew does not.

## 7. Constraints

- **Always confirm** before spawning — no Workflow without explicit user approval.
- **Never merge**, at any scale. The ceiling is review-ready, per unit.
- **One branch/PR per unit** — never one giant PR.
- Every per-unit guardrail still applies inside each unit-agent: `protected_paths` → escalate.
- Stay above the `orchestrator.scale_out` floor; below it, use the serial loop.
