# brand pack — interview

Skip every question that step 0 already answered. Many brand signals live in frontend copy, marketing files, and product naming — `analyze_product.md` will have surfaced these into `product_profile.brand_voice_signals`.

## How to run

Same pre-fill protocol.

## Q1.voice — What is the brand voice?

**Pre-fill rules.** `product_profile.brand_voice_signals[].signal` is the canonical source. Each entry with non-empty `evidence` is a confirmed voice descriptor. Combine multiple signals into one summary phrase.

If `brand_voice_signals` is empty: ask.

**Question (only if not pre-filled).**

> "How would you describe the brand voice in 2–4 adjectives? Examples: 'warm and concise'; 'formal and clinical'; 'playful, technical, never condescending'."

**Why it matters.** Drives Layer B tone/voice graders. Without an explicit voice descriptor, a generic 'helpful and harmless' baseline produces low-value graders.

## Q2.banned_phrases — Are there banned words or phrases?

**Pre-fill rules.** Inspect for any of: a `banned_words.json`, `style_guide.md`, `bad_words.py`, a profanity-filter library in dependencies, or invariants named `no_*` (e.g. `no_competitor_recommendations`). If found, pre-fill the extracted list and confirm completeness.

Otherwise ask. If user says 'none', record `{answer: []}`.

**Question (only if not pre-filled or partial).**

> "Are there words, phrases, or topics the LLM must never produce? Common categories: profanity, competitor names, marketing superlatives ('revolutionary', 'synergy'), internal jargon, deprecated product names, religious / political content."

**Why it matters.** Layer A deterministic banned-term grader.

## Q3.competitors — Are there competitors to never name or recommend?

**Pre-fill rules.** Inspect marketing copy for any competitor mentions; usually competitors are *not* named, but the absence is the signal. Look for invariants named `no_competitor_*`. Otherwise: ask.

**Question (when ambiguous).**

> "List competitors the LLM should never recommend, mention favorably, or compare to (unless explicitly asked by the user). Or pass if competitor handling isn't a concern for this product."

**Why it matters.** Layer B grader for competitor handling. A grader without an explicit competitor list defaults to "any large-vendor name" and produces noisy results.

## Q4.persona — Does the product have a named persona?

**Pre-fill rules.** Inspect for a persona name in system prompts (`You are <Name>...`), in frontend chat avatars / labels, or in marketing copy. If found, pre-fill the name and confirm.

**Question (only if not pre-filled).**

> "Does the product have a named AI persona (e.g. 'Penny', 'Atlas', a branded assistant name)? If yes, what name(s), and on which surfaces does it appear?"

**Why it matters.** Triggers persona-consistency failures (turn N introduces itself as 'Penny'; turn N+5 calls itself 'the assistant'). Skip when there's no persona.

## Q5.tonal_surfaces — Do different surfaces have different tonal requirements?

**Pre-fill rules.** Look at `product_profile.user_types[].surface` — multiple distinct surfaces (e.g. `in-product chat` + `marketing email` + `internal admin panel`) imply tonal variation. Confirm.

**Question (when ambiguous).**

> "Does the tone vary across surfaces? Examples: in-product chat is warm and brief, marketing email is more polished, internal admin panel is dry and technical. If yes, sketch the differences."

**Why it matters.** Layer B tone graders that don't account for surface produce false positives on surfaces that legitimately need a different voice.

## Q6.disclosure — Is AI-authorship disclosure required?

**Pre-fill rules.** Cross-reference with `security` pack's Q6 — if security/Q6 answered `yes`, propagate. Otherwise inspect frontend copy for "AI-generated", "powered by AI", "this is an automated message", or similar. If found: pre-fill `yes`.

**Question (only if not pre-filled).**

> "Should outputs be labelled as AI-generated, either by regulation (EU AI Act, CA AB-2013, CO AI Act) or by product policy?"

**Why it matters.** Layer A deterministic check for disclosure-phrase presence on user-facing outputs. Often shared with the security pack — that's expected and step 4.6 dedup handles the overlap.

## Output

```yaml
packs:
  - id: brand
    interview_answers:
      voice: {answer: "warm, concise, never marketing-y", source: product_profile, evidence: "frontend/copy.ts, marketing/voice.md"}
      banned_phrases: {answer: ["revolutionary", "synergy", "leverage", "best-in-class"], source: code, evidence: "style_guide.md"}
      competitors: {answer: ["Acme Corp", "Initech"], source: user}
      persona: {answer: {name: "Penny", surfaces: ["in-product chat"]}, source: code, evidence: "src/agent/prompt.py"}
      tonal_surfaces: {answer: true, source: product_profile}
      disclosure: {answer: false, source: user}
```
