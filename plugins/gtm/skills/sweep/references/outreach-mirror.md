# Sweep: mirror outreach tools into the CRM

Outreach tools (gojiberry, lemlist, instantly, apollo) send on the user's behalf. The sweep copies what they did into the CRM, so the CRM shows every contacted person. It runs first, so the later checks can match the new pages.

The tools are read only (`${CLAUDE_PLUGIN_ROOT}/reference/safety.md`, Read-only adapters). The sweep never creates, changes or deletes anything in them. If a fix can only be made in the tool (remove a suppressed contact from a tool campaign), put it under Needs you.

## Mirror data from the adapter

Besides events, each outreach adapter returns:

| Key | Holds |
|---|---|
| `campaigns` | `id`, `name`, `active`, `channels` (`linkedin`, `email` or both) |
| `labels` | contact keys, date, external id, label (for example `interested`) |
| `flagged` | tool contact id, contact keys, `bounced`, `unsubscribed` |
| `emails_found` | tool contact id, contact keys, email (an email the tool found for a contact) |
| `complete`, `incomplete` | whether every campaign was read; the campaigns that failed |

Each event carries `detail.tool_contact_id`, `detail.campaign_id`, `detail.campaign_name` and `detail.person` (name, title, company name, domain, company LinkedIn URL, company location, location, signal text).

## Only a touch creates pages

A `touch` event creates the contact, its company and its campaign when they are missing. No other event creates a page: not an accept, not a reply, not a label, and never a lead the tool found but did not contact. An accept or reply for a person with no page is unmatched.

Create these pages at once, in this order, not in the final batch, so the email and LinkedIn checks of the same run can match them. Re-read each new page to verify it. Use existing select options only; resolve them through `notion.option_map`.

### 1. Campaign

Find a Campaigns page whose `notes` contain `<Tool> campaign id: <id>` (for example `Gojiberry campaign id: 42`). If none, create:

| Field | Value |
|---|---|
| `name` | `<Tool> - <campaign name>`, trimmed |
| `type` | `LinkedIn`, `Email`, or `Mixed` when both channels |
| `status` | `Active` when the tool says active, else `Paused` |
| `start_date` | the first touch date in this run |
| `notes` | `<Tool> campaign id: <id>` |
| body | two lines: `Runs: external` and `Mirrored from <Tool> by /gtm:sweep. Do not run with /gtm:campaign-run.` |

`Runs: external` tells `/gtm:campaign-run` never to run this campaign (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`). On later runs, update only `status` when the tool's active state changed. If an existing mirrored page lacks the `Runs: external` line, append it.

### 2. Company

Match in this order: the company LinkedIn URL, then the website domain, then the normalized name (lower case, without legal suffixes such as Inc, Ltd, LLC, GmbH). A name-only match is a decision. If none, create: `name`, `website`, `linkedin`, `headquarters` (company location). Leave `icp`, `icp_notes`, `vertical`, `employees` and `description` empty.

If the matched company's `icp` is `Not a fit`, list it under Needs you (the tool is contacting a company the user ruled out).

### 3. Contact

Match in this order: `<Tool> contact id: <id>` in `notes`; then LinkedIn (compare the tool's profile URL and any public identifier, canonicalized as in `crm-rules.md`, Matching); then email. If none, create:

| Field | Value |
|---|---|
| `name` | the person's name |
| `linkedin` | canonical `https://www.linkedin.com/in/<slug>/` |
| `email` | if the tool has one |
| `location` | if given |
| `lead_source` | `Cold Outreach` |
| `status` | `Contacted` |
| `first_contacted` | the date of the contact's earliest touch event |
| `company` | the company page from step 2 |
| `campaign` | the campaign page from step 1 |
| `designation` | from the title, table below |
| `notes` | `<Tool> contact id: <id>. <title>. Signal: <signal text, HTML tags removed>` |
| body | the touch log line(s) |

For a contact that already exists:

- Add the campaign to its `campaign` relation: read the current list, append, write the full list. Never write the relation from the campaign side: a campaign's relation can read back at most 25 items, so a write from that side can drop contacts.
- Append the id line to `notes`, keeping the old text.
- Do not change `lead_source`, `company` or `designation`. Change `email` only to fill an empty one.
- The touch itself goes into the batch as a planned change (`events.md`).
- A suppressed contact: no Status change, log the touch, list it under Needs you ("<Tool> is still contacting a Do Not Contact contact; remove them in <Tool>").

### Designation from the title

First match wins, case-insensitive. Set only options that exist in the live schema. Never add an option; if the mapped option is missing, leave `designation` empty.

| Title contains | Designation |
|---|---|
| `founder #` followed by a number (an early employee) | none |
| founder, co-founder | `Founder` |
| CEO, chief executive | `CEO` |
| CTO, CPO, COO, CFO, CIO, CMO, CRO, or chief followed by officer | `CXO` |
| VP, vice president, head of | `VP` |
| director, manager, lead | `Manager` |
| engineer, developer, designer, analyst, scientist, specialist, associate, consultant | `Individual Contributor` |
| anything else | none |

## Fill missing emails

Some tools find an email for a LinkedIn-only contact during a sequence. Never ask a tool to find or reveal an email: that spends credits and the read-only client refuses it.

After the pages are created, on every run:

1. For each entry in `emails_found`, find the CRM contact (by `<Tool> contact id:` in `notes`, then by LinkedIn).
2. If the contact's `email` is empty, write the found email. Leave `email_status` empty (the tool does not say the address is verified). Log `Email added from <Tool>`.
3. Never overwrite a non-empty `email`. If it differs, keep the CRM value and record both under Decisions.

Write these at once, not in the batch, so the email check can match replies from the new addresses in the same run.

## Flagged contacts

For each `flagged` entry that matches a CRM contact:

- `unsubscribed`: plan the negative change (`events.md`) with `dnc_reason` `Unsubscribed in <Tool>`.
- `bounced`: plan `email_status` → `Not Found` and log `Email bounced`.

## Overlap with the other checks

Outreach tools send through the user's own LinkedIn and mailbox, so the email and LinkedIn checks see the same activity.

- A `<Tool> email sent` line for a date stops the email check from adding `Outbound message sent` for that date.
- Accepts and replies share event names across checks, so dedupe by date and event writes them once.
- Never read a tool's whole inbox as a list. It can hold all of the user's threads, not only campaign threads.

## Report

Per tool: campaigns read, new events by kind, campaigns, companies and contacts created, emails added, unknown actions, and `incomplete` campaigns. An incomplete tool keeps the old cursor for the failed campaigns only.
