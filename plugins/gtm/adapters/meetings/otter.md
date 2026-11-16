# meetings: otter

## Purpose

Reads meetings recorded by Otter: title, time, attendees, summary and the conversation link. `/gtm:sweep` turns each meeting with a matched contact into a Meetings page and a Discovery step (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/meetings.md`). Read-only.

## Tool

Only an Otter MCP connector. Without a connector this adapter is blocked.

Find the connector with ToolSearch (`otter meetings conversations`). Read the schemas and pick a tool that lists conversations or meetings in a date range and, if needed, a tool that reads one conversation's summary. Use only read tools. Never share, edit, delete or export a conversation, and never add the assistant to a meeting.

## Preflight check

List conversations from the last day. A result or an empty list is ok. A missing connector or an auth error is blocked.

## Read procedure

1. Window: from the cursor (`after`) to now; with no cursor, `sweep.first_run_lookback_days` days back.
2. Follow every page or cursor. Stopping early makes the read incomplete.
3. For each conversation take: a stable id, the title, the start time, the attendee emails (or speaker names when emails are missing), the summary (Otter's outline or summary, not the transcript) and the conversation link.
4. Drop conversations whose attendees are all the user. With names but no emails, match only through the calendar adapter's event at the same start time; otherwise list the meeting under Unmatched.

## Output

One `meeting_held` event per external attendee, as in `${CLAUDE_PLUGIN_ROOT}/adapters/meetings/fathom.md`, Output, with `source` `otter`, `external_id` `otter:<id>`, `detail.recording_url` = the conversation link, and `detail.meeting_source` `Otter`.

## Cursor

`state.json` key `otter`:

```json
{"after": "YYYY-MM-DDTHH:MM:SSZ"}
```

Moves only when every page was read.

## Blocked signs and fix

- No connector: "Add the Otter connector in Claude settings. Otter has no read API this plugin can use without it."
- Auth error: "Reconnect the Otter connector in Claude settings."

## Write / send capability

None. Read-only.
