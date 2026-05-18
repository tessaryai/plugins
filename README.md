# Tessary plugins

Claude Code plugins from [Tessary AI](https://tessary.ai) — drop-in tooling for teams building with LLMs.

## How to use

In any Claude Code session, add this marketplace and install a plugin:

```
/plugin marketplace add tessaryai/plugins
/plugin install <plugin-name>@tessary
```

To update later:

```
/plugin marketplace update tessary
```

## Plugins

- [evals](#evals) — synthesize a production-grade eval pipeline for any LLM-using product.

### evals

Point `evals` at a repo and it builds you a calibrated eval pipeline end-to-end. It discovers LLM call sites in the codebase, ingests OpenTelemetry GenAI traces if you have them, runs concern-bundle "packs" (quality, security, reliability, brand) to hypothesize failure modes, clusters those into a taxonomy, and emits one grader per failure mode — each with a judge prompt, rubric, and adversarial self-tests. The output lands in `evals/` alongside a self-contained `index.html` viewer you can open directly.

Install:

```
/plugin install evals@tessary
```

Then in a Claude Code session, run `/synthesize-graders` or ask Claude to "synthesize evals for this repo."

See the [plugin README](./plugins/evals/README.md) for flags, pack details, and validator usage.
