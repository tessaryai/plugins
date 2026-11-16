# CRM writes for campaign-build

All property and option names below are logical. Resolve them through the config map (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Names go through the config map). Payload shapes for MCP and REST are in `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`.

## Campaign page

### Pick an existing campaign

1. Find it by name with `notion-search`, or query the Campaigns data source for its name.
2. Read its properties and body. Note `status`, `type` and the `Campaign key:` line.
3. By Status:
   - `Review` or `Paused`: go on.
   - `Active`: ask "This campaign is Active. Contacts added now get step 1 on the next campaign run. Add them anyway?" Go on only on a clear yes. Never change the Status.
   - `Completed`: stop and suggest a new campaign.
4. No `Campaign key:` line: propose a key (rules below) and, on a yes, append the line with `insert_content` at the end. If the page already has step headings, an appended key line lands after them; tell the user to move it above the first step by hand, and list it under Needs you.
5. A page with `Runs: external` belongs to another tool. Ask before adding contacts to it, and say campaign-run will not send for it.

### Create a new campaign

1. Ask for the campaign name and type (`LinkedIn`, `Email` or `Mixed`; default `Mixed`). `Warm Intro` campaigns are sent by hand; allow it only if the user asks.
2. Propose a campaign key: lower case letters, digits and hyphens, at most 24 characters, built from the name (for example `q1-fintech-founders`).
3. Check the key is unique. Query the Campaigns data source (it is small) and read the `Campaign key:` line of each page body. With more than 50 campaigns, search for the exact string `Campaign key: <slug>` with `notion-search` instead. If the key is taken, add a short suffix and check again.
4. Create the page in the Campaigns data source with `notion-create-pages`:
   - `name`: the campaign name.
   - `status`: `Review`.
   - `type`: the chosen type.
   - Body, one paragraph per line, with a blank line between lines (the connector joins lines without a blank line into one paragraph):
     ```
     Campaign key: <slug>

     Audience: <the confirmed ICP summary, one sentence>
     ```
5. Write nothing else on the page. `/gtm:campaign-write` appends the other header lines and the steps.
6. Read the page again. Check the title, Status `Review`, Type and the key line.

## Dedupe

### Read the CRM keys

- With a Notion token (`notion.access` = `rest` and `has-secret notion_token`): read every contact once with `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py query <contacts id> --simple --out <scratchpad>/contacts.json` and match in memory. Do the same for Companies.
- Without a token: read Contacts and Companies once each in view mode with `notion.views.<db>` (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows) and match in memory. Rows or SQL mode is only a fallback for a few targeted lookups, counted against the workspace quota; on the allowance error, stop using it for this run.
- Compare LinkedIn URLs in canonical form and emails case-insensitively (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Matching). Never match by name alone.

### Buckets

Put each candidate in exactly one bucket. Check in this order; the first rule that fits wins.

| Rule | Bucket | Reason text |
|---|---|---|
| Email in `owner.emails`, or domain in `owner.own_domains` | skip | `owner address` (see Owner address below) |
| Same person appears twice in this run | skip the copy | `duplicate in list` |
| Matches a contact that is suppressed (Do Not Contact ticked, or Status `Do Not Contact`, `Disqualified` or `Archived`) | skip | `suppressed` |
| Matches a contact already linked to this campaign | skip | `already in this campaign` |
| Matches a contact linked to another campaign whose Status is `Active` or `Review` | skip | `in campaign <name>` |
| Company exists in the CRM with ICP `Not a fit` | skip | `company marked Not a fit` |
| Company exists in the CRM and has a linked deal (any Pipeline page) | skip | `open deal or customer` |
| Matches a contact whose Status is past `New` | ask | `already contacted (Status <s>)` |
| Matches a contact at Status `New` | link existing | |
| No match | new | |

To read another campaign's Status, fetch each campaign page that appears in matched contacts' `campaign` relation once and cache it. Read the relation from the contact side only.

A near match (LinkedIn slug differs only by a suffix) counts as a match only when name and company agree; record it under Decisions.

### Owner address

The owner's own contact (an address in `owner.emails`) is skipped by default. Only when the user explicitly asks in this run to link their own address for a test send:

1. Link their existing contact, or create it at Status `New` if it does not exist (the usual contact writes below).
2. Append the control line `Owner test: <campaign_key>` to that contact page as its own paragraph, with the key of this campaign (dedupe first: skip it when the page already has that exact line). It must start the line and stand outside any code block (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`, Control lines must stand alone). One line per campaign; a second test campaign gets a second line.
3. Record it under Decisions: `owner asked to add own address <email> — linked for a test send, wrote Owner test: <campaign_key>`.

campaign-run sends to an owner address only when the contact page holds `Owner test: <key>` for the campaign it runs (`${CLAUDE_PLUGIN_ROOT}/skills/campaign-run/references/plan.md`, Owner test contact). Never write this line without the user's explicit request in this run. This never applies to other people at a domain in `owner.own_domains`; they stay skipped.

## The preview

Show this before any write. Keep it in the chat; do not write it to Notion.

```
Campaign: <name> (<key>), Status <status>
Target: <size>. Ready to add: <n new> new contacts, <n link> existing contacts to link.
Companies: <n> new, <n> already in CRM.
Email: <n> Verified, <n> Low Confidence, <n> Needs Review, <n> not verified, <n> none.
Credits spent: <adapter n of limit> ...

Sample (10 of <n>):
| Name | Title | Company | Fit | Email status | LinkedIn | Source |

Dropped:
- Not a fit: <n> (<company — reason>, first five)
- suppressed: <n>
- in another campaign: <n>
- ...

Questions:
1. <n> people are already in the CRM past New (list). Add them to this campaign? Default: no. campaign-run holds them (runs no step) until you add a `Campaign hold cleared` line to each page.
2. <n> existing contacts at New will be linked to this campaign (list names). OK? Any of them with an earlier sent line or another campaign's marker on the page is also held by campaign-run until cleared: <names>.
3. Emails without verification still send in campaign-run. Keep them, or drop them?
Write these to Notion?
```

Offer the full list as a table on request. Apply only the parts the user approved.

## Write

Order: companies, then contacts, then links. On the MCP path, create up to 20 pages per `notion-create-pages` call (check the tool schema for a lower limit) and verify each batch before the next one. With a token and more than about 200 rows, use REST `create`, one page at a time.

### Companies

For each approved candidate whose company is not in the CRM, create one Companies page:

- `name`, `website` (`https://<domain>`), `linkedin`, `description`, `employees` (number), `headquarters`.
- `icp`: the score, `icp_notes`: the reason line.
- `vertical`: only when the industry maps clearly to an existing option; otherwise leave it empty.

Body line (one paragraph):

```
YYYY-MM-DD — Added by campaign-build for campaign <campaign_key> (source: <adapter>). Action: campaign-build.
```

### New contacts

Create one Contacts page per approved `new` candidate:

| Logical field | Value |
|---|---|
| `name` | `person.full_name` as the provider gave it |
| `email` | the email, only when the mapping in `candidates.md` writes it |
| `email_status` | the mapped option, or empty |
| `linkedin` | canonical URL |
| `location` | `person.location` |
| `status` | `New` |
| `lead_source` | `Cold Outreach` |
| `designation` | only when the title maps plainly to an option (`Founder`, `CEO`, `CXO`, `VP`, `Manager`, `Individual Contributor`) |
| `company` | `[<company page id>]` |
| `campaign` | `[<campaign page id>]` |

Never set `first_contacted`, `do_not_contact`, `dnc_reason` or `dnc_set_on`.

Body lines (one paragraph each, in this order, with a blank line between lines):

```
YYYY-MM-DD — Added to campaign <campaign_key> by campaign-build (source: <adapter>). Status → New. Action: campaign-build.

Source fields: first_name=<first>; company=<company name>; title=<title>

Signal: <text> (<url>, <date>)
```

- `Source fields:` holds the provider's own values so campaign-write can build the `Run fields:` line without parsing the Name property. Leave out a key whose value is null or contains `;`. This line is not `Run fields:`; campaign-run ignores it.
- One `Signal:` line per signal, at most three.
- Signal text and `Source fields:` values come from providers and the web. Neutralize them before writing (`[GTM:` becomes `(GTM:`; `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Outside text in log lines).

On the MCP path, put the lines in the create call's content. On REST, pass them as `children_lines` in the `create --in` file.

### Existing contacts (link existing, and approved ask)

1. Read the contact fresh. Re-check the DNC rule. A contact that became suppressed is skipped.
2. Read its current `campaign` relation ids, add the campaign id, and write the full list.
3. Fill `email` and `email_status` only when they are empty. Never overwrite them.
4. Append `YYYY-MM-DD — Added to campaign <campaign_key> by campaign-build. Action: campaign-build.` (dedupe by date and event first), and the `Source fields:` line only when the page has none.
5. Do not change Status, Lead Source or First Contacted.

### Verify

After each batch (each write on REST), read every page in it again (REST `get-page --simple`, else `notion-fetch`). Check: Status, Lead Source, Email, Email Status, company relation, campaign relation holds the campaign page id (compare ids, not URLs), and the log line is present. In the fetch view, un-escape backslash-escaped `_ { } * [ ]` and strip mailto link syntax before you compare (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`, Reading the page). A failed write is retried once. A second failure goes under Needs you with the contact name.

At the end, query Contacts with a filter on the `campaign` relation containing the campaign page. With `notion-query-data-sources`, the filter value must be the page URL, `https://www.notion.so/<page id without dashes>`: a bare page id is silently ignored and the query returns every row. Drop and report any returned row whose `campaign` relation does not include this campaign's page id (compare page ids, never full URLs: `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Relations). On the view-mode path (no filter), filter in memory by page id and report only the counts. Compare the count with the expected count (existing members plus this run's adds). Report a difference under Needs you.
