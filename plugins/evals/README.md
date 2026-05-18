# evals

A Claude Code plugin that generates a calibrated eval suite for your LLM product. Point it at your repo and you get graders, datasets, and a visual report — ready to wire into CI.

## Install

In any Claude Code session:

```
/plugin marketplace add tessaryai/plugins
/plugin install evals@tessary
```

## Run

Type `/evals:synthesize-graders` in a Claude Code session, or ask Claude to "synthesize evals for this repo."

Have OpenTelemetry GenAI traces from production? Pass them in for graders calibrated to real data:

```
/evals:synthesize-graders --traces path/to/traces.jsonl
```

## What you get

Everything lands in `evals/` in your repo:

| Path | What it is |
| --- | --- |
| `evals/index.html` | Self-contained visual report. Open it in a browser — no server needed. |
| `evals/report.md` | Human-readable walkthrough of every grader and what it catches. |
| `evals/graders/*.yaml` | One grader per failure mode: judge prompt, rubric, self-tests. Run these against your call sites in CI. |
| `evals/datasets/*.jsonl` | Replayable input rows captured from your traces (when provided). |
| `evals/pipeline/` | The pipeline definition: call sites, failure modes, taxonomy. Read this if you're wiring graders into your own runner. |

## Packs

Failure modes are organized into four bundled packs, each covering one concern area:

| Pack | Covers | Engages when |
| --- | --- | --- |
| `quality` | Correctness, formatting, instruction-following | Always |
| `security` | Prompt injection, PII, regulatory compliance | Your product handles sensitive data or untrusted user input |
| `reliability` | Cost, latency, retries, fallbacks | You provide production traces |
| `brand` | Voice, tone, on-message responses | Your product has user-facing copy |

Packs auto-engage based on what `evals` sees in your repo. To override:

```
/evals:synthesize-graders --pack security --no-pack brand
```

Drop your own pack at `.evals-packs/<id>/` in your repo to extend or override the bundled ones.

## Targeted re-runs

After curating, regenerate one grader without redoing the whole pipeline:

```
/evals:synthesize-graders --only <grader-id>
```

Your edits to grader files are preserved across re-runs. Pass `--force` only after a deliberate review — it overrides edit locks.

## Validating

```bash
python3 validate.py --bundle evals/
```

Runs every check on the generated bundle: failure-mode coverage, schema conformance, dedup uniqueness, lock consistency. Add `--pack <id>` to filter the coverage matrix to one pack.

For per-grader checks during curation:

```bash
python3 validate.py evals/graders/<file>.yaml --pipeline evals/
```

## Viewer

`evals/index.html` is regenerated every run. 

## License

MIT — see `LICENSE`.
