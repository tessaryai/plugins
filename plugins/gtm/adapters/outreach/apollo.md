# outreach: apollo

## Purpose

Reads the sequences ("emailer campaigns") that Apollo runs for the user (emails sent, replies, bounces, step activity) and turns them into events, so `/gtm:sweep` can mirror them into the CRM. Strictly read-only. Apollo as an enrichment source is a separate adapter (`adapters/enrichment/apollo.md`).

## Tool

Preferred, and in practice required: an Apollo MCP connector. Use only tools that clearly only read (list sequences, list a sequence's contacts or activity, get a contact). Never call a tool that adds contacts to a sequence, creates, edits, activates or pauses a sequence, sends, marks a task done, enriches or reveals.

Fallback: `readonly_api.py` tool `apollo`, secret `apollo_api_key`. Allowed paths: `/api/v1/auth/health`, `/api/v1/contacts/<id>`, `/api/v1/accounts/<id>`, `/api/v1/emailer_campaigns/<id>`.

Limit of the fallback: Apollo lists and searches contacts, sequence members and messages only with POST requests, which the client refuses. With the API alone this adapter can read one sequence by id and one contact by id, but cannot list who was contacted. So without a connector, the mirror cannot run: treat the adapter as blocked with the fix below, after the preflight.

## Preflight check

- Connector: list sequences (or the closest read tool). A result or an empty list is ok.
- API only: `python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py apollo check`. Exit 2 blocked. Exit 0 still means blocked for the mirror (no list access); report it with the connector fix.

## Read procedure

With a connector only (see Tool for why the API alone cannot list):

1. List sequences. Keep id, name, active state and channels.
2. For each sequence, list its contact activity or messages since the sequence's cursor, following every page or cursor. With no cursor, read back to the sequence's first activity on the first run.
3. For each item take: a stable id, the timestamp (convert to `owner.timezone`), the contact email and LinkedIn URL, name, title, company name and domain, the step type (email, LinkedIn, call, task), and for replies the text.

| Apollo activity | Event `kind` | `text` |
|---|---|---|
| Email step sent | `touch` (`detail.channel` `email`) | `Apollo email sent` |
| LinkedIn step completed (invite or message, when Apollo logs it) | `touch` (`linkedin_invite` or `linkedin_message`) | `Apollo invitation sent` or `Apollo LinkedIn message sent` |
| Reply | `reply` | the verbatim text, if given |
| Bounce | `bounce` | `Email bounced` |
| Unsubscribe or opt-out | `negative` with `detail.unsubscribed: true` | `Unsubscribed in Apollo` |
| Opens, clicks, calls and tasks not completed | dropped | |
| Unknown activity | no event; listed under Decisions | |

## Output

Events in the format of `${CLAUDE_PLUGIN_ROOT}/adapters/README.md`, oldest first, with `source` `apollo`, `external_id` `apollo:<activity id>`, and `detail` holding `tool_contact_id`, `campaign_id`, `campaign_name` and `person`.

Mirror data per `${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/outreach-mirror.md`: `campaigns`, `labels`, `flagged`, `emails_found` (none), `complete`, `incomplete`.

## Cursor

`state.json` key `apollo`:

```json
{"campaign_cursors": {"<sequence id>": "<timestamp of newest activity read>"}}
```

Write the full merged map. A failed sequence keeps its old value.

## Blocked signs and fix

- No connector: "Add the Apollo connector in Claude settings. Apollo's API lists sequence activity only through POST requests, which this plugin's read-only client does not send."
- Connector auth error: "Reconnect the Apollo connector in Claude settings."

## Write / send capability

None. Read-only.
