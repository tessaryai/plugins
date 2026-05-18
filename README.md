# tessary plugins

A Claude Code marketplace hosting Tessary AI's plugins.

## Install

In any Claude Code session:

```
/plugin marketplace add tessary-ai/plugins
/plugin install <plugin-name>@tessary
```

## Plugins

| Plugin | Description |
| --- | --- |
| [`evals`](./plugins/evals) | Synthesize an eval pipeline for any LLM-using product — discovers call sites, hypothesizes failure modes, emits graders, validates, and renders a visual report. |

## Layout

```
.
├── .claude-plugin/marketplace.json   marketplace manifest (name: tessary)
└── plugins/
    └── <plugin-name>/                one directory per plugin
        ├── .claude-plugin/plugin.json
        └── ...
```

## Adding a new plugin

1. Create `plugins/<name>/` with its own `.claude-plugin/plugin.json` and contents (skills, agents, hooks, etc.).
2. Append an entry to `.claude-plugin/marketplace.json`:
   ```json
   { "name": "<name>", "source": "./plugins/<name>", "description": "..." }
   ```
3. Commit and push. Users who have already run `/plugin marketplace add tessary-ai/plugins` can refresh with `/plugin marketplace update tessary` and then `/plugin install <name>@tessary`.
