export const meta = {
  name: 'crew-scale-out',
  description: 'Fan an approved crew decomposition plan across subagents — one branch/PR per unit, each implemented then reviewed; never merges.',
  whenToUse: 'Invoked by /crew:run only after the user confirms scale-out for a huge-scope task (see reference/scale-out.md). Not run directly.',
  phases: [
    { title: 'Implement', detail: 'one agent per unit, in its own worktree' },
    { title: 'Review', detail: 'review each implemented unit against the project standards' },
  ],
}

// ---------------------------------------------------------------------------
// crew scale-out — the shipped, parameterized Workflow.
//
// The orchestrator (/crew:run) builds the decomposition into `args` and calls:
//   Workflow({ scriptPath: "<ABS_PLUGIN_ROOT>/workflows/scale-out.js", args })
//
// Workflow scripts have NO env/filesystem access, so everything arrives via args:
//   args = {
//     pluginRoot: "/abs/path/to/plugins/crew",   // resolved ${CLAUDE_PLUGIN_ROOT}
//     mode: "github" | "local",
//     units: [{ id, slug, description, primitive, target }],
//     maxReviewIterations?: number,               // informational; the cap lives in crew.config.yaml
//   }
//
// Each unit becomes one independent pipeline: implement (in its own worktree) →
// review. One branch/PR per unit. crew NEVER merges, at any scale.
// Dependencies are NOT handled here — the orchestrator runs dependent units in a
// separate confirmed wave, or uses the dynamic fallback (see reference/scale-out.md).
// ---------------------------------------------------------------------------

const { pluginRoot, mode, units } = args

// Structured result of an implement (or other mutating) primitive on one unit.
const UNIT_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['slug', 'status', 'escalated', 'summary'],
  properties: {
    slug: { type: 'string', description: 'the unit slug, echoed back' },
    status: {
      type: 'string',
      enum: ['implemented', 'escalated', 'failed'],
      description: 'implemented = review-ready change committed; escalated = handed to a human; failed = could not complete',
    },
    escalated: { type: 'boolean', description: 'true if the unit hit a guardrail (protected path, too many files) and was handed off' },
    branch: { type: 'string', description: 'the branch the change lives on (empty if none)' },
    pr: { type: 'string', description: 'PR URL in github mode, else empty' },
    filesTouched: { type: 'array', items: { type: 'string' }, description: 'paths changed' },
    summary: { type: 'string', description: 'one or two sentences on what was done or why it escalated' },
  },
}

// Structured result of reviewing one implemented unit.
const REVIEW_RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['slug', 'decision', 'summary'],
  properties: {
    slug: { type: 'string' },
    decision: {
      type: 'string',
      enum: ['approve', 'request_changes'],
      description: 'approve = clean; request_changes = blockers found',
    },
    blockers: { type: 'array', items: { type: 'string' }, description: 'blocking findings, file:line where possible' },
    summary: { type: 'string' },
  },
}

// The dispatch prompt — byte-for-byte the contract of run/SKILL.md step 5, so a
// Workflow-spawned unit-agent behaves identically to a Task-dispatched primitive.
const dispatch = (u, primitive, extra = '') =>
  `Read and follow the instructions in ${pluginRoot}/skills/${primitive}/SKILL.md exactly. ` +
  `First read ${pluginRoot}/reference/work-model.md and operate in ${mode} mode. ` +
  `Work item: ledger slug "${u.slug}" — ${u.description}. ` +
  `Scope strictly to this unit's target: ${u.target}. ` +
  `Obey every guardrail in crew.config.yaml; never touch protected_paths (escalate instead); ` +
  `do not merge anything. ${extra} ` +
  `Report back: what you did, the PR URL or branch name, the files you touched, and whether ` +
  `you escalated (needs_human label / ESCALATION.md).`

log(`scale-out: ${units.length} unit(s), mode=${mode}`)

const results = await pipeline(
  units,
  // Stage 1 — implement the unit, isolated in its own worktree so parallel edits never collide.
  (u) =>
    agent(dispatch(u, u.primitive), {
      label: `impl:${u.slug}`,
      phase: 'Implement',
      isolation: 'worktree',
      schema: UNIT_RESULT,
    }),
  // Stage 2 — review the implemented branch. Skip units that escalated or failed in stage 1.
  (imp, u) => {
    if (!imp || imp.escalated || imp.status !== 'implemented') return imp
    return agent(
      dispatch(
        u,
        'review-pr',
        `Review the change on branch "${imp.branch || `crew/${u.slug}`}" against the project's coding standards. ` +
          `Judge only this unit's diff; do not re-implement.`,
      ),
      { label: `review:${u.slug}`, phase: 'Review', schema: REVIEW_RESULT },
    ).then((review) => ({ ...imp, review }))
  },
)

return { units: results.filter(Boolean) }
