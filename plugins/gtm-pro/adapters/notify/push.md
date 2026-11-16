# notify: push

## Purpose

Sends one push notification to the user's devices when a gtm run has something blocked, or when a skill's own rules ask for a notification. Every skill can use it, through `${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`. Chosen when `adapters.notify.kind` is `push` (the default).

## Tool

The `PushNotification` tool of the Claude Code session. There is no MCP connector and no `readonly_api.py` entry.

- It is often deferred. Load it with ToolSearch (`select:PushNotification`) and read its schema at run time. Pass only the parameters the schema defines. Never guess a parameter name.
- Allowed: one `PushNotification` call per run.
- Forbidden: any other tool for this purpose. Do not fall back to email, Slack or a message to a contact.

## Preflight check

Load the tool with ToolSearch. Found: ok. Not found: the notify adapter is unavailable for this run (not a blocked CRM adapter). Do not send a test notification unless the user asks.

## Send procedure

1. Wait until the end of the run, after the run log entry is written, so the message covers everything. Exception: when Notion itself is blocked, send right away and stop (`blocked.md`, Check procedure step 4).
2. Build one message (format below).
3. Call `PushNotification` once. Never send a second one in the same run, even if more problems appear later; put them in the run log.
4. If the call fails, do not retry more than once. Say in the final report's BLOCKED section that the notification could not be sent.

## Message format

One line, under 200 characters:

```
gtm <skill> blocked: <adapters or problem>. <first fix>. Needs you: <n>.
```

- `<skill>` is the skill name without the prefix (`sweep`, `campaign-run`, `funnel`, ...).
- `<adapters or problem>`: the blocked adapter names joined with commas, or the short problem for a skill that has no adapter block (for example `check failed`).
- `<first fix>`: the fix for the first BLOCKED item, shortened.
- `Needs you: <n>`: the count of Needs you items. Leave it out when 0.
- Never put a token, a key, an email address, message text or contact names in it. A count is fine.

Example: `gtm sweep blocked: gmail, chrome. Reconnect the Gmail connector in Claude settings. Needs you: 3.`

A push message has no link. The user opens the run log (the `run_log` path printed by `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py paths`) or the Notion page for detail.

## Cursor

None. This adapter keeps no state.

## Blocked signs and fix

- Tool not found after ToolSearch: "Push notifications are not available in this session; set adapters.notify.kind to slack or none." Report it once in the BLOCKED section; do not stop the run.
- Tool error: report "the push notification failed" in the BLOCKED section. Never retry through another tool.

## Write / send capability

Sends exactly one push notification per run, to the user only. Nothing else.
