# Sweep: CRM index, batch, verify, cursors

How the sweep reads the CRM, collects changes, writes them once, checks them and moves cursors. Notion paths follow `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`. Write every scratch file in the session scratchpad.

## 1. CRM index (before the checks)

The checks need to match many addresses and LinkedIn URLs. Build one index of contacts at the start, then match in memory.

Fields to read per contact: page id, `name`, `email`, `linkedin`, `status`, `do_not_contact`, `first_contacted`, `lead_source`, `notes` (for `<Tool> contact id:` lines), `company`, `campaign`, and created time when the path gives it (MCP view mode does not return it).

- Read: `notion-query-data-sources` in view mode with `notion.views.contacts`, following every `next_cursor` until `has_more` is false (`notion-access.md`, Query rows). View mode has no plan quota. Never build the index in rows or SQL mode: they share a small workspace allowance that one call can use up. Do not split the read by Status or date to get past a cap.
- Targeted lookups in rows or SQL mode (a key the index cannot answer) are allowed only in small numbers. Count them for the run log. On the allowance error, stop using rows and SQL mode for the rest of the run and answer from the view-mode index.
- If the full index cannot be read even in view mode (no view URL and none found, a failed page), note in the run log that the index was partial, treat every check that needs it as incomplete, and show the upgrade message under Needs you (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 1). Show it also when the CRM has about 300 contacts or more, with your estimate of the count.

Canonicalize LinkedIn URLs on both sides before comparing (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Matching). Index the domains of contact emails too, for the domain rule.

New pages created during the run (outreach mirror) are added to the index at once.

Also read Companies, Campaigns and Meetings once, the same way (view mode with `notion.views.companies`, `notion.views.campaigns` and `notion.views.meetings`), when the run needs them: the outreach mirror matches campaigns and companies, and the meetings step dedupes Meetings pages. Match in memory against these indexes; do not run one query per item. Add pages you create to the index at once.

Also read the Contacts schema once (`notion-fetch` on the data source) and keep the live select options for `status`, `email_status`, `lead_source` and `designation`.

## 2. Collect the batch

Each check adds planned changes; nothing is written yet (except mirror pages and filled emails, see `outreach-mirror.md`). One planned change:

```json
{"page_id": "...", "contact": "Ada Lovelace", "source": "gmail",
 "status_target": "Responded", "props": {"email_status": "Not Found"},
 "log_line": "2026-03-05 — Email reply received (neutral). Action: sweep gmail check.",
 "first_contacted_candidate": "2026-02-27", "decision": null, "needs_you": null}
```

The log line is stored without the `Status →` part; it is added at apply time when Status really changes. One exception: a contact page that the outreach mirror creates at Contacted already holds its touch line with `Status → Contacted` in the create body (`outreach-mirror.md`, Contact). That touch goes into the batch only as a dedupe key, so it is not logged twice.

Backfill First Contacted: take from the index the contacts where `first_contacted` is empty and Status is not `New` (any Status, terminal ones included). Do not run a new query for this. For each, find the date with the date rule in `crm-rules.md` (First Contacted): for rule 1, run one email search `from:<email> OR to:<email>` with the email adapter when it is ok, and use the LinkedIn thread date only if this run already opened it. For rule 3, ignore import lines (`Imported from <source>`, and lines copied from an import) and lines that record adding the contact to the CRM or a campaign (for example `Added to campaign <key> by campaign-build`). The date of an `Imported from <source>` line is never a First Contacted date, under any rule: being imported is not being contacted. Rule 5 needs the created time: use it only from a counted SQL lookup; otherwise skip rule 5 and record a Decision. Add the date to the batch. Record rules 3, 4 and 5 as decisions. For `Archived` and `Disqualified` contacts, use only rules 1 to 4: such a contact may never have been contacted, so the page's created time is not evidence. For a contact whose `lead_source` is the logical option `Import` (through `notion.option_map.contacts.lead_source`), use only message evidence: rule 1, rule 2 or rule 4. Never use rule 3 or rule 5 for it. With no such evidence, skip it: leave First Contacted empty, write nothing for it, and list it under Needs you (a count plus at most 10 names) so the user can fill the date by hand.

## 3. Merge and dedupe

1. Group the planned changes by page.
2. Resolve conflicts with `events.md` (Conflicts inside one run): negative wins, else the highest Status.
3. Keep one log line per date and event name.
4. First Contacted: the earliest candidate date.
5. Drop property changes whose target option is missing from the live schema; list each under Needs you once.

## 4. Apply

Per page, in this order:

1. Fresh read of the page: properties and body (`notion-fetch`). Do not use the index values for gates.
2. Gates (`crm-rules.md`, Gates before any Status write). Compute the final Status change, if any. Normalize a fetched body first (`notion-access.md`, Exact copy text), then drop log lines whose date and event already exist on the page.
3. Property write, one call per page:
   - MCP: `notion-update-page` with the properties command from its schema. Select = option name string; date = `date:<property>:start`; checkbox = `__YES__`; relation = the full id list (`notion-access.md`, Payload rules, MCP).
   - Never write `first_contacted` when it is not empty. Never clear `do_not_contact`.
4. Body append:
   - MCP: `notion-update-page`, command `insert_content`, position end, one paragraph per log line, with a blank line between lines (a single newline merges them into one paragraph).
   - Never use `replace_content` or `update_content` on a contact, company or campaign page.
5. A failed Status write: retry once after 2 seconds; if it fails again, append `YYYY-MM-DD — STATUS_UPDATE_FAILED: Status not updated to <target>. Fix by hand.` and list it under Needs you.
6. A Notion error about deleting child pages or databases is a hard stop for that page: do not retry with another payload; list it under Needs you.

Meetings pages from `meetings.md` are created before the contact pages they link.

With `dry-run`, stop before step 3: print the merged batch as the plan and write nothing.

## 5. Verify

Re-read every changed page. Check the Status, each new log line, First Contacted, and any relation you changed. List every mismatch in the run log under CRM changes as `mismatch: <contact> — <what>`, and under Needs you.

## 6. Cursors

The cursor for each adapter is the newest point it read completely. For each adapter, decide:

- finished: it read everything back to its old cursor, and its changes were applied and verified;
- incomplete: it stopped early (a page cap it could not pass, a failed page, a partial campaign);
- blocked.

Write cursors only for finished adapters, after step 5: Read `state.json`, replace the value under `adapters.<adapter>`, and Write the file back (`${CLAUDE_PLUGIN_ROOT}/reference/config.md`, No Python, step 6). The cursor shape is in each adapter file (Cursor). The write replaces the whole value for that key, so merge maps (outreach `log_cursors` or `campaign_cursors`) with the old value first. For an outreach tool with some failed campaigns, move only the campaigns that finished.

An incomplete or blocked adapter keeps its old cursor. With `dry-run`, move no cursor.

Outreach incomplete: when an outreach adapter is incomplete (it read some campaigns and failed others), its unmirrored contacts have no pages yet, so a reply from them in email or LinkedIn is unmatched this run. Then the email cursor (`gmail` or `outlook-mail`) and the LinkedIn messages cursor (`linkedin-messages`) move no later than the earliest unmirrored event date: the oldest event of a failed campaign that this run did not mirror, or, when that date is unknown, the failed campaign's old cursor date (for a log-id cursor, the date of that log row; if that is unknown too, keep the old email and LinkedIn message cursors). The next run then reads those replies again and matches them to the new pages. The LinkedIn connections cursor (`top_profile`) is a profile, not a date, and moves as usual; an accept from an unmirrored contact is listed as unmatched and repaired by dedupe on a later run. Say in the run log which cursors were held back and why.

LinkedIn connections is the one exception: a read that stopped at the 60-row cap still moves its cursor, and the run log says "gap possible" (`${CLAUDE_PLUGIN_ROOT}/adapters/linkedin/chrome.md`).

## Limits on long runs

Keep each shell command under about 100 seconds.
