# notify: slack

## Purpose

Posts one Slack message to the user's chosen channel or DM when a gtm run has something blocked, or when a skill's own rules ask for a notification. Every skill can use it, through `${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`. Chosen when `adapters.notify.kind` is `slack`.

## Tool

The Slack MCP connector. There is no `readonly_api.py` entry.

- Load with ToolSearch, for example `slack send_message search_channels search_users`. Use the names ToolSearch returns and read each schema at run time. Never guess a tool or parameter name.
- Allowed: the send-message tool (one call per run), and the channel and user search tools to resolve the target.
- Forbidden: drafts, scheduled messages, reactions, canvases, creating or joining channels, inviting people, reading channel history or threads, and any message to anyone other than the configured target.

## Target

`adapters.notify.slack_channel` holds the target:

- A channel id (starts with `C` or `G`) or a user id for a DM (starts with `U` or `W`): use it as given.
- A channel name (`#gtm-alerts` or `gtm-alerts`): resolve it with the channel search tool. Use it only when exactly one channel has that exact name.
- A user name or `@name` for a DM: resolve it with the user search tool. Use it only on exactly one exact match.
- Empty, or not resolvable to exactly one target: do not send. Fall back to `PushNotification` (`${CLAUDE_PLUGIN_ROOT}/adapters/notify/push.md`) and add under Needs you: "Set adapters.notify.slack_channel to a channel id or exact channel name."

Do not save a resolved id to config on your own. Suggest it under Needs you, so the next run skips the search.

## Preflight check

Load the tools with ToolSearch. When the target is a name, resolve it now (one search call). Tools found and the target resolved: ok. Do not post a test message unless the user asks.

## Send procedure

1. Wait until the end of the run, after the run log entry is written. Exception: when Notion itself is blocked, send right away and stop (`blocked.md`, Check procedure step 4).
2. Build one message (format below).
3. Call the send-message tool once, to the target. Never send a second message in the same run.
4. If the call fails (auth error, not in channel, tool missing), do not retry through Slack. Fall back to one `PushNotification` with the one-line text from `push.md`, and say in the BLOCKED section that Slack failed and why (status only).

## Message format

Plain text, at most 8 lines:

```
gtm <skill> — blocked
BLOCKED:
• <adapter or problem> — <fix>
• <adapter or problem> — <fix>
Needs you: <n> items (see the gtm run log)
<Notion link>
```

- First line: `gtm <skill> — blocked`, or `gtm <skill> — needs you` when the skill's own rules ask for a message with nothing blocked.
- One bullet per BLOCKED item, at most 4; then `• and <n> more` if there are more.
- `Needs you: <n> items`: the count only. Leave the line out when 0.
- Last line: a link to the most useful Notion page, if the run has one (the Funnel page for funnel, the campaign page for campaign-run). Leave it out otherwise.
- Never put a token, a key, message text, an email address or contact names in it. Counts and adapter names only. A Slack channel may be read by other people.

Example:

```
gtm funnel — blocked
BLOCKED:
• check failed: cold 2026-03 contacted went down: 12 -> 9 — check the CRM, or ask to accept the new baseline
https://www.notion.so/<funnel page>
```

## Cursor

None. This adapter keeps no state.

## Blocked signs and fix

- Tools not found: "Add the Slack connector in Claude settings, or set adapters.notify.kind to push." Fall back to push.
- Auth error: "Reconnect the Slack connector in Claude settings." Fall back to push.
- Not in channel or channel not found: "Invite the Slack app to the channel, or set adapters.notify.slack_channel to a channel it can post in." Fall back to push.

Never try to re-authorize the connector, join a channel or change Slack settings.

## Write / send capability

Posts exactly one message per run, to the configured channel or DM only. Nothing else.
