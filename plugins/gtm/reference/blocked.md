# Blocked adapters

An adapter is blocked when its tool cannot run in this session: the MCP connector is missing or fails auth, the tool has no connector in the session, Chrome is not connected, LinkedIn shows a login page, a CAPTCHA or a warning, or a Notion tool is missing.

A blocked adapter is never treated as clean, and never stays silent.

## Check procedure (preflight)

Run this at the start of every skill, for each adapter the run needs:

1. Read the adapter list from config (`adapters.*`).
2. For each adapter, open its file `${CLAUDE_PLUGIN_ROOT}/adapters/<kind>/<tool>.md` and run its Preflight check. Typical checks:
   - MCP connector: load its tools with ToolSearch; call one cheap read (for example list one item). Missing tools or an auth error = blocked.
   - Chrome (LinkedIn): load the Claude in Chrome tools, open a new tab on the LinkedIn feed, and check from a screenshot that it is not a login page or CAPTCHA. Tools missing or not connected = blocked.
   - Notion: load the Notion tools and fetch the Contacts data source.
3. Mark each adapter `ok` or `blocked` with what you saw (the error status or the screen state, never a token or raw exception text).
4. If Notion itself is blocked, stop the run after the notification: nothing can be written. Report it.

## Cowork

This edition follows these rules in Cowork and in Claude Code alike: a tool works only through its connector.

- Never call a vendor API with curl or a script. The Cowork virtual machine cannot reach them. One exception: the reachability probe in `/gtm:setup` step 0 (`curl` to `https://api.notion.com/` with no token, header or body, once), which runs before the runtime is known and sends no data.
- A tool with no connector in the session is blocked, even when its adapter file names an API key. Fix text: the upgrade message when Tessary GTM Pro could read the tool with a key (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 3), else "Connect a connector for <tool>."
- Never offer to save a key.

## During the run

1. Finish everything that does not depend on the blocked adapter. One blocked adapter never stops the others.
2. Do not run any step whose safety depends on the blocked adapter. Absence of a reply or an accept is not proof when the check that would show it is blocked. For example: a blocked email adapter stops email sends and every step whose condition is "no reply"; a blocked LinkedIn adapter stops LinkedIn sends and every step whose condition is "no reply" or "not accepted".
3. Do not move the blocked adapter's cursor in the state file. The next run retries the same period.
4. Never try to sign in, re-authorize a connector, enter a password, or solve a CAPTCHA. Never try another route around the block (another browser, scraping, a different API).
5. If LinkedIn shows a weekly invitation limit, a restriction notice or any warning during a run, stop all LinkedIn work at once and treat LinkedIn as blocked for the rest of the run.

## Report

Put a `BLOCKED` section first in the run log entry and first in the final report. For each blocked adapter give: the adapter, what you saw, and the fix. Fix text examples:

- "Reconnect the Gmail connector in Claude settings."
- "Open Chrome, sign in to LinkedIn, and check the Claude extension is connected."
- "Connect a connector for fathom." When the user wants the tool without a connector: the upgrade message (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`).
- "Add or reconnect the Notion connector in Claude settings."

## One notification per run

Send exactly one notification per run when anything is blocked, not one per adapter:

- Text: `gtm <skill> blocked: <adapters>. <first fix>. Needs you: <n>.` Keep it under 200 characters. No tokens, no contact data beyond a count.
- `adapters.notify.kind` = `push`: use `PushNotification` (load it with ToolSearch if it is not loaded).
- `adapters.notify.kind` = `slack`: post to `adapters.notify.slack_channel` with the Slack connector (`${CLAUDE_PLUGIN_ROOT}/adapters/notify/slack.md`). If Slack itself fails, fall back to `PushNotification`.
- `adapters.notify.kind` = `none`, or no notify tool is available: say so in the BLOCKED section.

A run with no blocked adapter sends no notification, unless the skill's own rules ask for one.
