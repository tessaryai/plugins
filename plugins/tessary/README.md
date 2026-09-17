# tessary

A Claude Code plugin for [Tessary](https://github.com/tessaryai/tessary), the open-source
reliability platform for AI agents in production. It self-hosts on your own machine or
infrastructure, monitors every trace, detects issues with classifiers, groups related findings
into cases, and investigates their root cause.

This plugin wraps the two workflows the project already documents at its repo root, so they run
the same way whether a user pastes a bare GitHub URL into an agent or types a slash command here.

## Install

In any Claude Code session:

```
/plugin marketplace add tessaryai/plugins
/plugin install tessary@tessary
```

## Set up Tessary (`/setup`)

```
/setup
```

Installs Tessary, starts it, verifies the frontend is running, and gives you the URL. This is a
thin pointer at the canonical workflow in
[`setup.md`](https://github.com/tessaryai/tessary/blob/main/setup.md) at the root of the
`tessaryai/tessary` repo, not a copy — the two stay in sync by construction.

## Instrument your repo (`/instrument`)

```
/instrument
```

Wires your repo's tracing to Tessary's OTLP endpoint and tags every model-call span with the
`tessary.call_site.id` attribute the platform's tools are keyed on. Also a thin pointer, at
[`instrument.md`](https://github.com/tessaryai/tessary/blob/main/instrument.md).

## Connect Claude Code to your instance (`/connect`)

```
/connect
```

Registers Tessary's MCP tools (read-only: cases, findings, traces, and spans) into this Claude
Code session, scoped locally to this repo. There's no OAuth here — a self-hosted instance
authenticates with an admin-scoped project API key you mint by hand under **Settings → MCP
tokens**. This skill never sees, prints, or constructs a command carrying that token: you paste it
into a hidden prompt run by the plugin's own helper script (`platform.py`), which stores it under
`~/.config/tessary/credentials.json` (`chmod 600`) and registers the server with `claude mcp add
--scope local`.

## License

MIT — see `LICENSE`.
