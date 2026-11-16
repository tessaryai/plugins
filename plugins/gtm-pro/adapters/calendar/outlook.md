# calendar: outlook

## Purpose

Reads the user's Outlook (Microsoft 365) calendar for meetings with contacts: booked, held and cancelled. `/gtm-pro:sweep` uses it. Read-only.

The rules of `${CLAUDE_PLUGIN_ROOT}/adapters/calendar/google.md` apply. Only the tool calls differ.

## Tool

A Microsoft 365 / Outlook MCP connector with calendar tools. Find it with ToolSearch (queries such as `outlook calendar events`, `microsoft 365 calendar`). Tool names differ between vendors; read the schemas and pick a tool that lists events in a time range (a calendar view that expands recurring events is best) and, if needed, one that reads one event.

Forbidden: create, update, delete, accept, decline, tentative, forward and any booking or scheduling tool.

There is no `readonly_api.py` entry for Outlook. Without a connector this adapter is blocked.

## Preflight check

List the events of the next day. A result or an empty list is ok. A missing connector or an auth error is blocked.

## Read procedure

1. Window: from the cursor date (or `sweep.first_run_lookback_days` back) to today plus `sweep.calendar_lookahead_days`, in `owner.timezone`.
2. Use the tool's calendar view (recurring events expanded into instances) when it has one.
3. Follow every page link or cursor. Stopping early makes the read incomplete.
4. Skip the same events as Google: no external attendee, declined by the user, all-day with no attendees, out-of-office and private blocks, more than `sweep.max_meeting_attendees` external attendees, and recurring internal-style series (a series master or occurrence) with no matched contact. Count skipped events only. Unmatched bookings go to Needs you only with 1 to 3 external attendees, as in Google.

## Output

Same events as Google (Output). `source` is `outlook-calendar`. Map the attendee response: accepted, tentative or none → booked or held by date; declined → `meeting_cancelled`. An event marked cancelled → `meeting_cancelled`. `external_id` = `event:<event id>:<start date>`.

## Cursor

`state.json` key `outlook-calendar`:

```json
{"after": "YYYY-MM-DD"}
```

Moves to today when the whole window was read.

## Blocked signs and fix

- No connector: "Add a Microsoft 365 / Outlook connector with calendar access in Claude settings."
- Auth error: "Reconnect the Outlook connector in Claude settings."

## Write / send capability

None. Read-only.
