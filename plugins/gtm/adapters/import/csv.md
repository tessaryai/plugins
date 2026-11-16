# import: csv

## Purpose

Reads a CSV file exported from any CRM or spreadsheet (Google Sheets, Excel, Salesforce, Airtable, HubSpot, Pipedrive, Attio, Close, Zoho, Copper, and others) for `/gtm:import`. This is also the fallback path for HubSpot, Pipedrive and Attio when no connector is available. This edition takes a file of about 200 rows or fewer; a larger file needs Tessary GTM Pro (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 2).

## Tool

No connector or key. Read the file with the Read tool, and map and plan it yourself (`${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Flatten and Plan by hand). The delimiter can be a comma, semicolon, tab or pipe; ignore a UTF-8 byte order mark at the start.

How to get the file, per source (tell the user the steps; never sign in for them):

| Source | Export |
|---|---|
| Google Sheets | File → Download → Comma-separated values (.csv), current sheet. One sheet per file. |
| Excel / Numbers | Save as or Export → CSV (UTF-8). |
| Salesforce | Reports → new Contacts or Leads report with the columns you need (include Contact ID or Lead ID, Email, Lead Status, Email Opt Out) → Export → Details only, CSV. Or Setup → Data Export. |
| Airtable | Open the view → view menu → Download CSV. |
| HubSpot | Contacts → Export → CSV, all properties (include Record ID). |
| Pipedrive | Contacts → People → … → Export filter results → CSV. |
| Attio | Open the People object or a list → … → Export as CSV. |

Ask the user to save the file inside the working directory or give its full path. Copy it to `<run>/contacts.csv` before you work on it (`<run>` is the run folder from `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`).

## Preflight check

1. The file exists, is readable, and is not empty.
2. At least one column holds an email or a LinkedIn URL. If none does, ask which columns hold the email and the LinkedIn URL. Without either, every row is skipped (no stable key) unless the user agrees to keyless rows and the file has a record id column.
3. Say the row count and the column list back to the user. Count the data rows before you create the run folder or copy the file. More than about 200: stop with the upgrade message (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 2).

Blocked: never. A bad file is an input error; ask for another export.

## Read procedure

1. Propose the mapping (`${CLAUDE_PLUGIN_ROOT}/skills/import/SKILL.md`, step 4). Show columns, three sample rows and the proposal.
2. Fix the mapping with the user. Map each useful unmapped column to `extra` (it becomes a `Column: value` line in Notes). Map columns you do not want to `null`. Map the record id column, if any, to `source_id` as described in `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Flatten. Map last-activity columns (`Last Contacted`, `Last Activity Date`) to `null`; they are not the first contact date.
3. Columns with a company: map the company name to `company` and its website or domain to `company_website`. The plan takes a company domain from a work email when the website is missing; free-mail domains and your own domains are never used.
4. A file with deals or activities (for example a separate deals export): ask for it as a second file, and turn it into `deals.json` or `activities.json` in the formats of apply.md with the Write tool, copying each value from the file.
5. Continue with `/gtm:import` step 4.

## Output

Not normalized events. The output is the plan JSON that you write (apply.md, Plan by hand): `creates`, `updates`, `skips`, `conflicts`, `companies {create, existing}`, `warnings`, `summary`. Rows with no name, email or LinkedIn are skipped; rows with an owner address are skipped as `owner address` unless the user asks to include them; rows with no email and no LinkedIn are skipped unless the user asks for keyless rows. A duplicate row inside the file (same email, LinkedIn URL or Source ID) fills the empty fields of the first row, adds its Notes lines, and is listed in skips with `merged_into` and `merged_fields`; a field where the two rows differ keeps the first value and gets a warning. A row whose keys point at different rows or different existing contacts is a conflict. An update carries `match_on`: `source_id`, `linkedin` or `email`. Each contact carries `source_fields` (first name, company, title) when those columns are mapped.

## Cursor

None. An import run keeps its progress in `adapters.import` in `state.json` and in `<run>/done.jsonl` (`${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Progress and resume).

## Blocked signs and fix

None. Input problems and their fixes:

| Sign | Fix |
|---|---|
| All text in one column | The delimiter was not detected. Re-export as comma-separated UTF-8. |
| Garbled accents | Re-export as UTF-8. |
| The mapping names columns not in the file | The mapping was made for another file. Propose it again. |
| Very wide file (hundreds of columns) | Map only the useful columns; the rest to `null`. |

## Write / send capability

None. Read-only.
