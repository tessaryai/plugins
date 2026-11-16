# enrichment: mcp

## Purpose

Uses any enrichment MCP connector the session has (a lead database, a people or company search service, an email finder or verifier) to source and enrich candidates. Used by `/gtm:campaign-build`. The provider is not fixed: the tools are found at run time.

## Tool

MCP connector only.

1. Search with ToolSearch for enrichment tools, with several queries: `find people`, `company search`, `email finder`, `email verification`, `enrich`, `prospect`. Exclude the Notion, email, calendar and Slack tools, and every server from the Exa or Apollo vendors whatever its prefix (for example both an "Exa" and an "Exa Agent" server). Exa and Apollo have their own adapters. Judge the vendor by the server name and its tool descriptions, not by one prefix.
2. Group the results by server prefix. If more than one server qualifies, list them and ask the user which to use. If exactly one qualifies, name it and use it.
3. Read each tool's schema and description. Sort the tools into:
   - free reads: account, subscription, credits, counts;
   - paid reads: people search, company search, profile or company scrape, email search, email verification, reverse lookups;
   - forbidden: anything that creates, updates, exports to or deletes in the provider (lists, sequences, CRM pushes, webhooks), and anything that sends.
   When the description does not say whether a call spends credits, treat it as paid.
4. Use only free and paid reads. Prefer single-item tools over bulk tools until the user approves the bulk cost.

## Preflight check

Tools found and one free read succeeds (the account, subscription or credit tool when present; else a count tool). A result = ok, and note the remaining credits. No tools found, or an auth error = blocked.

## Read procedure

1. Show the remaining credits from the free read.
2. Use a count tool before each search when the provider has one, and show the count. Ask before a search whose cost passes the run's credit limit.
3. Company search: map the ICP to the tool's filters (industry or keywords, size range, location, technology). Use include and exclude lists when the tool takes them, and exclude the user's own domains.
4. People search: filter by current company (domain or id from step 3) and current job title (expand acronyms and add synonyms). Limit results to what the target needs (`maxResults` or the tool's limit parameter).
5. Email search: only for people campaign-build will add, within the limit.
6. Email verification: for every email the search tool did not verify.
7. Read every page the tool returns for what you need, or report the read as incomplete.

## Output

Map each result into the candidate record (`${CLAUDE_PLUGIN_ROOT}/skills/campaign-build/references/candidates.md`):

- `source`: `mcp:<server name as the user would know it>`. `external_id`: the provider's id or profile URL.
- Person and company fields from the tool's own fields. Never derive a first name from a full name when the tool gives a first-name field.
- `email_check`: map the provider's verification result by meaning. Deliverable or confirmed with high certainty = `valid` (high); deliverable with lower certainty = `valid` (low); catch-all = `accept_all`; could not check = `unknown`; undeliverable, invalid, disposable = `invalid`; not checked = `null`. Record the provider's own value in the run log the first time you map it, as a decision.
- `credits_spent`: as the tool reports, else count calls.

## Cursor

None.

## Blocked signs and fix

- No enrichment tools found: "Add an enrichment connector in Claude settings, or remove `mcp` from adapters.enrichment."
- Auth error, unpaid plan or zero credits: "Check the provider account and reconnect its connector in Claude settings."

## Write / send capability

None. Read-only. Never call a tool that writes to the provider, even when it looks harmless.
