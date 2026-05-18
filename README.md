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

- [evals](#evals) — generate a calibrated eval suite for your LLM product.

### evals

Point `evals` at your repo and it generates a complete eval suite for your LLM features: one grader per failure mode (judge prompt, rubric, self-tests), plus a visual report you can open in your browser. Have production traces? Hand them in and graders get calibrated against real data.

```
/plugin install evals@tessary
```

Then run `/evals:synthesize-graders` in a Claude Code session, or just ask Claude to "synthesize evals for this repo."

See the [plugin README](./plugins/evals/README.md) for flags, packs, and validator usage.

## License

MIT — see [LICENSE](./LICENSE).
