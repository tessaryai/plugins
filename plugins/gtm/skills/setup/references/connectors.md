# Connector detection

Setup step 1. The goal is a short, true table of what this session can use. Detection is a hint for the questions in step 2, not a promise: the preflight of each skill checks again at run time.

## How to detect

1. Run ToolSearch keyword queries, a few terms each, and keep the tool names it returns. Tool names carry a server prefix that differs per session (for example `mcp__<id>__notion-fetch`). Use the names ToolSearch returns.
2. If the session has a connector status tool (search `connectors status`), call it once. It can show connectors that exist but are turned off or need auth.
3. For each kind found, make one cheap read call to prove auth works (table below). Read the tool's schema first. If the call fails with an auth error, the status is `auth error`; give the fix and do not try to re-authorize.
4. Never call a write or send tool during detection.

| Kind | ToolSearch query | Signs it is there | Cheap read |
|---|---|---|---|
| Notion (required) | `notion-search notion-fetch notion-query-data-sources notion-create-pages notion-update-page notion-create-database notion-update-data-source` | tools named `notion-*` | `notion-search` for any short word, limit small |
| Email: Gmail | `gmail search threads get_thread send_message` | `search_threads`, `get_thread` on a Gmail server | search one thread `in:sent` |
| Email: Outlook | `outlook mail messages` | Outlook or Microsoft 365 mail tools | list one sent message |
| Calendar: Google | `calendar list_events` | `list_events`, `list_calendars` | list calendars |
| Calendar: Outlook | `outlook calendar events` | Outlook calendar tools | list one event |
| LinkedIn: Claude in Chrome | `claude-in-chrome tabs_context navigate` | `mcp__claude-in-chrome__*` tools | `tabs_context_mcp` only; do not open LinkedIn here. Any reply that is not an error (including "no tab group yet") counts as found. The LinkedIn sign-in is checked at run time. |
| Meetings: Fathom | `fathom list_meetings` | `list_meetings`, `get_meeting_transcript` | list one meeting |
| Meetings: Granola | `granola meetings notes` | Granola tools | list one item |
| Meetings: Fireflies | `fireflies transcripts` | Fireflies tools | list one transcript |
| Meetings: Otter | `otter transcripts` | Otter tools | list one item |
| Notify: Slack | `slack send_message search_channels` | `slack_*` tools | search one channel by name |
| Notify: push | `select:PushNotification` | the `PushNotification` tool | none (do not send a test unless the user asks). The tool is often missing in subagent, headless and cloud runs. If it is not found, ask whether to use Slack or no notifications instead; if the user keeps push, say that BLOCKED alerts appear only in the run report when the tool is missing. |
| Import: HubSpot | `hubspot contacts companies deals` | HubSpot tools | list one contact |
| Import: Pipedrive | `pipedrive persons deals` | Pipedrive tools | list one person |
| Import: Attio | `attio records objects` | Attio tools | list objects |
| Outreach: Gojiberry, lemlist, Instantly, Apollo | `<tool name> campaigns` | tools named for the vendor | list one campaign |
| Enrichment: Exa | `exa web_search` | `web_search_exa` or similar | none needed |
| Enrichment: Apollo, Hunter, other | `apollo people`, `hunter email`, `enrich person company email` | vendor tools, or any people or company search tools | none; enrichment spends credits, so never call it here |
| Scheduling | `scheduled-tasks create_scheduled_task list_scheduled_tasks` | `create_scheduled_task` | `list_scheduled_tasks` |

## Without a connector

Claude Code only. In Cowork (or when `python3` is missing) skip this section: a tool without a connector is `not found`, with the fix "connect a connector for <tool>, or run this routine from Claude Code" (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`, Cowork).

A tool with no connector can still work through the read-only API client when it has an entry there:

```
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py tools
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py has-secret <secret name>
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py <tool> check
```

`check` exit 0 = ok, 2 = blocked (no key or the key was refused). If the key is not saved, give the user the `set-secret` command for that secret name (absolute plugin path filled in) and ask them to run it in their own terminal.

Tools with neither a connector nor an API entry (for example Granola, Otter, Exa without a connector) are `not found`; the fix is "add the <tool> connector in Claude settings".

## Show the result

```
| Kind | Tool | Status | Note |
|---|---|---|---|
| Notion | Notion connector | found | required |
| Email | Gmail | found | |
| LinkedIn | Claude in Chrome | not found | install the Claude in Chrome extension to use LinkedIn |
| Meetings | Fathom | auth error | reconnect Fathom in Claude settings |
```

Keep it to what was found or what the user might want. Do not list every vendor as `not found`.
