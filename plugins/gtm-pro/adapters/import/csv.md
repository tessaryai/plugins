# import: csv

## Purpose

Reads a CSV file exported from any CRM or spreadsheet (Google Sheets, Excel, Salesforce, Airtable, HubSpot, Pipedrive, Attio, Close, Zoho, Copper, and others) for `/gtm-pro:import`. This is also the fallback path for HubSpot, Pipedrive and Attio when no connector or key is available.

## Tool

No connector or key. The file is read by `${CLAUDE_PLUGIN_ROOT}/lib/csv_import.py`:

```
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/csv_import.py fields
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/csv_import.py suggest <file.csv> [--out mapping.json]
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/csv_import.py plan <file.csv> --mapping mapping.json [--existing keys.json] [--allow-keyless]
    [--owner-emails a@x.com,b@x.com] [--own-domains x.com] [--include-owner] [--out plan.json]
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/csv_import.py self-test
```

Without `--owner-emails` and `--own-domains`, `plan` reads `owner.emails` and `owner.own_domains` from the config. `self-test` checks the planner against a built-in sample file and exits 0 when every check passes.

The script never writes to Notion and never reaches the network. It detects the delimiter (comma, semicolon, tab, pipe) and strips a UTF-8 byte order mark.

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
2. `csv_import.py suggest <file>` exits 0 and shows at least one column mapped to `email` or `linkedin`. If none is, ask which columns hold the email and the LinkedIn URL. Without either, every row is skipped (no stable key) unless the user agrees to `--allow-keyless` and the file has a record id column.
3. Say the row count and the column list back to the user.

Blocked: never. A bad file is an input error; ask for another export.

## Read procedure

1. `suggest` the mapping. Show columns, three sample rows and the guess.
2. Fix the mapping with the user. Map each useful unmapped column to `extra` (it becomes a `Column: value` line in Notes). Map columns you do not want to `null`. Map the record id column, if any, to `extra` and also add a `Source ID` column as described in `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Flatten. The `Source ID` column maps to `source_id`. Map last-activity columns (`Last Contacted`, `Last Activity Date`) to `null`; they are not the first contact date.
3. Columns with a company: map the company name to `company` and its website or domain to `company_website`. The plan derives a company domain from a work email when the website is missing; free-mail domains and your own domains are never used.
4. A file with deals or activities (for example a separate deals export): ask for it as a second file, and turn it into `deals.json` or `activities.json` in the formats of apply.md with a short `python3 -I -B` script.
5. Continue with `/gtm-pro:import` step 4.

## Output

Not normalized events. The output is the plan JSON from `csv_import.py plan`: `creates`, `updates`, `skips`, `conflicts`, `companies {create, existing}`, `warnings`, `summary`. Rows with no name, email or LinkedIn are skipped; rows with an owner address are skipped as `owner address` unless `--include-owner`; rows with no email and no LinkedIn are skipped unless `--allow-keyless`. A duplicate row inside the file (same email, LinkedIn URL or Source ID) fills the empty fields of the first row, adds its Notes lines, and is listed in skips with `merged_into` and `merged_fields`; a field where the two rows differ keeps the first value and gets a warning. A row whose keys point at different rows or different existing contacts is a conflict. An update carries `match_on`: `source_id`, `linkedin` or `email`. Each contact carries `source_fields` (first name, company, title) when those columns are mapped.

## Cursor

None. An import run keeps its progress under `state-get import` and in `<run>/done.jsonl` (`${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Progress and resume).

## Blocked signs and fix

None. Input problems and their fixes:

| Sign | Fix |
|---|---|
| All text in one column | The delimiter was not detected. Re-export as comma-separated UTF-8. |
| Garbled accents | Re-export as UTF-8. |
| `mapping names columns not in the file` | The mapping was made for another file. Run `suggest` again. |
| Very wide file (hundreds of columns) | Map only the useful columns; the rest to `null`. |

## Write / send capability

None. Read-only.
