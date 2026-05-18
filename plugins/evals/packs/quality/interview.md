# quality pack — interview

The quality pack runs by default (it *is* the eval baseline). The interview narrows what "quality" means for *this* product. Skip every question that step 0 already answered.

## How to run

Same protocol as `security/interview.md`: pre-fill from `product_profile` and `implicit_invariants` where possible, confirm partial answers, ask only when no signal exists.

## Q1.user — Who is the user and what do they need?

**Pre-fill rules.** `product_profile.user_types` is the canonical source. Each entry has `role`, `surface`, `constraints` — together they define the user. When all three are populated for at least one user type, this question is fully answered.

If `user_types` is empty: ask.

**Question (only if not pre-filled).**

> "Who is the primary user of the LLM output? Describe their role, the surface they interact on, and any constraint that shapes what a 'good' answer means (time pressure, expertise level, regulatory exposure)."

**Why it matters.** Drives Layer B helpfulness and audience-fit failures. A grader for a senior engineer is different from a grader for an end consumer.

## Q2.domain — What domain expertise is required?

**Pre-fill rules.** `product_profile.domain` provides the high-level signal. Cross-check `implicit_invariants` for domain-specific terms (`medical_advice`, `legal_disclaimer`, `tax_jurisdiction`, `code_correctness`). When `domain` is one of `medical`, `legal`, `financial`, `developer tooling`, `tax`, `pharmaceutical`, `clinical research` → confirm as the domain.

If `domain` is generic ("B2B SaaS", "consumer app") or absent: ask.

**Question (only if not pre-filled).**

> "What level of domain expertise is the LLM expected to demonstrate? Options: general-knowledge (no specialized expertise required), domain-aware (correct vocabulary, doesn't make beginner mistakes), domain-expert (correct enough that a domain professional would not redo the work). Name the domain if applicable (medical / legal / financial / engineering / scientific / other)."

**Why it matters.** Domain-expert outputs trigger faithfulness graders against authoritative sources; general-knowledge outputs don't. Setting this wrong inflates the grader set with checks that aren't actionable.

## Q3.cost_of_wrong — What does a wrong answer cost the user?

**Pre-fill rules.** Strong implicit signal from:
- `product_profile.data_sensitivity` includes PHI / financial → cost is `high` (harm).
- `regulatory_context` non-empty → cost is at least `medium` (compliance exposure).
- `user_types[].constraints` includes "regulated", "high-stakes", "audited" → cost is `high`.
- Otherwise: low signal; ask.

**Question (when ambiguous).**

> "What does a meaningfully wrong answer cost the user? Options: annoyance only (user notices, re-prompts, moves on), lost trust / churn (user stops using the feature), lost revenue / time (user makes a wrong business decision), harm (user takes a wrong action with real-world consequences — medical, financial, legal, safety)."

**Why it matters.** Calibrates severity distribution. A "harm" product gets a Layer B set skewed toward `high` severity; an "annoyance" product gets a more relaxed distribution.

## Q4.faithfulness_signal — Are citations / sources required in outputs?

**Pre-fill rules.** Any call site with `shape: rag_answer` → citations expected, pre-fill `yes`. Any system prompt mentioning "cite", "source", "reference" → pre-fill `yes`. Otherwise default `no` and confirm.

**Question (when ambiguous).**

> "Should outputs cite their sources (retrieved docs, internal knowledge, etc.)? If yes, in what format?"

**Why it matters.** Triggers Layer A citation-structure and Layer B citation-grounding failures.

## Q5.format_strictness — How strict is the output format?

**Pre-fill rules.** Any system prompt that mentions JSON / schema / structured output → `strict`. Free-form prose endpoints → `loose`. Mixed → ask.

**Question (when ambiguous).**

> "How strictly is output format enforced downstream? Options: strict (downstream code parses the output; a malformed output crashes), tolerant (downstream is forgiving — extra prose / minor format drift is fine), display-only (output is shown directly to a user; format is a UX concern, not a parser concern)."

**Why it matters.** Strict formats get many more Layer A failures (schema validation, field-presence, enum bounds). Display-only formats lean Layer B (audience-fit).

## Output

```yaml
packs:
  - id: quality
    interview_answers:
      user:
        answer: "Sales reps on email surface, 30s attention between calls"
        source: product_profile
        evidence: "frontend/dashboard.tsx, README.md"
      domain:
        answer: "B2B sales productivity; general-knowledge"
        source: product_profile
      cost_of_wrong:
        answer: lost_revenue
        source: user
      faithfulness_signal:
        answer: false
        source: product_profile
        evidence: "No rag_answer call sites; no 'cite' in any prompt"
      format_strictness:
        answer: tolerant
        source: user
```
