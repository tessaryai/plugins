# enrichment: apollo

## Purpose

Finds people and companies that match the ICP in Apollo's database, and returns their emails with Apollo's email status. Used by `/gtm:campaign-build`. This is the enrichment use of Apollo; the outreach mirror is `${CLAUDE_PLUGIN_ROOT}/adapters/outreach/apollo.md`.

## Tool

Preferred: an Apollo MCP connector in the session. Find it with ToolSearch, for example the query `apollo people search organization enrich`. Read each tool's schema at run time; never guess names or parameters.

Allowed connector tools: people search, organization (company) search, person or organization enrichment and email reveal, account or credit usage. Forbidden: anything that creates or changes data in Apollo (create contact, add to list or sequence, create task, update stage), and anything that sends.

Without the connector, Apollo cannot source or enrich: treat it as blocked for this run with the fix below. An API key does not help here, in either edition, because Apollo's people search, company search and enrichment endpoints need POST.

## Preflight check

- Connector: load the tools. Call the account, usage or credit tool if one exists; else run the cheapest search with one result. A result = ok. Missing tools or an auth error = blocked.
- No connector: report blocked, "no Apollo connector".

## Read procedure

1. Read the credit balance first when a tool gives it. Searches in Apollo are usually free; email reveal and enrichment spend credits. Check the tool description for which calls spend.
2. Company search: map the ICP to the connector's filters (employee range, locations, industry keywords, technologies, funding). Page only as far as the target needs.
3. People search: filter by the chosen company domains or ids and by the ICP buyer titles (and seniority when the tool offers it). One or two people per company.
4. Email reveal or enrichment: only for people that passed scoring and dedupe in campaign-build, and only within the credit limit. Ask before passing it.
5. Read every result page the tool returns for the people you need, or report the read as incomplete.

## Output

Each person becomes a candidate record (`${CLAUDE_PLUGIN_ROOT}/skills/campaign-build/references/candidates.md`):

- `source`: `apollo`. `external_id`: the Apollo person id.
- `person`: first and last name from Apollo's own fields, title, LinkedIn URL (canonicalized), city and country, email.
- `company`: name, primary domain, website, LinkedIn URL, employee count, headquarters, short description, industry.
- `email_check`, from Apollo's email status. The names below are from memory, not checked against a live connector; map the values the connector actually returns by meaning, and record the first mapping as a decision:

| Apollo email status | `email_check.result` |
|---|---|
| `verified` | `valid` (confidence high) |
| `likely to engage` or similar | `valid` (confidence low) |
| `guessed`, `extrapolated`, `unverified` | `null` (not verified; verify with another adapter when one is set) |
| `unavailable`, no email | no email |

- `signals`: funding date or hiring data only when the result includes it with a date.
- `credits_spent`: credits the tool reports, or one per reveal.

## Cursor

None.

## Blocked signs and fix

- No Apollo connector: "Add the Apollo connector in Claude settings."
- Auth error: "Reconnect the Apollo connector in Claude settings."
- Out of credits: report it, stop paid calls, and keep what was found.

## Write / send capability

None. Read-only. Never create, change or enroll anything in Apollo.
