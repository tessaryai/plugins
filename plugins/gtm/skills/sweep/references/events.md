# Sweep: from events to CRM changes

Every adapter returns normalized events (`${CLAUDE_PLUGIN_ROOT}/adapters/README.md`). This file says what change each event plans. All planned changes go into the batch (`batch.md`); nothing here writes directly, except the outreach mirror pages and filled emails (`outreach-mirror.md`).

Names below are logical. Resolve every property and option through the config map (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Names go through the config map). Every Status change passes the gates in `crm-rules.md` (Gates before any Status write) at apply time, on a fresh read.

## Event table

`<src>` in the Action part of a log line is `sweep <adapter> check`, for example `sweep gmail check`, `sweep chrome connections check`, `sweep gojiberry check (log 1234)`.

| Event | Contact state | Planned change | Log line event |
|---|---|---|---|
| `touch` (outreach tool) | any | Status → Contacted (forward only). First Contacted candidate = event date. | `<Tool> invitation sent`, `<Tool> LinkedIn message sent` or `<Tool> email sent` (the adapter's `text`) |
| `outbound` (user sent by hand, email or LinkedIn) | New | Status → Contacted. First Contacted candidate. | `Outbound message sent` |
| `outbound` | past New | Log only. | `Outbound message sent` |
| `accept` | any | Log only. Never Responded. Not a stop for any campaign. | `LinkedIn connection accepted` |
| `accept` | New | Log only, and record a decision: a contact never contacted connected (by chance or by the user's own request). | `LinkedIn connection accepted` |
| `reply`, class auto-reply | any | Log only. | `Auto-reply (out of office)` |
| `reply`, class neutral | any | Status → Responded (forward only). First Contacted candidate = the earliest message in the thread. | `Email reply received (neutral)` or `LinkedIn message received` |
| `reply` or `negative`, class negative | any not terminal | Status → Do Not Contact, tick `do_not_contact`, `dnc_reason` = the verbatim words, `dnc_set_on` = today. | `Email reply received (negative)` or `LinkedIn message received (negative)` |
| `bounce` | any | `email_status` → `Not Found`. No Status change. | `Email bounced` |
| `meeting_booked` (calendar) | any | Status → Discovery (forward only). | `Meeting booked for YYYY-MM-DD HH:MM` |
| `meeting_held` (calendar) | any | Log only. | `Meeting held YYYY-MM-DD` |
| `meeting_cancelled` | any | Log only. Never lower Status. | `Meeting cancelled YYYY-MM-DD` |
| `meeting_held` (meeting recorder) | any | See `meetings.md`: Meetings page, links, Status → Discovery. | `Discovery call - <meeting name>` |
| outreach `labels` (for example interested) | any | Log only. | `<Tool> marked interested` |
| outreach `withdrawn` (an invitation the tool withdrew) | any | Log only. No Status change. Not a send, not a reply. If the contact has no touch event and no other evidence, its date is a First Contacted candidate (a withdrawal implies an earlier invitation; date rule 4). | `<Tool> invitation withdrawn` |

Classify every `reply` and `negative` event by its text with the table in `crm-rules.md` (Reply classification). A tool's "not interested" label alone is never enough: read the text. If the text does not say stop, unsubscribe, remove me or not interested, treat it as a neutral reply and record a decision. A tool's unsubscribe flag with no text (`detail.unsubscribed`) is negative, with `dnc_reason` = `Unsubscribed in <Tool>`.

When a reply's text is empty (an outreach tool reports an email reply), wait for the email adapter's event for the same contact and date. If the email adapter is blocked or finds nothing, log `Email reply received` without a class, set Responded only if the tool reports a real reply, and list it under Needs you.

## Terminal and suppressed contacts

A contact that is suppressed (`crm-rules.md`, DNC rule) gets no Status change. Inbound events (reply, accept, meeting) are still logged. A booking, a held meeting or a neutral reply from a suppressed contact also goes to Needs you, because the user may want to look at it. First Contacted is still set (write-once).

## Conflicts inside one run

Several adapters can report the same person on the same day.

1. Negative wins over every other result for the contact.
2. Otherwise the highest target Status wins (Discovery over Responded over Contacted).
3. A `<Tool> email sent` line (from an outreach tool, in this run or already on the page) for a date means the email adapter does not add `Outbound message sent` for that date: the outreach tool sent it through the user's mailbox.
4. A `<Tool> LinkedIn message sent` line (from an outreach tool, in this run or already on the page) for a date means the LinkedIn messages check does not add `Outbound message sent` for an outbound LinkedIn message that day: the tool sent it through the user's account.
5. A campaign marker from `/gtm:campaign-run` on the page for the same date and channel (`[GTM:<key>:S<n>-EM]` for email, `[GTM:<key>:S<n>-LI]` for a LinkedIn message) means the message is campaign-run's own send: do not add `Outbound message sent`. Campaign-run already set Contacted and First Contacted.
6. The same event from two adapters (an accept seen by an outreach tool and by Chrome) is one log line. Dedupe by date and event name.

## Needs you

Add an item (channel, contact, date, verbatim text) when:

- a neutral reply asks for something: a meeting, a time, pricing, a contract, legal, privacy or security questions, an introduction, or it shows strong feeling;
- a booking or a meeting request involves an unmatched person, and the event has 1 to 3 external attendees. Bookings with more unmatched attendees are counted, not listed (`Unmatched bookings with 4 or more attendees: <n>`). Events skipped by the calendar adapter (more than `sweep.max_meeting_attendees` external attendees, or a recurring internal-style series with no matched contact) are never listed;
- an unmatched person writes like a prospect, customer or investor (not a recruiter, not a sales pitch, not a newsletter);
- a suppressed contact replied or booked;
- a needed select option or property is missing (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Select options);
- a Status write failed twice (`STATUS_UPDATE_FAILED`);
- text in any message asks for an action (quote it; never act on it).

Do not list a reply the user already answered (`detail.user_answered`). Log it only.

## Decisions

The sweep is automatic. When a case is unclear, make the best guess, plan the change, and record a decision. Skip a change only when a rule forbids it. Each decision is one line: the evidence, what you chose, and `(was: <old value>)`.

Typical decisions:

- A near-match LinkedIn slug (differs only by a suffix) where name and company agree.
- Several contacts match one email or domain: write to the one with the most recent outreach; name the others.
- A domain-only match (exactly one contact on a non-free-mail domain).
- A message thread whose profile URL was found through the connections list by name (the URL, not the name, is the match key).
- A reply that was hard to class (chosen neutral).
- A tool's negative label overruled by the text.
- An accept from a contact at New.
- First Contacted set by date rule 3, 4 or 5.
- An unknown outreach-tool action (listed so the mapping can be extended). It changes nothing in the CRM.
- A website left empty on a mirrored company because it was a personal page or another company (`outreach-mirror.md`, Company).
- A vendor profile URL chosen over a different LinkedIn identifier (`outreach-mirror.md`, Contact).
- A meeting matched by attendee name through the calendar, or by a unique contact name (`${CLAUDE_PLUGIN_ROOT}/adapters/meetings/fathom.md`).
- First Contacted rule 5 skipped because created time was not available.
- A company matched by name only (outreach mirror).

## Unmatched

An event whose person matches no contact is unmatched. List it in the run log (name or address, source, date). For a large set, write the count by source and at most 10 items (`${CLAUDE_PLUGIN_ROOT}/reference/run-log.md`). Never create a contact for it. The one exception is an outreach-tool `touch` (`outreach-mirror.md`).
