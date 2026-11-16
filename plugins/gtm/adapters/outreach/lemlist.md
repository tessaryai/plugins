# outreach: lemlist

## Purpose

Reads the outreach that lemlist runs (emails, LinkedIn invites and messages, accepts, replies, bounces, unsubscribes) and turns it into events, so `/gtm:sweep` can mirror it into the CRM. Strictly read-only.

## Tool

Preferred: a lemlist MCP connector, if the session has one. Use only tools that clearly only read (list campaigns, list activities, get a lead). Never call a tool that adds, updates, pauses, starts or deletes a campaign, lead or sequence, marks a lead, sends, or unsubscribes.

Fallback: `readonly_api.py` tool `lemlist`, secret `lemlist_api_key`. Allowed paths: `/api/team`, `/api/campaigns`, `/api/campaigns/<id>`, `/api/campaigns/<id>/export`, `/api/activities`, `/api/unsubscribes`.

Never call the lemlist API another way. See `${CLAUDE_PLUGIN_ROOT}/reference/safety.md`, Read-only adapters.

## Preflight check

- Connector: list campaigns. A result or an empty list is ok.
- API: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py lemlist check` (reads `/api/team`). Exit 0 ok, exit 2 blocked.

## Read procedure

`RO` means `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py lemlist get`. Write output to the scratchpad.

1. Campaigns: `RO /api/campaigns --out <s>/lm-campaigns.json`. Keep `_id`, `name`, status and channels.
2. Activities per campaign: `RO /api/activities --param campaignId=<id> --param limit=100 --param offset=<n> --out <s>/lm-act-<id>-<n>.json`. Increase `offset` by 100 until a page returns fewer than 100 rows or rows older than the cursor. The parameter names and the activity type names below are from the lemlist API docs at the time of writing; if a response shows other names, use the live names and record the change under Decisions.
3. Stop per campaign at the first activity at or before the campaign's cursor (`createdAt`, or `_id` when equal). With no cursor, read back `sweep.first_run_lookback_days` days only, unless the user asked for full history in this run (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/outreach-mirror.md`, How far back).
4. Unsubscribes: `RO /api/unsubscribes --out <s>/lm-unsub.json` (page with `offset` if the response pages).
5. For each activity take: `_id`, `type`, `createdAt` (convert to `owner.timezone`), the lead's email, LinkedIn URL, first and last name, company name, and the campaign id and name. For reply activities take the reply text when the activity carries it.

Map `type` to an event kind:

| lemlist activity type (examples) | Event `kind` | `text` |
|---|---|---|
| `emailsSent` | `touch` (`detail.channel` `email`) | `lemlist email sent` |
| `linkedinInviteDone`, `linkedinInviteSent` | `touch` (`linkedin_invite`) | `lemlist invitation sent` |
| `linkedinSent` | `touch` (`linkedin_message`) | `lemlist LinkedIn message sent` |
| `linkedinInviteAccepted` | `accept` | `LinkedIn connection accepted` |
| `emailsReplied`, `linkedinReplied` | `reply` | the reply text if present, else empty (the email or LinkedIn adapter supplies it) |
| `emailsBounced` | `bounce` | `Email bounced` |
| `emailsUnsubscribed`, entries in `/api/unsubscribes` | `negative` with `detail.unsubscribed: true` | `Unsubscribed in lemlist` |
| `emailsNotInterested` | `negative` | the reply text as for reply |
| `emailsInterested` | no event; mirror data `labels` | |
| opens, clicks, visits, anything else known to be passive | dropped | |
| unknown types | no event and no CRM change; listed under Decisions | |

## Output

Events in the format of `${CLAUDE_PLUGIN_ROOT}/adapters/README.md`, oldest first, with `source` `lemlist`, `external_id` `lemlist-activity:<_id>`, `contact_key` from the lead email and LinkedIn URL, and `detail` holding `tool_contact_id` (lead id or email), `campaign_id`, `campaign_name` and `person` (name, title if present, company name and domain, location).

Mirror data, as defined in `${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/outreach-mirror.md`: `campaigns`, `labels`, `flagged` (bounced and unsubscribed leads), `emails_found` (none; lemlist leads carry their email in every event), `complete`, `incomplete`.

## Cursor

`state.json` key `lemlist`:

```json
{"campaign_cursors": {"<campaign id>": "<createdAt of newest activity read>"}}
```

Write the full merged map. A campaign that failed keeps its old value.

## Blocked signs and fix

- Exit 2 or a connector auth error: "Save a working lemlist API key: run `python3 -I -B <plugin root>/lib/config.py set-secret lemlist_api_key` in a terminal, or reconnect the lemlist connector."
- Exit 1 (refused path): report under Needs you; never edit the allowlist.

## Write / send capability

None. Read-only.
