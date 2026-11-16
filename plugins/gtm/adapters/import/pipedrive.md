# import: pipedrive

## Purpose

Reads persons, organizations, deals, notes and activities from Pipedrive for `/gtm:import`. Read-only.

## Tool

Preferred: a Pipedrive MCP connector in the session. Find it with ToolSearch (`pipedrive persons deals organizations`), read each tool's schema, and use only its list and get tools. Never call a tool that adds, updates, merges or deletes anything.

Otherwise: `${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py pipedrive`, secret `pipedrive_api_token`. Run `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py tools` for the allowed GET paths. The token is sent in a header, never in the URL.

How the user gets the token: in Pipedrive, avatar menu → Personal preferences → API → copy the personal API token. The token has the same rights as the user; the read-only client is the limit on our side. Then, in their own terminal:

```
python3 -I -B <absolute plugin root>/lib/config.py set-secret pipedrive_api_token
```

Claude Code only; in Cowork use the connector or a CSV export.

Never ask for the token in the chat.

Fallback: CSV export (`${CLAUDE_PLUGIN_ROOT}/adapters/import/csv.md`).

## Preflight check

- Connector: list one person. Auth error or missing tools = blocked.
- API: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py pipedrive check`. Exit 0 = ok, 2 = blocked. Not with `runtime` = `cowork` or without Python (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`, Cowork).

## Read procedure

Write every response to `<run>/raw/` (the run folder from `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`) with `--out`. Prefer the v2 endpoints; use v1 for objects v2 does not list here (notes, field definitions).

Paging:
- v2 (`/api/v2/...`): `--param limit=500`, then repeat with `--param cursor=<additional_data.next_cursor>` until `next_cursor` is null or absent.
- v1 (`/v1/...`): `--param limit=500 --param start=<n>`, repeat with `start=<additional_data.pagination.next_start>` while `additional_data.pagination.more_items_in_collection` is true.

If any page fails, the read is incomplete; stop before planning.

1. Fields: `get /v1/personFields`, `get /v1/organizationFields`, `get /v1/dealFields` to learn custom field keys and option labels (custom values come back as hashed keys and option ids).
2. Pipelines and stages: `get /api/v2/pipelines`, `get /api/v2/stages`.
3. Organizations: `get /api/v2/organizations`.
4. Persons: `get /api/v2/persons`.
5. Deals: `get /api/v2/deals` (open and closed; add `--param status=...` only if the user wants a subset).
6. History, if the user wants it: `get /api/v2/activities` (done activities: type, subject, due date, person) and `get /v1/notes` (content, add time, person). Keep the most recent 20 per person unless the user asks for all.
7. Flatten as in `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Flatten. Field defaults:

| Pipedrive field | CSV column |
|---|---|
| person `name` (or `first_name`, `last_name`) | Name |
| primary entry of `emails` (v2) / `email` (v1) | Email |
| primary entry of `phones` / `phone` | Phone |
| a custom field holding the LinkedIn URL (ask) | LinkedIn URL |
| a custom job title field, if any | Job Title |
| linked organization `name`, its website custom field or `address` | Company, Company Website, Headquarters |
| organization employee count field, if any | Employees |
| label or the custom status field the user names | Lead Status |
| `marketing_status` = unsubscribed | Do Not Contact |
| earliest done email or call activity date | First Contacted |
| person id | Source ID `pipedrive:person:<id>` |

Resolve custom option ids to labels with the field definitions from step 1. When persons have no status field, derive one as in `${CLAUDE_PLUGIN_ROOT}/skills/import/references/status-mapping.md`, Pipedrive.

Deals: `title` → name, `stage_id` → stage label → stage table, `value` → value, `expected_close_date` → expected close, `org_id` → company, `person_id` (plus participants if the user wants) → contacts.

## Output

Not normalized events: `contacts.csv`, `deals.json`, `activities.json` in the run folder, then the `csv_import.py` plan.

## Cursor

None. Progress lives under `state.json` `adapters.import` and `done.jsonl` (apply.md, Progress and resume).

## Rate limits

Pipedrive limits requests per token in a rolling window, and the limit depends on the plan. On HTTP 429, readonly_api retries with backoff and honours `Retry-After`. If it still fails, stop, save progress, and tell the user to run `/gtm:import resume` later.

## Blocked signs and fix

| Sign | Fix |
|---|---|
| Connector tools missing | "Add the Pipedrive connector in Claude settings, or save your API token with set-secret pipedrive_api_token, or export a CSV." (Claude Code only. In Cowork: "Connect a connector for pipedrive, or export a CSV.") |
| `check` exit 2 with 401 | "The Pipedrive token is invalid. Copy it again from Personal preferences → API and run set-secret pipedrive_api_token." (Claude Code only. In Cowork: "Connect a connector for pipedrive, or export a CSV.") |
| 404 or 410 on an endpoint | The API version changed. Report the path; use the CSV export meanwhile. |

## Write / send capability

None. Read-only.
