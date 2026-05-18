# evals

A Claude Code plugin that synthesizes a production-grade eval pipeline for an LLM-using product. Point it at a repo (with optional OpenTelemetry GenAI traces) and it discovers LLM call sites, runs concern-bundle "packs" (security / quality / reliability / brand), hypothesizes failure modes across three layers (mechanical, judgmental, adversarial / operational), clusters them into a taxonomy, generates calibrated graders (judge prompts + rubrics + adversarial self-tests), and emits a curatable bundle.

## Output

The skill writes to `evals/` in the target repo:

```
evals/
  pipeline.yaml             product profile, packs, runtime config, call sites,
                            chains, failure modes (with pack_ids + compliance_tags),
                            taxonomy
  graders/*.yaml            one file per grader — judge prompt, rubric, self-tests
                            (with adversarial coverage), _meta provenance + locks
  datasets/*.jsonl          captured-input rows from OTel traces (when provided),
                            one file per call site for replay
  .synth-lock.yaml          content hashes for survivable re-runs
  report.md                 human-readable walkthrough
  index.html                self-contained visual viewer
```

`evals/index.html` is fully self-contained — open it directly, no server needed.

## Usage

In a Claude Code session, type `/evals:synthesize-graders` or ask Claude to "synthesize evals for this repo." The orchestrator walks through a multi-step pipeline (0 → 0.5 → 1 → 2 → 3 → 4 → 4.5 → 4.6 → 4.7 → 5 → 6 → 7 → 8) — see `skills/synthesize-graders/SKILL.md` for what each step does.

Optional flags:

| Flag | Effect |
| --- | --- |
| `--traces <path>` | JSONL of OpenTelemetry GenAI spans (see `examples/sample_traces.jsonl`). Enables Path A ingestion with observed.* stats, source-span backlinks, dataset capture. |
| `--pack <id>` | Force a pack engaged (repeatable). Default packs auto-engage from product signals. |
| `--no-pack <id>` | Force a pack off. |
| `--only <id>` | Targeted regeneration — re-synthesize one grader / call site / chain without re-running steps 0–5. |
| `--force` | Override `_meta.locked_fields` and `human_edited` flags on re-run. Destructive — use only after a deliberate review. |

The viewer's header CTA defaults to `https://evals.tessary.ai`. To point it elsewhere, run `viewer.py` standalone with `--cta-url <url> --cta-label <text>`.

## Packs

Four bundled concern-bundle packs ship by default:

| Pack | Tier hint | Engages by default when |
| --- | --- | --- |
| `quality` | free | Always |
| `security` | addon | `regulatory_context` non-empty, `data_sensitivity` non-empty, or user-supplied content reaches the prompt |
| `reliability` | included | Traces are provided (`observed.*` stats anchor cost / latency budgets) |
| `brand` | addon | `brand_voice_signals` non-empty or user-facing call sites exist |

Each pack is a thin manifest + an interview prompt + a failure-synthesis prompt under `packs/<id>/`. The interview pre-fills answers from the step-0 product analysis (regulations from `regulatory_context`, data sensitivity from migration files, voice from frontend copy, etc.) — Claude only asks the user the questions no signal answered. `tier_hint` is informational for downstream products to gate commercial enablement.

User packs at `<repo>/.evals-packs/<id>/` override bundled packs of the same id.

## Validating output

```bash
python3 validate.py --bundle evals/             # full bundle check
python3 validate.py --bundle evals/ --pack security   # filter + compliance matrix
python3 validate.py evals/graders/<file>.yaml --pipeline evals/pipeline.yaml   # per-file
```

`--bundle` runs every per-file check plus global checks: FM↔grader bijection, chain DAG acyclicity, duplicate IDs, taxonomy reachability, layer A/B/C coverage gates, pack-id resolution, dedup uniqueness, lock consistency.

## Layout

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Orchestrator instructions (the canonical "what does the skill do") |
| `output_format.md` | On-disk shape reference for `evals/` |
| `CHANGELOG.md` | Versioned migration notes for consumers (v0.0.1 → v0.2 → v0.3) |
| `contract/AUTHORING_CONTRACT.md` | Author-orchestrator interface (v2); canonical rule list |
| `contract/grader.schema.json` | Machine-readable grader schema (v2) |
| `contract/pack.schema.json` | Machine-readable pack manifest schema (v1) |
| `validate.py` | Authoritative validator (per-file + `--bundle` + `--pack`) |
| `viewer.py` | Builds `evals/index.html` from the generated YAML |
| `viewer_template/` | HTML + CSS + JS for the viewer (mustache placeholders) |
| `authors/default/` | OSS fallback grader author (bundled markdown procedure, contract v2) |
| `packs/` | Bundled packs — `security`, `quality`, `reliability`, `brand` |
| `prompts/` | Per-step reasoning prompts the orchestrator loads |
| `examples/` | Reference inputs (OTel trace sample) |

## Versions

- **Plugin / pipeline schema**: `0.3.0` (also the `version` field in emitted `pipeline.yaml`)
- **Grader contract**: `v2` (the author/orchestrator interface)
- **Pack contract**: `v1`

See `CHANGELOG.md` for migration notes when upgrading consumer code.

## License

Apache License 2.0 — see `LICENSE`.
