# Sweep: CRM index, batch, verify, cursors

How the sweep reads the CRM, collects changes, writes them once, checks them and moves cursors. Notion paths follow `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`. Write every scratch file in the session scratchpad.

## 1. CRM index (before the checks)

The checks need to match many addresses and LinkedIn URLs. Build one index of contacts at the start, then match in memory.

Fields to read per contact: page id, `name`, `email`, `linkedin`, `status`, `do_not_contact`, `first_contacted`, `notes` (for `<Tool> contact id:` lines), `company`, `campaign`, created time.

- REST path (token present, `notion.access` = `rest`): `python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py query <contacts id> --simple --out <s>/contacts.json`. It reads all pages.
- MCP path: `notion-query-data-sources` on the Contacts data source. Pick a mode from the live schema that reads every row (`notion-access.md`, MCP Query). Rows mode returns at most 100 rows with no cursor, so for a larger CRM either page with the mode that has a cursor or offset, or split the query (by Status option, then by created-date windows) until each part returns fewer than 100 rows.
- If the full index cannot be read (usage cap, no paging), fall back to targeted lookups: after each check, query Contacts once per key you need (`email` equals X, `linkedin` contains `/in/<slug>`), batching keys with an `or` filter where the tool allows. Note in the run log that the index was partial, and suggest under Needs you that the user add a Notion token in `/gtm:setup`.

Canonicalize LinkedIn URLs on both sides before comparing (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Matching). Index the domains of contact emails too, for the domain rule.

New pages created during the run (outreach mirror) are added to the index at once.

Also read the Contacts schema once (`notion-fetch` on the data source, or `notion_rest.py schema <contacts id>`) and keep the live select options for `status`, `email_status`, `lead_source` and `designation`.

## 2. Collect the batch

Each check adds planned changes; nothing is written yet (except mirror pages and filled emails, see `outreach-mirror.md`). One planned change:

```json
{"page_id": "...", "contact": "Ada Lovelace", "source": "gmail",
 "status_target": "Responded", "props": {"email_status": "Not Found"},
 "log_line": "2026-03-05 — Email reply received (neutral). Action: sweep gmail check.",
 "first_contacted_candidate": "2026-02-27", "decision": null, "needs_you": null}
```

The log line is stored without the `Status →` part; it is added at apply time when Status really changes.

Backfill First Contacted: query Contacts where `first_contacted` is empty and Status is not `New` (any Status, terminal ones included). For each, find the date with the date rule in `crm-rules.md` (First Contacted): for rule 1, run one email search `from:<email> OR to:<email>` with the email adapter when it is ok, and use the LinkedIn thread date only if this run already opened it. Add the date to the batch. Record rules 3, 4 and 5 as decisions. For `Archived` and `Disqualified` contacts, use only rules 1 to 4: such a contact may never have been contacted, so the page's created date is not evidence.

## 3. Merge and dedupe

1. Group the planned changes by page.
2. Resolve conflicts with `events.md` (Conflicts inside one run): negative wins, else the highest Status.
3. Keep one log line per date and event name.
4. First Contacted: the earliest candidate date.
5. Drop property changes whose target option is missing from the live schema; list each under Needs you once.

## 4. Apply

Per page, in this order:

1. Fresh read of the page: properties and body (MCP `notion-fetch`, or REST `get-page --simple` and `blocks`). Do not use the index values for gates.
2. Gates (`crm-rules.md`, Gates before any Status write). Compute the final Status change, if any. Drop log lines whose date and event already exist on the page.
3. Property write, one call per page:
   - MCP: `notion-update-page` with the properties command from its schema. Select = option name string; date = `date:<property>:start`; checkbox = `__YES__`; relation = the full id list (`notion-access.md`, Payload rules, MCP).
   - REST: `notion_rest.py update <page_id> --in <s>/upd-<n>.json` with `{"properties": {...}}` in REST shape. Status as a `select` payload, unless `notion.select_payload` says `status` for it.
   - Never write `first_contacted` when it is not empty. Never clear `do_not_contact`.
4. Body append:
   - MCP: `notion-update-page`, command `insert_content`, position end, one paragraph per log line.
   - REST: `notion_rest.py append <page_id> --in <s>/app-<n>.json` (a JSON array of strings).
   - Never use `replace_content` or `update_content` on a contact, company or campaign page.
5. A failed Status write: retry once after 2 seconds; if it fails again, append `YYYY-MM-DD — STATUS_UPDATE_FAILED: Status not updated to <target>. Fix by hand.` and list it under Needs you.
6. A Notion error about deleting child pages or databases is a hard stop for that page: do not retry with another payload; list it under Needs you.

Meetings pages from `meetings.md` are created before the contact pages they link.

With `dry-run`, stop before step 3: print the merged batch as the plan and write nothing.

## 5. Verify

Re-read every changed page. Check the Status, each new log line, First Contacted, and any relation you changed. List every mismatch in the run log under CRM changes as `mismatch: <contact> — <what>`, and under Needs you.

## 6. Cursors

For each adapter, decide:

- finished: it read everything back to its old cursor, and its changes were applied and verified;
- incomplete: it stopped early (a page cap it could not pass, a failed page, a partial campaign);
- blocked.

Write cursors only for finished adapters, after step 5: `python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/config.py state-set <adapter> '<json>'`. The cursor shape is in each adapter file (Cursor). `state-set` replaces the whole value for that key, so merge maps (outreach `log_cursors` or `campaign_cursors`) with the old value first (`state-get <adapter>`). For an outreach tool with some failed campaigns, move only the campaigns that finished.

An incomplete or blocked adapter keeps its old cursor. With `dry-run`, move no cursor.

LinkedIn connections is the one exception: a read that stopped at the 60-row cap still moves its cursor, and the run log says "gap possible" (`${CLAUDE_PLUGIN_ROOT}/adapters/linkedin/chrome.md`).

## Limits on long runs

Keep each shell command under about 100 seconds. Process large REST batches in chunks of about 50 pages per command. Keep scripts short and in the scratchpad.
