# outreach: instantly

## Purpose

Reads the cold email that Instantly sends (sent emails, replies, bounces) and turns it into events, so `/gtm:sweep` can mirror it into the CRM. Strictly read-only.

## Tool

Preferred: an Instantly MCP connector, if the session has one. Use only tools that clearly only read (list campaigns, list emails, list or get leads). Never call a tool that creates, updates, activates, pauses or deletes a campaign, lead, list or account, sends or replies, or changes a lead's interest status.

Fallback: `readonly_api.py` tool `instantly`, secret `instantly_api_key`. Allowed paths: `/api/v2/campaigns`, `/api/v2/campaigns/<id>`, `/api/v2/campaigns/analytics`, `/api/v2/campaigns/analytics/overview`, `/api/v2/emails`, `/api/v2/emails/<id>`, `/api/v2/accounts`.

Limit of the fallback: Instantly lists leads only with a POST request, which the client refuses. Without a connector this adapter reads the email log (`/api/v2/emails`), which covers sent emails, replies and bounces, but not lead fields such as title or company. Mirrored contacts then get only email, name if present, and the campaign.

## Preflight check

- Connector: list campaigns. A result or an empty list is ok.
- API: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py instantly check` (reads `/api/v2/campaigns`). Exit 0 ok, exit 2 blocked. Not with `runtime` = `cowork` or without Python (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`, Cowork).

## Read procedure

`RO` means `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py instantly get`. Write output to the scratchpad. Parameter and field names below are from the Instantly v2 docs at the time of writing and were not checked with a live key; if a response differs, use the live names and record the change under Decisions.

1. Campaigns: `RO /api/v2/campaigns --param limit=100 --out <s>/in-campaigns.json`, following `next_starting_after` with `--param starting_after=<value>` until it is absent.
2. Emails per campaign: `RO /api/v2/emails --param campaign_id=<id> --param limit=100 [--param starting_after=<value>] --out <s>/in-emails-<id>-<n>.json`. Results are newest first. Stop at the first email at or before the campaign's cursor; with no cursor, read back `sweep.first_run_lookback_days` days only, unless the user asked for full history in this run (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/outreach-mirror.md`, How far back). Follow `next_starting_after` until it is absent.
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

- Exit 2 or a connector auth error: "Save a working Instantly API key (v2, read scopes): run `python3 -I -B <plugin root>/lib/config.py set-secret instantly_api_key` in a terminal, or reconnect the Instantly connector." (Claude Code only. In Cowork: "Connect a connector for instantly, or run this routine from Claude Code.")
- Exit 1 (refused path): report under Needs you; never edit the allowlist.

## Write / send capability

None. Read-only.
