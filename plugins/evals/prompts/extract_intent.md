You are extracting the intent and constraints of one LLM call site. Read the prompt, the surrounding code, the system prompt, and any product hint provided.

The intent you produce here is the **single most important input** to the next steps — failure-mode hypothesis and grader synthesis both lean on it. A vague intent ("summarizes text") leads to vague failure modes ("might be wrong"). A precise intent ("summarizes a sales-call transcript for a busy account exec who has 30 seconds to triage next steps before their next meeting") leads to precise, user-centric failure modes.

## Output, per call site

### 1. `intent` — three sentences, in this exact order

**Sentence 1 — what this call produces.** Be concrete. "Generates a 2-3 sentence overview plus a bulleted list of action items, each tagged with the owner."

**Sentence 2 — who the user is and what their constraint is.** Don't skip this. Examples of useful framing:
- "The user is a sales rep who has 30 seconds between meetings and needs to know what to do next."
- "The user is an enterprise support agent answering a question about internal documentation; they will copy-paste the answer into a ticket."
- "The user is the parent agent in a multi-step plan; the output becomes the input to a tool call, so structural correctness matters more than prose quality."

If the surrounding code gives you a hint about the user (function name like `meeting_summary_for_sales_reps`, prompt language like "for an enterprise reader", a route like `/api/v1/support/answer`), use it. If genuinely unclear, write "Likely user: ..." and pick the most plausible one — flag it in the rationale for the reader to correct.

**Sentence 3 — what makes a good answer here, in user-impact terms.** Not "respects the JSON schema" — that's a constraint, not a quality bar. Things like:
- "A good summary calls out blockers and decisions, not just what was said."
- "A good answer cites sources the user can click through to verify."
- "A good extracted record only includes fields explicitly stated; missing fields are null, never invented."

### 2. `constraints` — deterministic rules the output must obey

Each constraint:
- `kind`: `schema | length | format | refusal | citation | other`
- `description`: a precise rule a parser/regex/schema-check can verify. "Output must be valid JSON matching MeetingSummary schema with non-empty `action_items` list."
- `enforcement`: `deterministic` if a parser/regex/schema-check can verify it; `judge` if it requires LLM judgment.

**Sources of constraints:**
- Output schemas (Pydantic, Zod, JSON Schema, dataclass) in the surrounding code.
- Explicit instructions in the prompt: "respond in 2 sentences", "always cite sources", "no Markdown fences".
- Refusal conditions: "if the user asks about X, refuse", "do not provide medical advice".
- Format hints: "respond in JSON", "use Markdown", "subject line ≤ 70 characters".
- **Observed production stats** (Path A, when traces are provided): `call_sites[].observed.p95_tokens_out` lower-bounds reasonable length constraints; `observed.refusal_rate` reveals refusal conditions the prompt didn't state explicitly. Use these as evidence for constraints — don't invent constraints from observed numbers alone, but use them to corroborate.

**Prefer `deterministic` over `judge` when the rule is mechanical.** Reserve `judge` constraints for things only judgment can verify (faithfulness, tone, helpfulness). The mechanical constraints become deterministic graders downstream and *do not* count as failure modes — they're cheaper checks at runtime, no judge drift.

## Important

- The intent is for the *next* synthesis step to lean on. Write it for that consumer, not for a human reading a doc. Be specific.
- If a constraint is implicit in the schema but not stated in the prompt (e.g. the function returns a Pydantic `Deal` model with required fields), it's still a constraint — extract it.
- Don't stuff the intent with information that should be a constraint. Intent is about *purpose and quality*; constraints are about *mechanical rules*.
