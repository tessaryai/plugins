# import: attio

## Purpose

Reads people, companies and deals (and notes, when the connector offers them) from Attio for `/gtm:import`. Read-only.

## Tool

Preferred: an Attio MCP connector in the session. Find it with ToolSearch (`attio records objects people companies`), read each tool's schema, and use only its list, query, search and get tools. Never call a tool that creates, updates, asserts or deletes records, entries, notes or tasks.

The read-only API client cannot list Attio records: Attio's record listing is a POST query (`/v2/objects/{object}/records/query`), and `${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py` sends GET only. `readonly_api.py attio` can check the key (`/v2/self`), list objects and attributes, and fetch a single record by id, which is not enough for an import.

So without a connector, use the CSV export (`${CLAUDE_PLUGIN_ROOT}/adapters/import/csv.md`): in Attio, open the People object (or the list to import) → … → Export as CSV; do the same for Companies if the user wants company fields beyond name and domain.

If the user has an Attio key saved (`attio_api_key`, via `python3 -I -B <absolute plugin root>/lib/config.py set-secret attio_api_key` in their own terminal), use it only for the preflight and to read attribute definitions (`/v2/objects/people/attributes`), which helps map status options.

## Preflight check

- Connector: one cheap read (list objects, or query one person). Auth error or missing tools = blocked; offer the CSV path.
- Key only: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py attio check`. Exit 0 = the key works, but the import still goes through CSV.

## Read procedure

These steps use the connector. Without one, follow the Read procedure of the csv adapter on the exported file.

Write each response to `<run>/raw/` (the run folder from `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`).

1. Objects and attributes: list the objects (`people`, `companies`, `deals` if enabled) and their attributes, so you know the slugs of email, LinkedIn, job title, status and any custom fields.
2. Companies, then people, then deals: query each object page by page with the paging the tool defines (limit and offset, or a cursor) until a page comes back short or empty. If any page fails, the read is incomplete; stop before planning.
3. If the user imports from a list (for example a sales pipeline list), read its entries too: the list's stage attribute is the status or deal stage to map.
4. Notes, if the tool offers them and the user wants history: keep the most recent 20 per person.
5. Flatten as in `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Flatten. Field defaults:

| Attio attribute | CSV column |
|---|---|
| `name` (first, last, full) | First Name, Last Name |
| `email_addresses` (first entry) | Email |
| `linkedin` | LinkedIn URL |
| `phone_numbers` (first entry) | Phone |
| `primary_location` | Location |
| `job_title` | Job Title |
| `company` record → `name`, `domains` (first) | Company, Company Website |
| company `employee_range`, `linkedin` | Employees, Company LinkedIn |
| list stage or a status attribute the user names | Lead Status |
| person record id | Source ID `attio:person:<id>` |

Attribute slugs differ per workspace. Use the attribute list from step 1 and ask about anything unclear.

## Output

Not normalized events: `contacts.csv` (and `deals.json`, `activities.json` when read) in the run folder, then the `csv_import.py` plan.

## Cursor

None. Progress lives under `state.json` `adapters.import` and `done.jsonl` (apply.md, Progress and resume).

## Rate limits

Attio limits reads per second per workspace. On a rate-limit error from the connector, wait a few seconds and repeat the same page once; if it fails again, stop, save progress, and offer `/gtm:import resume` or the CSV path.

## Blocked signs and fix

| Sign | Fix |
|---|---|
| No Attio connector | "Add the Attio connector in Claude settings, or export People as CSV from Attio." |
| Connector auth error | "Reconnect the Attio connector in Claude settings." |
| `attio check` exit 2 | "The Attio key is invalid or lacks read scopes. Create a new key with read access and run set-secret attio_api_key." |

## Write / send capability

None. Read-only.
