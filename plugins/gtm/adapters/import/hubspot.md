# import: hubspot

## Purpose

Reads contacts, companies, deals and engagement history (notes, emails, calls, meetings) from HubSpot for `/gtm:import`. Read-only.

## Tool

A HubSpot MCP connector in the session. Find it with ToolSearch (`hubspot contacts companies deals`), read each tool's schema, and use only its list, get, search and property-read tools. Never call a tool that creates, updates, merges, deletes or associates records.

Without a connector: a CSV export of about 200 rows or fewer (`${CLAUDE_PLUGIN_ROOT}/adapters/import/csv.md`). A larger CRM without a connector needs Tessary GTM Pro, which reads HubSpot with a private app token (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, triggers 2 and 3). Never ask for a token in the chat.

## Preflight check

- Connector: one cheap read (list one contact). Auth error or missing tools = blocked.

## Read procedure

Write every response to `<run>/raw/` (the run folder from `${CLAUDE_PLUGIN_ROOT}/skills/import/references/apply.md`) with the Write tool, as the connector returned it. Paging: follow the connector's paging (HubSpot's `paging.next.after`) until there is no next page. The paths and parameters below name the HubSpot objects and properties to ask the connector for. If any page fails, the read is incomplete; stop before planning.

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


## Output

Not normalized events: `contacts.csv`, `deals.json`, `activities.json` in the run folder, then the plan (apply.md, Plan by hand).

## Cursor

None. Progress lives under `state.json` `adapters.import` and `done.jsonl` (apply.md, Progress and resume).

## Rate limits

Private apps get about 100 to 190 requests per 10 seconds depending on the plan, plus a daily cap. On a rate-limit error from the connector, wait 10 seconds and repeat that page once. Then stop, save progress, and tell the user to run `/gtm:import resume` later. Check the current limits in HubSpot's API usage docs.

## Blocked signs and fix

| Sign | Fix |
|---|---|
| Connector tools missing | "Add the HubSpot connector in Claude settings, or export a CSV of 200 rows or fewer." For a larger CRM, add the upgrade message (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`). |
| Connector auth error | "Reconnect the HubSpot connector in Claude settings." |
| A permission error on one object | "Give the connector read access to <object>." |

## Write / send capability

None. Read-only.
