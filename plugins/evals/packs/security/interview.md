# security pack — interview

Run this interview after step 0 (`analyze_product.md`) has produced `product_profile`, `implicit_invariants`, and `invariant_coverage`. **Skip every question that step 0 already answered with confidence.** This document declares per-question pre-fill rules so you can confidently elide the question rather than nag the user.

## How to run

For each question below:

1. Inspect the **pre-fill rules**. If they resolve to a confident answer, set that as the answer and **do not ask the user**. Record the answer in `pack.interview_answers.<question_id>` with `source: product_profile` (or `invariants`) and `evidence: <file path>`.
2. If the rules resolve to a *partial* answer (medium confidence, weak evidence), present the inferred answer to the user as a confirmation: *"I see X from `<file>` — does that cover everything you need here?"* Record `source: product_profile_confirmed` if they accept.
3. Only ask the full open question when no signal exists. Record `source: user`.

Print one line per question:

```
[security/Q1.regulations] auto-filled from product_profile.regulatory_context: [HIPAA, GDPR] (evidence: requirements.txt, frontend/copy.ts)
[security/Q3.threat_model] asking: ...
```

This gives the user visibility into what was inferred vs asked, and a chance to correct.

## Q1.regulations — Which regulations apply?

**Pre-fill rules.** Use `product_profile.regulatory_context[].regime` directly. Each `regime` entry with non-empty `evidence` becomes a confirmed regulation. If `regulatory_context` is empty AND `product_profile.notable_dependencies` includes any of `presidio`, `hipaa`, `gdpr`, `stripe`, `plaid`, `langfuse-hipaa` → infer the matching regulation and ask the user to confirm.

If both are silent: ask.

**Question (only if not pre-filled).**

> "Which regulatory regimes does this product need to comply with? Multi-select (or 'none'): HIPAA, GDPR, CCPA, EU AI Act, PCI-DSS, SOX, FERPA, FedRAMP, SOC 2, NIST AI RMF, California AB-2013, Colorado AI Act, or other (specify)."

**Why it matters.** Narrows the `contributes_compliance_tags` set on every security-pack failure. A pack run with `[HIPAA]` produces graders tagged with HIPAA controls only — no EU AI Act tags pollute the bundle.

## Q2.data_sensitivity — What sensitive data flows through the LLM?

**Pre-fill rules.** Use `product_profile.data_sensitivity[].kind` directly. Each non-empty `kind` is a confirmed sensitivity category. Cross-check with table-name evidence from `analyze_product.md`'s "where to look" passes — e.g. tables named `patient_visits`, `payment_methods`, `student_records`, `consent_log` are strong implicit signals when the explicit field is silent.

If empty AND no table-name signal: ask.

**Question (only if not pre-filled).**

> "Which data sensitivity categories pass through any LLM call site? Multi-select: PII (names, emails, addresses, phone numbers), PHI (medical, health), financial (PAN, account numbers, balances), authentication secrets (passwords, API keys, tokens), trade secrets / IP, multi-tenant customer data, child-safety-relevant content, none."

**Why it matters.** Drives Layer C `pii_leakage` / `secret_leakage` / `tool_arg_exfiltration` failures and which compliance tags apply per call site.

## Q3.threat_model — Where does adversarial input come from?

**Pre-fill rules.** Inspect call sites:
- Any call site whose system prompt or surrounding code shows user-supplied content (a `user` message, an HTTP request body, a webhook payload) flowing into the prompt → `external_user_input: true`.
- Any call site that reads retrieved documents from a user-shared or third-party source → `external_retrieved_content: true`.
- Any call site that ingests outputs from another LLM call before producing its own → `chained_llm_input: true`.

`internal_abuse` and `supply_chain` cannot be inferred from code. Always ask, but pre-fill the externally-derivable parts.

**Question (only if not all parts are pre-filled).**

> "Threat model — which sources of adversarial input is this product exposed to? Multi-select: external user input, content retrieved from user-shared / third-party sources, chained LLM output (one model feeds another), internal abuse by authenticated users, supply-chain (third-party prompts / SDKs / fine-tunes)."

**Why it matters.** Determines which prompt-injection / jailbreak surfaces deserve graders. A purely internal admin tool with no user-supplied input doesn't need user-input injection graders; a chatbot does.

## Q4.geography — Which markets does the product serve?

**Pre-fill rules.** Inspect `product_profile.regulatory_context` (GDPR → EU; CCPA → California; HIPAA → US; FERPA → US schools; LGPD → Brazil). Inspect copy / localization files (`en.json`, `fr.json`, etc.) for languages. Inspect domain references in marketing copy.

If `regulatory_context` is non-empty: pre-fill the implied geographies and confirm.
If silent: ask.

**Question (only if not pre-filled).**

> "Which geographies does the product serve users in? Multi-select: United States, EU/EEA, UK, Canada, Brazil, India, China, Japan, ANZ, Middle East, global, other (specify)."

**Why it matters.** Geography narrows the compliance tag set and triggers region-specific failures (e.g. EU markets enable EU AI Act Art. 13 disclosure failure).

## Q5.fairness_axes — Are there protected demographic axes outputs must not vary on?

**Pre-fill rules.** Strong implicit signal when `product_profile.user_types[].surface` indicates direct consumer use AND `regulatory_context` includes EU AI Act, FedRAMP, or "anti-discrimination" appears in any copy file. Otherwise no good signal in the code — ask.

**Question (when ambiguous).**

> "Are there protected demographic axes that outputs must not vary on (race, gender, age, disability, religion, national origin, dialect, accented English, ZIP-code-as-proxy)? If yes, which?"

**Why it matters.** Triggers fairness/bias failures (paired-input differential testing). Skip the failure category entirely when the answer is "no" to avoid noise.

## Q6.disclosure_required — Does the product require AI-generated disclosure?

**Pre-fill rules.**
- `regulatory_context` includes EU AI Act → yes (Art. 13/52).
- `regulatory_context` includes California AB-2013 → yes (for training data; the output disclosure question is separate, still ask).
- `regulatory_context` includes Colorado AI Act → yes.
- `product_profile.user_types[].surface` is in `["consumer chat", "in-product chat", "marketing"]` AND no explicit signal → recommend yes, confirm.

Otherwise ask.

**Question (when not pre-filled).**

> "Does any user-facing output need to be labelled as AI-generated (per EU AI Act Art. 13, California AB-2013, Colorado AI Act, or product policy)?"

**Why it matters.** Triggers a deterministic Layer A check for disclosure-phrase presence on relevant call sites.

## Output

The orchestrator writes the resolved Q&A to `pipeline.packs[].interview_answers`:

```yaml
packs:
  - id: security
    interview_answers:
      regulations:
        answer: [HIPAA, GDPR]
        source: product_profile
        evidence: "requirements.txt: presidio; frontend/copy.ts: HIPAA disclaimer"
      data_sensitivity:
        answer: [PHI, PII]
        source: product_profile
        evidence: "db/migrations/0007_patient_visits.sql"
      threat_model:
        answer: {external_user_input: true, external_retrieved_content: false, chained_llm_input: true, internal_abuse: false, supply_chain: false}
        source: user
        evidence: "user reply"
      geography: {answer: [United States, EU/EEA], source: product_profile, evidence: ...}
      fairness_axes: {answer: [race, gender, age], source: user, evidence: ...}
      disclosure_required: {answer: true, source: product_profile, evidence: ...}
```

The `failures.md` prompt reads this block and produces only the failures that match.
