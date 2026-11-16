# meetings: fireflies

## Purpose

Reads meetings recorded by Fireflies: title, time, attendees, summary and the transcript link. `/gtm:sweep` turns each meeting with a matched contact into a Meetings page and a Discovery step (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/meetings.md`). Read-only.

## Tool

Preferred: a Fireflies MCP connector. Find it with ToolSearch (`fireflies transcripts meetings`). Read the schemas; use only tools that list or read transcripts and summaries. Never call a tool that uploads audio, deletes, shares or changes a transcript, or adds the bot to a meeting.

Fallback: the read-only GraphQL endpoint through `readonly_api.py` (tool `fireflies`, secret `fireflies_api_key`). The client refuses any query that contains `mutation` or `subscription`.

```
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py fireflies graphql \
  --query-file <scratchpad>/ff-query.graphql --variables-file <scratchpad>/ff-vars.json --out <scratchpad>/ff-<n>.json
```

A query shape that matched the Fireflies schema at the time of writing (check the field names against the current Fireflies API docs or an error message before relying on it):

```graphql
query Transcripts($fromDate: DateTime, $toDate: DateTime, $limit: Int, $skip: Int) {
  transcripts(fromDate: $fromDate, toDate: $toDate, limit: $limit, skip: $skip) {
    id
    title
    date
    transcript_url
    meeting_attendees { email displayName }
    summary { overview short_summary }
  }
}
```

Variables: `{"fromDate": "<cursor ISO>", "toDate": "<now ISO>", "limit": 50, "skip": 0}`. If the API reports an unknown field, remove that field, record it under Needs you ("the Fireflies query needs an update"), and read with the rest.

## Preflight check

- Connector: list one transcript. A result or an empty list is ok.
- API: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py fireflies check`. Exit 0 ok, exit 2 blocked. Not with `runtime` = `cowork` or without Python (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`, Cowork).

## Read procedure

1. Window: from the cursor (`after`) to now; with no cursor, `sweep.first_run_lookback_days` days back.
2. Page with `skip` (+50) until a page returns fewer than `limit` items. Stopping early makes the read incomplete.
3. For each transcript take: `id`, `title`, `date` (epoch milliseconds in the API; convert to `owner.timezone`), `transcript_url`, attendee emails, and the summary (`overview`, else `short_summary`).
4. Drop meetings whose attendees are all the user.
5. A transcript with no summary yet stays pending for the next run.

## Output

One `meeting_held` event per external attendee, as in `${CLAUDE_PLUGIN_ROOT}/adapters/meetings/fathom.md`, Output, with `source` `fireflies`, `external_id` `fireflies:<id>`, `detail.recording_url` = `transcript_url`, and `detail.meeting_source` `Fireflies`.

## Cursor

`state.json` key `fireflies`:

```json
{"after": "YYYY-MM-DDTHH:MM:SSZ", "pending": [<transcript ids without a summary>]}
```

Moves only when every page was read.

## Blocked signs and fix

- Connector missing and no key: "Add the Fireflies connector in Claude settings, or save a key: run `python3 -I -B <plugin root>/lib/config.py set-secret fireflies_api_key` in a terminal." (Claude Code only. In Cowork: "Connect a connector for fireflies, or run this routine from Claude Code.")
- Auth error or exit 2: "Reconnect the Fireflies connector, or save a new Fireflies API key with set-secret." (In Cowork: "Reconnect the Fireflies connector.")

## Write / send capability

None. Read-only.
