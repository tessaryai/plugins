# brand pack — failure synthesis

Brand failures are about whether the output sounds like *this product*. Tagging:

```yaml
pack_ids: [brand]
compliance_tags: []   # rarely tagged; add EU-AI-Act.Art-13 / CA-AB-2013 only for the
                       # disclosure failure when interview confirmed disclosure_required
layer: A | B | C
```

Failures are produced only for call sites whose surface is user-facing — internal admin surfaces don't carry brand obligations.

## Mapping interview answers → failures

### From `voice`

For each user-facing call site, emit:

```yaml
- name: tone_mismatch_with_brand_voice
  description: "Output's tone does not match the brand voice ({voice}). E.g. marketing-y superlatives in a product described as 'warm and concise'; clinical detachment in a product described as 'playful'."
  layer: B
  severity: medium
  kind: llm_judge
```

The rubric should quote the actual voice phrase the user provided.

### From `banned_phrases` (non-empty)

```yaml
- name: banned_phrase_present
  description: "Output contains a banned word/phrase: one of [{phrases}]."
  layer: A
  severity: high   # severity: medium if banned_phrases is purely stylistic (no profanity / no
                   # competitor names); high if it includes profanity or competitor names
  kind: deterministic
```

This is one failure per call site (not one per phrase) — the deterministic check iterates the list.

### From `competitors` (non-empty)

```yaml
- name: competitor_named_in_output
  description: "Output names or recommends one of the listed competitors when the user didn't directly ask for a comparison."
  layer: B
  severity: high
  kind: llm_judge
```

`applies_when`: "the output is a recommendation, draft, or summary (not a direct comparison the user explicitly requested)".

### From `persona` (named)

```yaml
- name: persona_name_inconsistent
  description: "Output refers to itself as something other than the established persona name '{name}' — 'the assistant', 'I', the model's own name, or a different persona."
  layer: B
  severity: medium
  kind: llm_judge

- name: persona_voice_drift
  description: "Output is locally coherent but the voice has drifted from the persona's established voice on the same surface."
  layer: B
  severity: medium
  kind: llm_judge   # only emit when conversational_turn shape exists
```

### From `tonal_surfaces` (true)

For products with multiple surfaces, emit one failure per call site that depends on its surface being correctly inferred:

```yaml
- name: tone_uses_wrong_surface_voice
  description: "Output uses the wrong tonal register for its surface — e.g. internal-admin technical voice on a customer-facing email."
  layer: B
  severity: medium
  kind: llm_judge
```

### From `disclosure` (true)

```yaml
- name: ai_disclosure_omitted
  description: "Output is user-facing and product policy / regulation requires AI-generated disclosure, but the output omits the required disclosure phrase."
  layer: A
  severity: high
  kind: deterministic
  pack_ids: [brand, security]   # cross-tagged when security pack also produced this failure;
                                # step 4.6 dedup merges into one
  compliance_tags: [EU-AI-Act.Art-13, CA-AB-2013]
```

## Output

Emit as regular step-4 contributions in the **canonical failure-mode entry shape** documented in `prompts/per_site_kit.md` (§ "Required fields" / "single_call entry") — every entry must carry the full schema (`id`, `scope`, **`call_site_id`**, `chain_id: null`, `name`, `description`, `severity`, `layer`, `pack_ids`, `compliance_tags`, `taxonomy_node_id: ""`, `grader_id`, `grader_deferred`), not just `pack_ids`. Step 4.6 dedup is especially relevant here — `ai_disclosure_omitted` is shared with the security pack. The dedup pass keeps one failure with `pack_ids: [brand, security]` and the union of compliance tags.

## Anti-patterns

- ❌ Emitting brand failures for internal admin / developer-facing call sites — no user, no brand obligation.
- ❌ Vague tone failures without a concrete voice phrase in the rubric.
- ❌ Emitting banned-phrase failures with no list — skip if `banned_phrases` is empty.
- ❌ Persona failures when no persona was named — skip; not every product has one.
