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

## Connect Claude Code to your instance

Not in this release. `/tessary:connect` — which registers Tessary's MCP tools (read-only: cases,
findings, traces, and spans) into this Claude Code session — ships in a follow-up release of this
plugin. Until then, follow the **Client configuration** steps in
[the MCP server docs](https://github.com/tessaryai/tessary/blob/main/docs/reference/mcp-server.mdx)
to register it by hand.

## License

MIT — see `LICENSE`.
