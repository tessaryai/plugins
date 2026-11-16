# calendar: google

## Purpose

Reads the user's Google Calendar for meetings with contacts: booked (future), held (past) and cancelled. `/gtm:sweep` uses it. Read-only.

## Tool

The Google Calendar MCP connector. There is no `readonly_api.py` entry for it.

- Load with ToolSearch, for example `google calendar list_events get_event`. Use the names ToolSearch returns and read each schema at run time.
- Allowed: `list_events`, `get_event`, `list_calendars`.
- Forbidden: `create_event`, `update_event`, `delete_event`, `respond_to_event`, and any tool that suggests or books times.

## Preflight check

Call `list_events` on the primary calendar with a one-day window and `pageSize` 1. A result or an empty list is ok. A missing tool or an auth error is blocked.

## Read procedure

1. Window: from the cursor date (with no cursor, `sweep.first_run_lookback_days` days back) to today plus `sweep.calendar_lookahead_days` days. Pass local times without an offset, as the schema asks; set `timeZone` to `owner.timezone`.
2. Calendar: primary only, unless config later names others.
3. Order by start time. Follow `pageToken` until none is returned. Stopping early makes the read incomplete.
4. Skip: events with no attendee outside the user (an attendee is external when the address is not in `owner.emails` and not on `owner.own_domains`), events the user declined, all-day events with no attendees, out-of-office, focus-time and working-location events.
5. Call `get_event` only when the list result lacks attendee response status or the description is needed to tell a cancellation.

## Output

One event per external attendee per meeting (format in `${CLAUDE_PLUGIN_ROOT}/adapters/README.md`). `source` is `google-calendar`. `contact_key.email` = the attendee address. `external_id` = `event:<event id>:<start date>` (recurring events get one id per instance). `detail` holds `title`, `start` (local `YYYY-MM-DD HH:MM`), `attendee_name`, `response` and `event_url`.

| Situation | Event `kind` |
|---|---|
| Start in the future, not cancelled, attendee accepted, tentative or not yet answered | `meeting_booked` |
| Start in the past (inside the window), not cancelled, attendee did not decline | `meeting_held` |
| Event cancelled, or the attendee declined | `meeting_cancelled` |

`date` is the meeting date. Unmatched external attendees are still returned as events; the sweep lists them as unmatched. A booking with an unmatched attendee goes to Needs you, because the user may know the person.

## Cursor

`state.json` key `google-calendar`:

```json
{"after": "YYYY-MM-DD"}
```

Moves to today when the whole window was read. Future events are read again each run until they are past; dedupe by date and event keeps that safe.

## Blocked signs and fix

- Tools missing: "Add the Google Calendar connector in Claude settings."
- Auth or permission error: "Reconnect the Google Calendar connector in Claude settings."

## Write / send capability

None. Read-only.
