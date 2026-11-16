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

When a log row names a contact id that is missing from the tool's contact list (for example the contact was removed from a list later), use the contact object embedded in the log row for `person` and the keys. Only when neither exists is the event unmatched; list it with the log id.

## How far back

- With a cursor: read back to the cursor, as the adapter says.
- First run (no cursor for a campaign): read back only `sweep.first_run_lookback_days` days. Older outreach is not mirrored.
- Full history: only when the user asks for it in this run. A full-history mirror can create hundreds of pages, so first read the logs, show the counts (campaigns, contacts and companies that would be created), and ask before you create anything. A scheduled or unattended run never mirrors full history.

## Only a touch creates pages

A `touch` event creates the contact, its company and its campaign when they are missing. No other event creates a page: not an accept, not a reply, not a label, and never a lead the tool found but did not contact. An accept or reply for a person with no page is unmatched.

Create these pages at once, in this order, not in the final batch, so the email and LinkedIn checks of the same run can match them. Pass `allow_async` = false on every `notion-create-pages` call for a campaign, company or contact: the next step needs the new page ids for its relations. At most 20 pages per call; verify each batch. Re-read each new page to verify it. Use existing select options only; resolve them through `notion.option_map`.

### 1. Campaign

Find, in the Campaigns index (`batch.md`, CRM index), a page whose `notes` contain `<Tool> campaign id: <id>` (for example `Gojiberry campaign id: 42`). If none, create:

| Field | Value |
|---|---|
| `name` | `<Tool> - <campaign name>`, trimmed |
| `type` | `LinkedIn`, `Email`, or `Mixed` when both channels |
| `status` | `Active` when the tool says active, else `Paused` |
| `start_date` | the first touch date in this run |
| `notes` | `<Tool> campaign id: <id>` |
| body | two lines: `Runs: external` and `Mirrored from <Tool> by /gtm-pro:sweep. Do not run with /gtm-pro:campaign-run.` |

`Runs: external` tells `/gtm-pro:campaign-run` never to run this campaign (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`). On later runs, update only `status` when the tool's active state changed. If an existing mirrored page lacks the `Runs: external` line, append it.

### 2. Company

Canonical company LinkedIn URL: `https://www.linkedin.com/company/<slug>`, in lower case, with no query string and no trailing slash. Canonicalize both sides before you compare, and store this form.

Match against the Companies index (`batch.md`, CRM index), in this order: the canonical company LinkedIn URL, then the website domain, then the normalized name (lower case, without legal suffixes such as Inc, Ltd, LLC, GmbH). A name-only match is a decision. If none, create: `name`, `website`, `linkedin` (canonical), `headquarters` (company location). Leave `icp`, `icp_notes`, `vertical`, `employees` and `description` empty.

Website check: leave `website` empty when the tool's website is a personal page (a profile, a link page, a personal blog or a free-mail domain) or plainly belongs to a different company than the company name and the contact's email domain suggest. Record it as a Decision with the value you left out.

If the matched company's `icp` is `Not a fit`, list it under Needs you (the tool is contacting a company the user ruled out).

### 3. Contact

Match in this order: `<Tool> contact id: <id>` in `notes`; then LinkedIn (compare the tool's profile URL and any public identifier, canonicalized as in `crm-rules.md`, Matching); then email. When the tool's profile URL and its identifier give different slugs, the profile URL wins: use it for matching and storage, and record the other as a Decision. If none, create:

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
| body | every initial log line for this contact from this run (touches, accept, and any other events), in date order, oldest first |

Create-body log lines: the contact is created at Contacted, so its first touch line carries the Status change, for example `2026-03-02 — Gojiberry invitation sent. Status → Contacted. Action: sweep gojiberry check (log 1234).` Later lines (a second touch, `LinkedIn connection accepted`) follow in date order without a Status part. Separate the lines with a blank line in the Markdown content, or they merge into one paragraph (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Payload rules). These events still go into the batch, but only as dedupe keys, so apply writes no second copy.

For a contact that already exists:

- Add the campaign to its `campaign` relation: read the current list, append, write the full list. Never write the relation from the campaign side: a campaign's relation can read back at most 25 items, so a write from that side can drop contacts.
- Append the id line to `notes`, keeping the old text.
- Do not change `lead_source`, `company` or `designation`. Change `email` only to fill an empty one.
- The touch itself goes into the batch as a planned change (`events.md`).
- A suppressed contact: no Status change, log the touch, list it under Needs you ("<Tool> is still contacting a Do Not Contact contact; remove them in <Tool>").

### Designation from the title

First match wins, case-insensitive. Match whole words only (word boundaries): `Director` must not match `CTO`, `coordinator` must not match `COO`, `Leadership` is not `lead`. Treat a title of the form `Chief <words> Officer` (any words between, for example `Chief Revenue Officer`, `Chief Customer Success Officer`) as CXO. Compound forms: `cofounder` and `co-founder` are Founder; `SVP`, `EVP` and `AVP` are VP; `Founding Engineer` is not Founder. Set only options that exist in the live schema. Never add an option; if the mapped option is missing, leave `designation` empty.

| Title contains | Designation |
|---|---|
| `founder #` followed by a number (an early employee) | none |
| founder, co-founder, cofounder (not `founding`) | `Founder` |
| CEO, chief executive | `CEO` |
| CTO, CPO, COO, CFO, CIO, CMO, CRO, CISO, or `Chief ... Officer` | `CXO` |
| VP, SVP, EVP, AVP, vice president, head of | `VP` |
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
- A `<Tool> LinkedIn message sent` line for a date stops the LinkedIn messages check from adding `Outbound message sent` for that date.
- Accepts and replies share event names across checks, so dedupe by date and event writes them once.
- Never read a tool's whole inbox as a list. It can hold all of the user's threads, not only campaign threads.

## Report

Per tool: campaigns read, new events by kind, campaigns, companies and contacts created, emails added, unknown actions, and `incomplete` campaigns. An incomplete tool keeps the old cursor for the failed campaigns only.
