# outreach: instantly

## Purpose

Reads the cold email that Instantly sends (sent emails, replies, bounces) and turns it into events, so `/gtm:sweep` can mirror it into the CRM. Strictly read-only.

## Tool

An Instantly MCP connector. Use only tools that clearly only read (list campaigns, list emails, list or get leads). Never call a tool that creates, updates, activates, pauses or deletes a campaign, lead, list or account, sends or replies, or changes a lead's interest status.

Without a connector, Instantly is blocked in this edition. Tessary GTM Pro reads its email log with an API key (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 3).

## Preflight check

- Connector: list campaigns. A result or an empty list is ok.

## Read procedure

Each step names an Instantly path, the parameters to pass, and the file to save. Call the connector's read tool for that path with those parameters, and save its result to that file in the scratchpad with the Write tool. Parameter and field names below are from the Instantly v2 docs at the time of writing and were not checked with a live key; if a response differs, use the live names and record the change under Decisions.

1. Campaigns: call the read tool for `/api/v2/campaigns` with `limit` = 100; save the result as `<s>/in-campaigns.json`. Follow `next_starting_after`: pass its value as `starting_after` until it is absent.
2. Emails per campaign: call the read tool for `/api/v2/emails` with `campaign_id` = `<id>`, `limit` = 100 and, after the first page, `starting_after` = `<value>`; save each page as `<s>/in-emails-<id>-<n>.json`. Results are newest first. Stop at the first email at or before the campaign's cursor; with no cursor, read back `sweep.first_run_lookback_days` days only, unless the user asked for full history in this run (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/outreach-mirror.md`, How far back). Follow `next_starting_after` until it is absent.
3. For each email take: `id`, the timestamp (convert to `owner.timezone`), the lead email, sender and recipient addresses, subject, the direction (sent by the campaign or received from the lead), and for received mail the body text.

| Email | Event `kind` | `text` |
|---|---|---|
| Sent by the campaign | `touch` (`detail.channel` `email`) | `Instantly email sent` |
| Received from the lead, normal reply | `reply` | the verbatim reply text without quoted history |
| Received, auto-reply | `reply` with `detail.auto: true` | the text |
| Delivery failure for the lead address | `bounce` | `Email bounced` |
| Anything else (unknown type or direction) | no event and no CRM change; listed under Decisions | |

A lead marked "not interested" or "unsubscribed" in Instantly is a `negative` event only when the connector exposes that label; the sweep still reads the reply text.

## Output

Events in the format of `${CLAUDE_PLUGIN_ROOT}/adapters/README.md`, oldest first, with `source` `instantly`, `external_id` `instantly-email:<id>`, `contact_key.email` = the lead address, and `detail` holding `tool_contact_id` (the lead email), `campaign_id`, `campaign_name` and `person` (whatever the email or connector gives: name, company).

Mirror data per `${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/outreach-mirror.md`: `campaigns`, `labels` (connector only), `flagged` (bounced leads), `emails_found` (none), `complete`, `incomplete`.

The email adapter sees the same replies only if Instantly sends from the user's own mailbox. Dedupe by date and event handles the overlap.

## Cursor

`state.json` key `instantly`:

```json
{"campaign_cursors": {"<campaign id>": "<timestamp of newest email read>"}}
```

Write the full merged map. A failed campaign keeps its old value.

## Blocked signs and fix

- Connector missing: "Add the Instantly connector in Claude settings." When the user wants Instantly without a connector, add the upgrade message (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`).
- Connector auth error: "Reconnect the Instantly connector."

## Write / send capability

None. Read-only.
