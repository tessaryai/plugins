# Status and stage mapping

Detail for `/gtm:import` step 4. The user confirms every mapping. These are proposals only.

## How to build the table

1. Count the distinct values of the mapped status column (`status_source` in the plan, or the raw column before the plan).
2. For each value, propose a logical status. Use the tables below; they are the source of truth. A value the tables mark `ask`, or do not list, gets a warning and a suggested `New`: ask the user. A plain `Lead` maps to `New` (in most CRMs "lead" is an early stage, not a deal).
3. Show: source value, rows, proposed logical status. Ask for corrections. Save `{"<source value>": "<logical status>"}` to `<run>/status_table.json`.
4. A blank value maps to `New`.

The logical statuses are `New`, `Contacted`, `Responded`, `Discovery`, `Lead`, `Archived`, `Do Not Contact`, `Disqualified` (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`). `Lead` means a deal exists. Propose `Archived` or `Disqualified` only when the source value says so plainly; these and `Do Not Contact` are counted separately in the preview.

## Common source values

### HubSpot lifecycle stage and lead status

| Source value | Proposed |
|---|---|
| subscriber, lead, New or Open (lead status) | New |
| Attempted to contact, In progress (lead status) | Contacted |
| Connected (lead status) | Responded (confirm) |
| Open deal (lead status) | Lead |
| marketingqualifiedlead (MQL) | New, or Responded when the user says MQL means a reply |
| salesqualifiedlead (SQL) | Discovery |
| opportunity | Lead |
| customer, evangelist | Lead (and say so: gtm has no Customer status; the funnel reads customers from Pipeline stages) |
| Unqualified (lead status), Bad timing | Disqualified (confirm) |
| other | ask |

Also map HubSpot's internal values the same way: `subscriber`, `lead`, `marketingqualifiedlead`, `salesqualifiedlead`, `opportunity`, `customer`, `evangelist`, `other` (lifecycle stage) and `NEW`, `OPEN`, `IN_PROGRESS`, `OPEN_DEAL`, `UNQUALIFIED`, `ATTEMPTED_TO_CONTACT`, `CONNECTED`, `BAD_TIMING` (lead status).

When both lifecycle stage and lead status exist, map the one that tells more about outreach (usually lead status) and keep the other in Notes as an extra column.

### Pipedrive

Pipedrive persons have no standard status. Use, in order: a custom person field the user names; the person's label; else derive from deals and activities:

| Signal | Proposed |
|---|---|
| no activities, no deals | New |
| a done email or call activity | Contacted |
| an open deal | Lead |
| only lost deals | keep the derived status; put `Deal lost: <reason>` in Notes |
| `marketing_status` = unsubscribed | Do Not Contact |

Common Pipedrive values used as a status (labels, default deal stages, `marketing_status`):

| Value | Proposed |
|---|---|
| Lead In, Cold lead, subscribed | New |
| Contact Made | Contacted |
| Demo Scheduled, Needs Defined | Discovery |
| Proposal Made, Negotiations Started, Customer, won | Lead |
| Hot lead, Warm lead, lost, no_consent | ask |

### Attio

Map the values of the status or stage attribute the user names on the People object or the list they import from. Propose by meaning with the generic table below. Common Attio list stages: `Lead` → New, `In Progress` → Contacted, `Won` → Lead, `Lost` → ask.

### Salesforce (CSV export)

| Lead Status | Proposed |
|---|---|
| Open - Not Contacted | New |
| Working - Contacted | Contacted |
| Closed - Converted | Lead |
| Closed - Not Converted | Disqualified (confirm) |

`HasOptedOutOfEmail` or `Email Opt Out` = true → Do Not Contact.

### Generic words

| Words in the value | Proposed |
|---|---|
| new, open, prospect, to contact | New |
| contacted, emailed, sequenced, attempted, in progress | Contacted |
| replied, responded, engaged, interested, in conversation | Responded |
| meeting, demo, call booked, qualified, discovery | Discovery |
| opportunity, proposal, negotiation, customer, won | Lead |
| not a fit, unqualified, junk, bad fit | Disqualified |
| archived, inactive, dead | Archived |
| unsubscribed, opted out, do not contact, bounced | Do Not Contact (a bounce: ask; it may be better as `email_status` Not Found) |

## Deal stages

Map each source pipeline stage to a logical stage of `option_map.pipeline.stage`: `First Call`, `Interested`, `Discovery`, `Proposal`, `Pilot`, `Won`, `Lost`, `On Hold`. Proposals by meaning: appointment scheduled → First Call; qualified to buy → Discovery; presentation, proposal, contract sent, negotiation → Proposal; trial, pilot, POC → Pilot; closed won → Won; closed lost → Lost; anything paused → On Hold. Several pipelines: show each pipeline's stages separately, since stage names can repeat with different meaning.
