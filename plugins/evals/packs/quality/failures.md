# quality pack — failure synthesis

The quality pack is the baseline. **Most failures produced at step 4 are quality failures** — Layer A/B coverage from `prompts/per_site_kit.md`. This file specifies how to tag them and how to specialize them based on the interview.

## Default tagging

For each baseline Layer A or Layer B failure produced by `per_site_kit.md`:

```yaml
pack_ids: [quality]
compliance_tags: []   # quality contributes_compliance_tags only when interview signals warrant
```

Add `NIST-AI-RMF.MS-2.6` only when `cost_of_wrong` answer is `lost_revenue` or `harm` (a stricter accuracy regime). Add `EU-AI-Act.Art-15` only when the security pack is also enabled (overlap, step 4.6 will dedup the tag set).

## Specialization from interview answers

### From `domain`

| Domain answer | Add these failures (Layer B) |
|---|---|
| medical | `medical_advice_without_disclaimer`, `clinical_guideline_misapplication`, `dosage_or_drug_interaction_fabrication` |
| legal | `legal_advice_without_disclaimer`, `jurisdiction_mismatch`, `cited_case_fabricated` |
| financial | `financial_advice_without_disclaimer`, `figure_fabrication`, `tax_jurisdiction_mismatch` |
| developer tooling | `code_runs_but_does_wrong_thing`, `api_signature_fabricated`, `deprecated_pattern_recommended` |
| scientific | `cited_paper_fabricated`, `claim_misattributes_finding` |

Domain-specific failures get `severity: high` when `cost_of_wrong` is `harm` or `lost_revenue`, else `medium`.

### From `cost_of_wrong`

Calibrates severity distribution:

| Answer | Default severity skew |
|---|---|
| annoyance | mostly `medium` and `low` |
| lost_trust | shift one tier of Layer B to `high` |
| lost_revenue | half of Layer B is `high`; Layer A `medium`+ |
| harm | most of Layer B is `high`; any refusal-condition Layer A is `high` |

### From `faithfulness_signal` (true)

For every `rag_answer` call site (and any other site the user marked needing citations), produce:

```yaml
- name: cited_doc_not_in_retrieval
  description: "Output cites a document identifier that does not appear in the retrieved context for this query."
  layer: B
  severity: high

- name: claim_unsupported_by_cited_doc
  description: "Output cites a document but the claim it cites does not appear in (or contradicts) that document's passages."
  layer: B
  severity: high

- name: citation_format_violation
  description: "Output is missing required citation markers, or uses a format other than the one the system prompt specifies."
  layer: A
  severity: medium
```

Tag with `compliance_tags: [NIST-AI-RMF.MS-2.6]` when present.

### From `format_strictness`

| Answer | Layer A emphasis |
|---|---|
| strict | 5–8 schema/format failures per site (JSON-validity, field-presence, enum bounds, type bounds, no-extra-keys) |
| tolerant | 3–4 (basic shape + critical fields) |
| display-only | 2–3 (length bounds, no-leading-junk) |

### From `user`

Use `user.constraints` to inform Layer B audience-fit failures:

- "30s of attention" → produce `summary_exceeds_attention_span`, `nuance_dropped_for_brevity`.
- "non-technical user" → produce `unexplained_technical_term`, `assumes_prerequisite_knowledge`.
- "regulated industry" → produce `confidence_overstated_in_regulated_claim`.

## Output

Emit contributions as part of the regular step-4 output, in the **canonical failure-mode entry shape** documented in `prompts/per_site_kit.md` (§ "Required fields" / "single_call entry") — every entry must carry the full schema (`id`, `scope`, **`call_site_id`**, `chain_id: null`, `name`, `description`, `severity`, `layer`, `pack_ids`, `compliance_tags`, `taxonomy_node_id: ""`, `grader_id`, `grader_deferred`), not just `pack_ids`. Quality failures dominate step 4.6 dedup as anchors — other packs (security, brand) often merge into the quality failure where there's overlap, since quality is the most common pack and its failure name is usually the most generic.

## Anti-patterns

- ❌ Emitting domain-specific failures (medical, legal) for a generic-domain product.
- ❌ Skipping Layer A coverage even when `format_strictness: display-only` — at least 2 structural checks are needed everywhere.
- ❌ Inflating severity uniformly to `high` when `cost_of_wrong` is `harm` — most failures are still `medium`; only the ones a user would actually be harmed by are `high`.
- ❌ Adding `compliance_tags` to baseline quality failures without an interview signal that warrants them.
