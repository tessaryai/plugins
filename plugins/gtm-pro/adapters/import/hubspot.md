# import: hubspot

## Purpose

Reads contacts, companies, deals and engagement history (notes, emails, calls, meetings) from HubSpot for `/gtm-pro:import`. Read-only.

## Tool

Preferred: a HubSpot MCP connector in the session. Find it with ToolSearch (`hubspot contacts companies deals`), read each tool's schema, and use only its list, get, search and property-read tools. Never call a tool that creates, updates, merges, deletes or associates records.

Otherwise: `${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py hubspot`, secret `hubspot_token`. Run `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py tools` for the allowed GET paths.

How the user gets a token: in HubSpot, Settings → Integrations → Private Apps (newer accounts: Development → Legacy apps → Private app) → create a private app with read-only scopes only: `crm.objects.contacts.read`, `crm.objects.companies.read`, `crm.objects.deals.read`, `crm.schemas.contacts.read`, `crm.schemas.deals.read` (plus `crm.objects.owners.read` if they want owners). Copy the access token, then run in their own terminal (Claude Code only; in Cowork use the connector or a CSV export):

```
python3 -I -B <absolute plugin root>/lib/config.py set-secret hubspot_token
```

Never ask for the token in the chat.

Fallback: CSV export (`${CLAUDE_PLUGIN_ROOT}/adapters/import/csv.md`).

## Preflight check

- Connector: one cheap read (list one contact). Auth error or missing tools = blocked.
- API: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py hubspot check`. Exit 0 = ok, 2 = blocked. A 403 on a later object means a missing scope; report which object. Not with `runtime` = `cowork` or without Python (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`, Cowork).

## Read procedure

Write every response to `<run>/raw/` (the run folder from `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`) with `--out`. Paging: repeat with `--param after=<paging.next.after>` until the response has no `paging.next`. If any page fails, the read is incomplete; stop before planning.

1. Properties: `get /crm/v3/properties/contacts` (and companies, deals) to learn the internal names of the fields to read, including custom ones the user wants.
2. Pipelines: `get /crm/v3/pipelines/deals` for stage ids → stage labels (needed for the stage table).
3. Companies: `get /crm/v3/objects/companies --param limit=100 --param properties=name,domain,website,linkedin_company_page,numberofemployees,city,country,description`.
4. Contacts: `get /crm/v3/objects/contacts --param limit=100 --param properties=firstname,lastname,email,phone,jobtitle,company,website,city,country,hs_linkedin_url,lifecyclestage,hs_lead_status,hs_email_optout,notes_last_contacted,hs_analytics_source --param associations=companies`.
5. Deals: `get /crm/v3/objects/deals --param limit=100 --param properties=dealname,dealstage,pipeline,amount,closedate,hs_next_step --param associations=contacts,companies`.
6. Engagements (only if the user wants history): `get /crm/v3/objects/notes` (and `emails`, `calls`, `meetings`) with `--param limit=100 --param properties=hs_timestamp,hs_note_body` (emails: `hs_email_subject`, `hs_email_direction`; calls: `hs_call_title`; meetings: `hs_meeting_title`) and `--param associations=contacts`. Keep the most recent 20 per contact unless the user asks for all.
7. Flatten as in `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`, Flatten. Field defaults:

| HubSpot property | CSV column |
|---|---|
| `firstname`, `lastname` | First Name, Last Name |
| `email` | Email |
| `hs_linkedin_url` (if present) | LinkedIn URL |
| `phone` | Phone |
| `city`, `country` | Location (`city, country`) |
| `jobtitle` | Job Title |
| associated company `name`, `domain` (else contact `company`, `website`) | Company, Company Website |
| company `numberofemployees`, `linkedin_company_page` | Employees, Company LinkedIn |
| `hs_lead_status`, else `lifecyclestage` | Lead Status |
| `hs_analytics_source` | Lead Source |
| `notes_last_contacted` is not first contact; leave First Contacted empty | — |
| `hs_email_optout` = true | Do Not Contact |
| contact id | Source ID `hubspot:contact:<id>` |

Some fields above (`hs_linkedin_url`, `hs_email_optout`) may not exist in every portal. Use the property list from step 1; drop what is missing.

The HubSpot search endpoint is POST, so the read-only client cannot use it; the GET list with paging reads everything.

## Output

Not normalized events: `contacts.csv`, `deals.json`, `activities.json` in the run folder, then the `csv_import.py` plan.

## Cursor

None. Progress lives under `state.json` `adapters.import` and `done.jsonl` (apply.md, Progress and resume).

## Rate limits

Private apps get about 100 to 190 requests per 10 seconds depending on the plan, plus a daily cap. On HTTP 429, readonly_api retries with backoff; if it still fails, wait 10 seconds and repeat that page once. Then stop, save progress, and tell the user to run `/gtm-pro:import resume` later. Check the current limits in HubSpot's API usage docs.

## Blocked signs and fix

| Sign | Fix |
|---|---|
| Connector tools missing | "Add the HubSpot connector in Claude settings, or save a private app token with set-secret hubspot_token, or export a CSV." (Claude Code only. In Cowork: "Connect a connector for hubspot, or export a CSV.") |
| `check` exit 2 with 401 | "The HubSpot token is invalid or revoked. Create a new private app token and run set-secret hubspot_token." (Claude Code only. In Cowork: "Connect a connector for hubspot, or export a CSV.") |
| 403 on one object | "Add the read scope for <object> to the private app." |
| `no key saved` | Give the set-secret command above (Claude Code only; in Cowork: "Connect a connector for hubspot, or export a CSV."). |

## Write / send capability

None. Read-only.
