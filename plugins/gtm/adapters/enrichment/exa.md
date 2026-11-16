# enrichment: exa

## Purpose

Finds companies and people that match the ICP, and reads company sites and recent news, through the Exa search connector. Used by `/gtm:campaign-build` (sourcing and buying signals) and `/gtm:campaign-write` (per-contact research). Exa does not return or verify email addresses.

## Tool

MCP connector only. `lib/readonly_api.py` has no Exa entry, because Exa search is a POST API.

Find the tools with ToolSearch, for example the query `exa web search fetch`. Typical tools (names carry a server prefix that differs per session; read each schema at run time):

| Tool | Use | Cost |
|---|---|---|
| web search (for example `web_search_exa`) | Search the web. A `category:company` or `category:people` hint in the query focuses on company pages or public LinkedIn profiles. | low, per call |
| web fetch (for example `web_fetch_exa`) | Read known URLs as text. Batch several URLs in one call. | low, per call |
| agent run (for example `agent_run`) | Multi-step list building or enrichment that returns a table. | metered; can cost several dollars per run |

Allowed: the tools above, read-only. Never pass the user's data to an agent run beyond company names, domains and public profile URLs.

## Preflight check

ToolSearch only. Make no search or fetch call: every real Exa call is billable.

1. Load the tools with ToolSearch (for example `exa web search fetch`). No search tool found = blocked.
2. Read the search and fetch tool schemas. Both present = ok.
3. An auth or quota error can therefore first show at the first real call. Then mark Exa blocked for the rest of the run and report it as below.

## Read procedure

### Sourcing (campaign-build)

1. Turn the ICP into two to four descriptive queries that describe the ideal page, not keywords: `category:company B2B SaaS companies selling to finance teams, 20 to 200 employees, based in the United States`. Put the facts to pull (size, location, product, funding) in the tool's objective field when it has one.
2. Ask for 10 to 25 results per query. Repeat with other phrasings or regions until enough companies pass the exclusions, or results start to repeat.
3. For people at a chosen company: `category:people <title> at <company name>`. Keep results whose current title and company both match. Take the LinkedIn URL from the result URL.
4. For buying signals: one search per company for recent funding, launches or hiring, limited to the last 12 months when the tool takes a date filter.
5. Use an agent run only when the user agrees to its cost. Set its budget to the remaining credit limit in dollars, and pass the companies already in the CRM as exclusions when the tool takes them.

### Research (campaign-write)

1. Fetch the company home page and one product, about or blog page.
2. One news search for the company or the founder in the last 12 months.
3. Keep only facts the fetched text states, with the URL.

## Output

Each company or person becomes a candidate record (`${CLAUDE_PLUGIN_ROOT}/skills/campaign-build/references/candidates.md`):

- `source`: `exa`. `external_id`: the result URL.
- `company.name`, `company.domain` (from the company URL), `company.description` (one sentence from the result text), `employees` and `headquarters` only when the text states them.
- `person.full_name`, `person.title`, `person.linkedin` from a people result. `person.email` is always null.
- `signals`: `{text, url, date}` for each fact from a news or site result.
- `credits_spent`: the number of calls (search and fetch), or the agent run's reported cost. Every real call counts toward the run's credit budget in `/gtm:campaign-build` and `/gtm:campaign-write`, including calls that return no useful result.

Drop results that are directories, list articles, job boards or the user's own domains, unless they lead to a company page you then read.

## Cursor

None. Enrichment runs are not incremental; dedupe against the CRM happens in campaign-build.

## Blocked signs and fix

- No Exa tools after ToolSearch: "Add the Exa connector in Claude settings, or remove `exa` from adapters.enrichment."
- Auth error or quota exceeded: "Check your Exa plan and reconnect the Exa connector in Claude settings."

## Write / send capability

None. Read-only.
