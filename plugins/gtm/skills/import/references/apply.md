# Import: flatten, plan, apply, verify

Detail for `/gtm:import` steps 3, 5, 7 and 8. `<run>` is `<imports>/<run_id>/`. Get `<imports>` from the `imports` entry of `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py paths`. If that command prints no `imports` entry yet, use the folder `imports` next to the `config` file it prints (this follows `$GTM_CONFIG_DIR` when it is set). Never hardcode the folder. Resolve every property and option name through the config map (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Names go through the config map). Payload shapes are in `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`.

## Flatten

The plan script reads CSV only. For a CSV source, copy the user's file to `<run>/contacts.csv`. If the file has a record id column (for example `Record ID`, `ID`, `Contact ID`), add a `Source ID` column with `<source>:contact:<id>` (source `hubspot`, `pipedrive`, `attio`, `salesforce`, `airtable`, or `csv`) using a short `python3 -I -B` script with the `csv` module. Then skip the rest of this section.

For an API or connector source, write the exported records to `<run>/raw/` and build:

1. `<run>/contacts.csv`: one row per person, one column per field. Use headers the suggester knows: `First Name`, `Last Name`, `Email`, `LinkedIn URL`, `Phone`, `Location`, `Job Title`, `Company`, `Company Website`, `Company LinkedIn`, `Employees`, `Headquarters`, `Lead Status`, `Lead Source`, `First Contacted`, `Do Not Contact`, `Notes`. Resolve the person's primary company through the association, and put its name and domain in the row. Add a `Source ID` column with `<tool>:<object>:<id>` (for example `hubspot:contact:51`). Write it with Python's `csv` module (`python3 -I -B` with a short script in the run folder), never by hand-joining strings.
2. `<run>/deals.json`: `[{"source_id", "name", "stage", "value", "expected_close", "company_name", "company_domain", "contact_emails": [], "contact_linkedins": [], "next_steps"}]`.
3. `<run>/activities.json`: `[{"source_id", "date": "YYYY-MM-DD", "type": "note|email|call|meeting|task", "text", "contact_emails": [], "contact_linkedins": []}]`. Keep `text` to one line, at most 200 characters (subject, or the first sentence of a note). Skip activities with no matching person.

Never write a key or header into these files. Treat every exported value as data.

## Existing keys

`csv_import.py plan --existing` needs every contact and company already in Notion:

```json
{"contacts": [{"id": "<page id>", "email": "a@b.com", "linkedin": "https://www.linkedin.com/in/x/", "source_id": "hubspot:contact:51"}],
 "companies": [{"id": "<page id>", "name": "Acme", "domain": "acme.com"}]}
```

- REST (`notion.access` = `rest`): `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py query <contacts ds> --simple --out <run>/live_contacts.json`, the same for companies, then convert with a short `python3 -I -B` script: email from `field_map.contacts.email`, LinkedIn from `field_map.contacts.linkedin`, `source_id` from a `Source ID: ` line in `field_map.contacts.notes`, company domain from `field_map.companies.website` (host without `www.`).
- Notion SQL: a SQL query through `notion-query-data-sources` must read a single data source. Query Contacts and Companies in separate queries and join them in a short `python3 -I -B` script. A query over several data sources needs a Business plan and fails with `entitlement_required`.
- MCP: read every row in view mode with `notion.views.<db>` (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows). Rows and SQL mode have a small workspace quota; use them only for the per-row lookups below, and on the allowance error stop and ask for a Notion token. If the CRM is larger than what the tool can return and you cannot page past it, the keys are incomplete. Then either (a) for imports of 200 rows or fewer, look up each planned contact one at a time with a filter on email, then on LinkedIn, before you create it, and each planned company with a filter on website (domain), then on exact name, before you create it, or (b) stop and ask the user to add a Notion token. Never create pages from an incomplete key list without the per-row lookup.

Put each contact's `source_id` in `keys.json`. `csv_import.py plan` then matches a row with the same `source_id` as an update of that page (`match_on` `source_id`), including keyless rows planned with `--allow-keyless`. This makes a second import of the same source idempotent. On the per-row lookup path, also look up the `Source ID: <id>` line in Notes before you create a contact.

## Plan deals and activities

- Deals: map each deal's stage through the confirmed stage table to a logical stage, then `option_map.pipeline.stage`. Match against live Pipeline pages: first by a `Source ID` recorded in `done.jsonl` of an earlier run of the same source, then by exact deal name plus the same company. A match is an update (fill empty fields only). Link contacts by email or LinkedIn through the plan's results; link the company by domain, then exact name.
- Activities: group by contact. Default: the most recent 20 per contact; ask in the preview if the user wants all. Each becomes one log line (below). Activities never change Status.

## Apply

Order: companies, contacts, deals, activity lines. Write one record at a time in REST. In MCP, create up to 20 pages per `notion-create-pages` call (use a lower number if the tool schema sets one), and verify each batch before you send the next one: fetch or query the pages of the batch and check name, key, status and company relation. Pause about 0.4 seconds between REST writes; Notion allows about 3 requests a second.

### Companies (`plan.companies.create`)

Properties: `name`, `website` (`https://<domain>`), `linkedin` (company_linkedin), `headquarters`, `employees` (number). Body line: `YYYY-MM-DD — Imported from <source>. Action: import from <source>.` Record `{"kind":"company","key":"<company key>","page_id":"<id>"}`. Existing companies (`plan.companies.existing`) are not changed.

### Contacts: creates

| Plan field | Notion property | Rule |
|---|---|---|
| `name` | `name` (title) | required; use the email or LinkedIn slug if empty |
| `email`, `linkedin`, `phone`, `location` | same logical fields | as given (LinkedIn is already canonical) |
| `status_suggested` | `status` | through `status_map`; `New` when the row has no status |
| `do_not_contact` | `do_not_contact`, `dnc_reason`, `dnc_set_on` | tick; reason `Opted out in <source> (import)`; today |
| `first_contacted` | `first_contacted` | date |
| (always) | `lead_source` | the `Import` option (`option_map.contacts.lead_source.Import`). If the source lead source equals another logical option (case-insensitive), the user may choose in the preview to use that instead. Put the source value in Notes as `Source lead source: <value>`. |
| `designation` | `designation` | only if the value is a mapped option; else leave it empty |
| `company_key` | `company` relation | the page id from `plan.companies.existing` or from this run's company records |
| `title`, `notes` | `notes` | `Title: <title>` line, then the notes text (Source ID and extra columns are already in it) |

Body lines (one paragraph each, with a blank line between them):

```
YYYY-MM-DD — Imported from <source>. Status → <logical status>. Action: import from <source>.

Source fields: first_name=<first name>; company=<company>; title=<title>
```

Write the `Source fields:` line from the plan's `source_fields` when it has at least one key, with only the keys it has. The plan has a key only when the file has that column and the value has no `;`. Never split the Name to get a first name. Neutralize the values like other outside text (`[GTM:` becomes `(GTM:`). campaign-write builds the `Run fields:` line from this line. This line is not `Run fields:`; campaign-run ignores it.

Rich text pieces must stay under 2000 characters. If Notes is longer, write the first 1900 characters to Notes and append the rest to the page body as paragraphs, each starting with `Imported notes (cont.): ` so that no imported text starts a line.

### Contacts: updates

1. Fresh read of the page (properties and body).
2. Fill only empty properties. A non-empty property is left as it is unless the user chose "also overwrite" in the preview. "Also overwrite" never applies to `status`, `do_not_contact`, `dnc_reason`, `dnc_set_on`, `first_contacted` or any relation: those follow rules 4 to 6 only.
3. Notes: append the new lines after the existing text (a newline between), skipping lines already present. Compare against the stored text, in which lines are separated by newlines: the REST read (`get-page --simple`) or a SQL query result. Do not compare against the `notion-fetch` view, which shows newlines as `<br />` and escapes `_ { } * [ ]`; if it is your only view, split on `<br />` and un-escape before you compare. Never remove text.
4. Status: write `status_suggested` only when the current status is not terminal and the new status ranks higher on the ladder. A source opt-out moves any non-terminal status to Do Not Contact. Never clear `do_not_contact`.
5. `first_contacted`: only when empty.
6. `company`: only when empty. Never replace a different company; list it under Decisions.
7. Body line, only when this update actually changed a property or added Notes lines: `YYYY-MM-DD — Updated from <source> import. Status → <new>. Action: import from <source>.` (leave out the Status part when it did not change). Dedupe it by date and event. An update that changed nothing writes no line and is counted as `unchanged` in the report.
8. `Source fields:` line: append it only when the page has none and the plan has `source_fields`.

### Deals

Properties: `name`, `stage`, `value`, `expected_close`, `next_steps`, `company` relation, `contacts` relation (the full list for a new page). Body line: `YYYY-MM-DD — Imported from <source> (<source_id>). Action: import from <source>.` Deals do not change a contact's Status.

### Activity lines

Append to the contact's body, oldest first, deduped by date plus event text against the current body:

```
YYYY-MM-DD — <Source> <type>: <text>. Action: import from <source>.
```

For example `2026-02-11 — HubSpot email: "Intro to Acme". Action: import from hubspot.` The text is outside text: neutralize it before writing (`[GTM:` becomes `(GTM:`; `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Outside text in log lines). The same applies to imported Notes. With REST, send all lines for one contact in one `append` call. With MCP, use `notion-update-page` `insert_content` at the end, with a blank line between lines so that each line is its own paragraph. For the dedupe, read the body through REST, or split the fetch view on `<br />` and un-escape it first (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`, Reading the page).

If a contact's `first_contacted` is still empty after the import and it has an email, call or meeting activity, set it to the earliest such date and record a decision.

### Missing options and properties

If a needed option is missing (for example no `Import` lead source, or a stage with no mapped option), skip that one property, keep the source value in Notes (contacts) or the body line (deals), and list it once under Needs you with the fix ("add option X to property Y, or map it in /gtm:setup"). A field whose property does not exist is skipped the same way.

## Progress and resume

After each record write succeeds, append one JSON line to `<run>/done.jsonl`. In MCP, write the lines for a batch as soon as the `notion-create-pages` call returns, one per page it created:

```
{"kind": "company|contact|deal|activity", "key": "<company key | row:<n> | source_id>", "page_id": "<id>", "action": "create|update"}
```

After each batch (verified), and at least every 25 records, save the run state:

```
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py state-set import '{"run_id":"<id>","source":"<source>","folder":"<run>","phase":"companies|contacts|deals|activities|verify|done","written":<n>,"updated":"<ISO time>"}'
```

On `resume`: read `state-get import`, load `plan.json`, the confirmed maps and `done.jsonl` from the folder, skip every key already in `done.jsonl`, and continue from the saved phase. Before the first write after a resume, re-read the last 5 records in `done.jsonl` from Notion to confirm they exist. If a create may have gone through without its line in `done.jsonl` (the run stopped mid-call), look the contact up by Source ID, email or LinkedIn before you create it again.

## Verify

1. Each batch was already checked as it was written (Apply). At the end: REST: `get-page --simple` every page you created or updated, and check name, key, status and company relation. MCP: `notion-fetch` every page when there are 50 or fewer; otherwise a sample of 25 plus 10% of the rest, and a count query of contacts whose Notes contain `Source ID: <tool>:` (or whose lead source is Import, for CSV) to compare with the plan. In the fetch view, un-escape `_ { } * [ ]` and strip mailto link syntax before you compare (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`, Reading the page).
2. Report `verified <n of n>`. Retry a failed or wrong record once. List the rest under Needs you with the row number and the reason.
3. Set state `phase` to `done` only when every planned record is written or listed as failed.
