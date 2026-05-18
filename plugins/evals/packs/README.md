# packs/

A pack is a high-level concern bundle that contributes failure modes at step 4 of synthesis. The orchestrator engages packs at step 0.5 based on signals from step 0 (`analyze_product.md`), runs each pack's interview against the user (skipping questions already answered by the product analysis), and then invokes each pack's failure-synthesis prompt to produce contributions that get merged with the baseline at step 4.6.

## Bundled packs

| Pack | Tier hint | Scope |
| --- | --- | --- |
| [`quality`](quality/) | free | Output correctness for the user — faithfulness, helpfulness, calibration, audience fit, schema/format. Always-on; the eval baseline. |
| [`security`](security/) | addon | Safety, regulatory compliance (HIPAA / GDPR / EU AI Act / PCI / FedRAMP / CCPA / FERPA / state laws), PII / secret handling, adversarial robustness, fairness. One umbrella; the interview narrows to what actually applies. |
| [`reliability`](reliability/) | included | Cost regressions, latency regressions, output variance, fallback hygiene. Budgets are anchored to `observed.*` stats from ingested traces. |
| [`brand`](brand/) | addon | Voice, tone, persona consistency, banned terms, competitor handling, AI-generated disclosure. |

## Anatomy of a pack

```
packs/<pack_id>/
  pack.yaml         # manifest — see contract/pack.schema.json
  interview.md      # questions Claude asks the user at step 0.5, with per-question
                    # pre-fill rules pointing at step-0 artifacts so questions already
                    # answered by code analysis are skipped
  failures.md       # how to produce failure modes from the interview answers; runs at step 4
  README.md         # optional — operator-facing notes
```

### `pack.yaml`

See [`../contract/pack.schema.json`](../contract/pack.schema.json) for the full schema. Required fields: `id`, `name`, `version`, `description`, `contract_version: 1`, `interview_prompt`, `failure_prompt`. Important optional fields:

- `tier_hint` — informational metadata for downstream commercial gating. **The orchestrator and validator never enforce this**; your product does.
- `applies_when.auto_signals` — human-readable conditions checked against step-0 artifacts. When one or more match, the pack is recommended on by default; the user can still toggle.
- `default_layer_distribution` — soft target for how the pack's contributions distribute across A/B/C layers. The audit at step 4.7 uses this to surface under-coverage.
- `contributes_compliance_tags` — the full menu of control IDs (`EU-AI-Act.Art-13`, `HIPAA-164.502`, etc.) the pack *may* attach. The runtime subset chosen by the interview narrows this set.
- `dependencies` / `conflicts` — other pack ids this pack assumes / refuses. Validator enforces.

### `interview.md`

The load-bearing artifact. Each question declares **pre-fill rules** pointing at step-0 fields (`product_profile.regulatory_context`, `implicit_invariants[].name`, etc.). The orchestrator follows a three-mode protocol for every question:

1. **Auto-fill** when the rules resolve to a confident answer. Record `source: product_profile` (or similar) with the citing `evidence` file. Do not ask the user.
2. **Confirm** when the rules resolve a partial / lower-confidence answer. Ask one confirmation sentence; record `source: product_profile_confirmed`.
3. **Ask** when no signal exists. Record `source: user`.

The interview prints a transparency line per question so the user sees what was inferred vs asked.

### `failures.md`

Read by step 4 after the interview is complete. Produces failure modes in the same YAML form as [`prompts/hypothesize_failures.md`](../prompts/hypothesize_failures.md), but with `pack_ids: [<pack_id>]` and `compliance_tags: [...]` set on every entry. Contributions are *additive* to baseline failures — overlaps are resolved at step 4.6 dedup, not in the pack file.

## Pack identity is a tag, not part of failure-mode IDs

Failure mode IDs remain `<call_site_id>::<failure_name>` regardless of which pack contributed. A failure can carry multiple `pack_ids` (e.g. `ai_disclosure_omitted` is both `brand` and `security`). The only exception is the rare "conflict suffix" case at step 4.6 where two packs propose the same name with materially different rubrics — see SKILL.md § Step 4.6.

## User-supplied packs

Drop a `pack.yaml` + `interview.md` + `failures.md` under `<repo>/.evals-packs/<pack_id>/` and the orchestrator discovers it at step 0.5. User packs with the same `id` as a bundled pack **override** the bundled version. Each pack is content-hashed (SHA-256 of pack.yaml + interview.md + failures.md, first 16 hex chars) and recorded in `pipeline.packs[].content_digest` so re-runs detect when a pack itself has changed.

## Validating packs

The validator checks pack manifests against `contract/pack.schema.json`, then enforces global pack invariants:

```bash
python3 validate.py --bundle evals/             # includes pack-resolution + dependency checks
python3 validate.py --bundle evals/ --pack security   # filter + compliance-tag matrix
```

`--pack <id>` is the lightweight compliance-review surface: see exactly which failures and graders carry the pack and which control IDs they collectively cover.
