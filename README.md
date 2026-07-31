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

- [evals](#evals) — connect your repo to evals.tessary.ai and work with your evals from the coding agent.
- [crew](#crew) — a multi-agent dev harness that triages, implements, reviews, and maintains your repo.

### evals

`evals` connects your repo to [evals.tessary.ai](https://evals.tessary.ai): a one-time device link, OTLP trace wiring, native platform tools in Claude Code, and `/evals:instrument` to tag your LLM call sites. From there the platform's observer authors and maintains your eval bundle — graders arrive as draft PRs against your repo, grounded in your real traffic.

```
/plugin install evals@tessary
```

Then run `/evals:connect` in a Claude Code session, or just ask Claude to "connect this repo to tessary."

See the [plugin README](./plugins/evals/README.md) for the full flow.

### crew

`crew` is a multi-agent development harness. Hand it a goal and an orchestrator decides what
needs doing and does it — triaging issues, implementing changes through a deliberative team,
reviewing PRs, responding to review feedback, and keeping docs and knowledge current —
running unattended up to a **review-ready PR** (it never merges; you do). You can also invoke
any single capability directly.

```
/plugin install crew@tessary
```

Then either let it drive — `/crew:run "close out the open bugs"` — or call a primitive
yourself, e.g. `/crew:review-pr 42` or `/crew:triage-bug 17`. Run `/crew:init-config` once to
tune it to your repo. This release is local-first (runs in your own Claude Code session);
GitHub Actions packaging is planned.

See the [plugin README](./plugins/crew/README.md) for the full skill list and configuration.

## License

MIT — see [LICENSE](./LICENSE).
