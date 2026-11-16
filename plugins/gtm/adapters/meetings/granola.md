# meetings: granola

## Purpose

Reads meeting notes from Granola: title, time, attendees, the AI summary and a link to the note. `/gtm:sweep` turns each meeting with a matched contact into a Meetings page and a Discovery step (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/meetings.md`). Read-only.

## Tool

Only a Granola MCP connector. Granola has no public read API that `readonly_api.py` covers, so without a connector this adapter is blocked.

Find the connector with ToolSearch (`granola meetings notes`). Tool names are not fixed here: read the schemas and pick a tool that lists meetings or notes in a date range and, if the list lacks it, a tool that reads one note's summary. Use only read tools. Never create, edit, share or delete a note.

## Preflight check

List meetings or notes from the last day. A result or an empty list is ok. A missing connector or an auth error is blocked.

## Read procedure

1. Window: from the cursor (`after`) to now; with no cursor, `sweep.first_run_lookback_days` days back.
2. Follow every page or cursor the tool returns. Stopping early makes the read incomplete.
3. For each meeting take: a stable id, the title, the start time, the attendee emails, the summary (Granola's enhanced notes or summary, not the raw transcript) and a link to the note if the tool returns one.
4. Drop meetings whose attendees are all the user (`owner.emails`, `owner.own_domains`). If the tool returns no attendee emails for a meeting, keep it only when its calendar event can be matched by the calendar adapter (same start time); otherwise list it under Unmatched with its title.

## Output

One `meeting_held` event per external attendee, as in `${CLAUDE_PLUGIN_ROOT}/adapters/meetings/fathom.md`, Output, with `source` `granola`, `external_id` `granola:<id>`, `detail.recording_url` = the note link (or null), and `detail.meeting_source` `Granola`.

## Cursor

`state.json` key `granola`:

```json
{"after": "YYYY-MM-DDTHH:MM:SSZ"}
```

Moves to the newest meeting time read, only when every page was read.

## Blocked signs and fix

- No connector: "Add the Granola connector in Claude settings. Granola has no read API this plugin can use without it."
- Auth error: "Reconnect the Granola connector in Claude settings."

## Write / send capability

None. Read-only.
