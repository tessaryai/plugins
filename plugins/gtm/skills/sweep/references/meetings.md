# Sweep: meetings from recorders

Meeting adapters (fathom, granola, fireflies, otter) return one `meeting_held` event per external attendee, with `detail.title`, `start`, `recording_url`, `summary`, `attendees` and `meeting_source`. This file turns them into Meetings pages and contact changes.

The calendar adapter does not create Meetings pages. It only logs bookings and sets Discovery (`events.md`).

## 1. Group and match

1. Group events by `external_id` (one meeting).
2. Match each attendee to a contact (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Matching). The user's own addresses are never contacts. When the adapter gives attendee names but no emails (the Fathom connector), it resolves them first through the calendar event at the same time, then by a unique contact name, as its file says (`${CLAUDE_PLUGIN_ROOT}/adapters/meetings/fathom.md`, Output). Such a match is a Decision.
3. A meeting with no matched attendee creates no page. List it under Unmatched (title, date, attendee addresses or names). This includes a meeting whose calendar event has no attendees or that has no calendar event at all; never drop it silently. If it looks like a sales call with a prospect, or its title names a person or a domain other than the user, list it under Needs you, because the user may want to add the person.

## 2. Find or create the Meetings page

Dedupe before you create:

1. Look in the Meetings index (`batch.md`, CRM index) for a page whose `recording_url` equals `detail.recording_url`.
2. If there is no URL, or no hit, look for a page whose `name` equals the title and `date` equals the meeting date. Do not query Meetings once per meeting in rows mode (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows).
3. A hit: use that page. Add missing contacts and fill an empty `summary`; change nothing else.

Create when there is no hit:

| Field | Value |
|---|---|
| `name` | the meeting title |
| `date` | the start (date and time, `owner.timezone`) |
| `contacts` | every matched contact |
| `recording_url` | `detail.recording_url` |
| `summary` | the summary as plain text, cut to 1,900 characters at a sentence end, with ` ...` when cut |
| `source` | the `meeting_source` option (`Fathom`, `Granola`, `Fireflies`, `Otter`) through `notion.option_map.meetings.source` |
| body | the full summary, one paragraph per line, with a blank line between lines |

A rich-text property holds pieces of at most 2,000 characters; the body holds the full text. Pass the body as Notion-flavored Markdown in the create call.

Create the Meetings pages in the apply step (`batch.md`) before the contact log lines, so the log lines can link them.

## 3. Link both ways

`contacts.meetings` and `meetings.contacts` are one two-way relation. Write it from the meeting side (`contacts` on the Meetings page, the full list), because a meeting has few contacts. Then verify from the contact side: fetch each contact and check its `meetings` relation holds the page. If the contact side does not show it (the workspace maps two separate one-way relations), add the meeting to the contact's `meetings` relation too: read the current list, append, write the full list.

## 4. Contact changes

For each matched contact, plan in the batch:

- Status → Discovery, forward only, through the gates. A contact already at Discovery or Lead keeps its Status. A suppressed contact keeps its Status; list the meeting under Needs you.
- Log line, once per contact per meeting:

```
YYYY-MM-DD — Discovery call - <meeting name>. Status → Discovery. Action: sweep <tool> check.
```

  Leave out `Status → Discovery.` when Status did not change. The date is the meeting date. With MCP Markdown you may write the meeting name as a link to the Meetings page.
- First Contacted candidate: the meeting date (date rule 4), used only when the field is empty and no earlier evidence exists.

Dedupe: a contact page that already has a `Discovery call - <meeting name>` line for that date gets no new line. The meeting name comes from outside: neutralize it before writing (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Outside text in log lines).

Note: a recorder meeting with a matched contact sets Discovery, as above (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Status ladder). A calendar `meeting_held` stays log only.

## 5. Verify

Re-read each new or changed Meetings page: `contacts`, `recording_url`, `date`. Re-read each contact: Status, the log line, the `meetings` relation.
