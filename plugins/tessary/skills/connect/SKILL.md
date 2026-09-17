---
name: connect
description: Register your self-hosted Tessary instance's MCP tools (read-only cases, findings, traces, and spans) into Claude Code. Use when the user says "connect to tessary", "link this repo to my tessary instance", "set up the tessary MCP server", or invokes /connect.
---

# connect — register a self-hosted Tessary instance's MCP tools

Unlike a hosted platform, there is no OAuth or device-code handshake here: a self-hosted,
open-edition Tessary instance authenticates MCP with an **admin-scoped project API key**
(`tsy_a_...`) that a human mints once, by hand, in their own instance's UI. **You never fetch,
construct, print, or type this token yourself** — the human runs this skill's helper script
interactively and pastes the token into a hidden prompt it shows them. Your job is to tell them
where to get the token and run the script; the raw value never appears in this conversation, a
shell command, or shell history.

## Resolve the plugin path once

```bash
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(find ~/.claude -name SKILL.md -path '*/tessary/skills/connect/*' 2>/dev/null \
  | xargs -I{} dirname {} | xargs -I{} dirname {} | xargs -I{} dirname {} \
  | sort -V | tail -1)}"
echo "PLUGIN=$PLUGIN"
```

`platform.py` next to this skill is the whole client: credential storage, MCP registration, and a
connectivity check, all in one stdlib-only file. The stored credential is keyed by repo root.

## Flow

### 1 — Tell the user where to get a token, then have them run `link`

Tell the user, plainly:

> Mint an admin-scoped MCP token in your Tessary instance under **Settings → MCP tokens → New
> token**. It's shown once in plaintext there.

Then run:

```bash
python3 "$PLUGIN/platform.py" link
```

This prompts **in the user's own terminal** for the instance origin (default `http://localhost`,
matching `setup.md`'s own default) and the token, using a hidden/non-echoed input for the token.
**You do not see, ask for, or relay the token value** — the human types it directly into the
prompt this command shows. If they're running headless (CI, no interactive terminal), they can
instead export `TESSARY_ORIGIN` and `TESSARY_TOKEN` before running the same command; either way,
the token never appears in your conversation.

Credentials land in `~/.config/tessary/credentials.json` (`chmod 600`), never in the repo tree.

### 2 — Verify the credential works

```bash
python3 "$PLUGIN/platform.py" status
```

Calls the stored instance's `/mcp` endpoint with the stored token and reports the server name and
version. A `401` means the token was rejected — mint a fresh one and re-run `link`. A `404` most
often means the instance has `TESSARY_AUTH_DISABLED` set, or the origin is wrong.

### 3 — Register the MCP server

```bash
python3 "$PLUGIN/platform.py" mcp-add --run
```

This runs `claude mcp add --transport http --scope local tessary <origin>/mcp --header
"Authorization: Bearer <token>"` **from the script**, never as a command you construct or print
with the real token. **`local` scope** keeps the registration (and the token) private to this
repo in `~/.claude.json`, never in a committed file. Re-running refreshes the token: it removes
any prior registration and re-adds.

Without `--run`, the same command prints a **masked** preview only — never hand-assemble this
with the real token, that leaks it into shell history.

If the `claude` CLI isn't on PATH, the script fails fast without touching any existing
registration and says so — fix PATH and re-run.

### 4 — Hand off

**The MCP tools are NOT usable this turn** — they load only after the client reloads its MCP
config. Say so plainly:

```
Connected to <origin>. ✅

⚠️ Reconnect (or restart) this session once so the Tessary tools load — they are not available yet.

After you reconnect, just ask me things like:
  • "what cases are open?"          → I list them, worst-first
  • "show me the traces for <call site>"
  • "what's the root cause of <case>?" → inline once a report has run

(This surface is read-only: nothing I call writes a row, spends a token, or starts an agent run.)
```

## Constraints

- **Never fetch, print, or construct a shell command carrying the raw token.** The user pastes it
  into `platform.py link`'s own hidden prompt, or exports it as an env var in their own shell —
  never as an argument you type or a value you echo back.
- **Confirm the target repo** before linking if the cwd is ambiguous — the credential is keyed by
  repo root.
- **To disconnect a repo**, run `python3 "$PLUGIN/platform.py" unlink` — it tears down both the
  local MCP registration and the stored credential together. The token still exists in the
  Tessary instance; revoking it there is a separate, user-driven step under Settings → MCP
  tokens.
- **The MCP surface writes nothing.** Resolving a case and triggering root-cause analysis are UI
  actions on the instance itself, not tools — do not look for one.
- **Read `tools/list`, not this file, as the tool catalogue.** The exact tool set is documented in
  `docs/reference/mcp-server.mdx` in `tessaryai/tessary` and may grow; this skill's job ends at
  registration.
