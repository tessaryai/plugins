# Notion access

Every gtm skill works with only the Notion MCP connector. When the user saved a Notion integration token in setup, bulk work goes through REST with `${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py`. This file says which path each operation uses.

## Choose the path

1. Read `notion.access` from config (`python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/config.py get notion.access`).
2. Check for a token: `python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/config.py has-secret notion_token` (exit 0 = saved). It prints only `set` or `not set`.
3. `mcp`, or no token: use MCP for everything. `rest` with a token: use REST for the operations marked "REST when token" below, and MCP for the rest.
4. If REST fails with an auth error (exit code 2 and status 401 or 403), fall back to MCP for this run and report it under Needs you ("the Notion token is invalid or the integration lost access; share the CRM pages with the integration or run set-secret again").

## Load the MCP tools

The Notion connector's tools are deferred in most sessions. Load them with ToolSearch before the first call, in one query, for example `notion-search notion-fetch notion-query-data-sources notion-create-pages notion-update-page`. Tool names carry a server prefix that differs per session (for example `mcp__<id>__notion-fetch`). Use the names ToolSearch returns.

Read each tool's schema at run time and pass exactly the parameters it defines. Never guess a command name, a parameter name or an enum value. If a tool you need is missing, the Notion adapter is blocked (see `${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`).

## Operations

| Operation | MCP path | REST path (`lib/notion_rest.py`) | Use REST when |
|---|---|---|---|
| Find a page or database by name | `notion-search` | none | never; use MCP |
| Read a data source schema (properties, select options) | `notion-fetch` on the database or data source | `schema <data_source_id>` | token present and the skill validates many writes |
| Query with a filter, all pages | `notion-query-data-sources` (check its schema for filter and paging parameters; follow every page or cursor it returns) | `query <data_source_id> --filter F [--simple]` | token present and the result can pass about 100 rows, or the MCP query hits a usage cap |
| Read one page's properties | `notion-fetch` | `get-page <page_id> --simple` | in a REST batch |
| Read page body blocks with exact text | `notion-fetch` (see the limit below) | `blocks <page_id> [--recursive]` | token present, always for copy that will be sent |
| Create a page in a data source | `notion-create-pages` with the data source as parent | `create <data_source_id> --in F` | imports over about 200 rows |
| Update properties | `notion-update-page` (check its schema for the update command) | `update <page_id> --in F` | in a REST batch |
| Append text to a page body | `notion-update-page`, command `insert_content`, position end (never `replace_content`) | `append <page_id> --in F` | token present, or more than a few lines |
| Create a database | `notion-create-database` | none | never; setup uses MCP |
| Add or change properties or select options | `notion-update-data-source` | none | never; only setup does this |

All REST commands are run as `python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py <command> ...`. Exit code 0 is done, 1 is bad input, 2 is a Notion error (the message holds only the status and a short body excerpt). Write input and output files in the session scratchpad, never in the plugin folder or the user's repo. One exception: `/gtm:import` keeps its work files in `~/.config/gtm/imports/<run_id>/`, so that `resume` works in a later session (`${CLAUDE_PLUGIN_ROOT}/reference/config.md`).

## Where MCP alone is limited

- Large CRMs. An MCP query can return a capped page of results or hit a per-integration usage cap. Follow every cursor the tool returns. If the tool gives no way to read past a cap, narrow the filter (for example by status, by campaign, by created date window) and query several times. If you still cannot read everything, report the check as incomplete, apply what you read, and suggest under Needs you that the user add a Notion token in `/gtm:setup` for bulk reads.
- Exact copy text. An MCP fetch returns the page as converted text. It can flatten line breaks or escape characters, so it is not a safe source for text that will be sent. With a token, always read copy with `notion_rest.py blocks` and use each block's `plain_text`. Without a token, read the page with `notion-fetch`, take the text inside the code block or quote under the step heading, and before any live send show that exact text in the run log. If line breaks or characters look altered (escaped quotes, `\n` sequences, missing blank lines), skip the step and list it under Needs you. Never repair copy by guessing.
- Relations. Some responses return at most 25 related items. Never read a campaign's contact list from the campaign side. Query Contacts with a relation filter instead (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Relations).

## Payload rules

The two paths take different property shapes. Read the tool schema each run; the shapes below were checked against the connector at the time of writing.

### MCP (`notion-create-pages`, `notion-update-page` with `update_properties`)

Properties are a flat map of property name to a plain value:

- Select: the option name as a string, `{"<Status property>": "Responded"}`.
- Date: split keys, `{"date:<property>:start": "YYYY-MM-DD", "date:<property>:is_datetime": 0}`.
- Checkbox: `"__YES__"` or `"__NO__"`.
- Relation: an array of page ids or URLs, the full list (read the current ids, add the new one, write all of them).
- Number: a JSON number. Text, email, URL, title: a string.
- A property named `id` or `url` (any case) is written as `userDefined:<name>`.
- Create in a database: `parent` = `{"type": "data_source_id", "data_source_id": "<id>"}`; fetch the data source first for its exact property names.
- Append to a page body: `notion-update-page` with command `insert_content`, `position` `{"type": "end"}`, and `content` as Notion-flavored Markdown (one paragraph per line, blank line between). Read the connector's Markdown spec resource before the first write if it says so.
- Query: `notion-query-data-sources`. `rows` mode takes a structured filter and returns at most 100 rows with no cursor; `sql` mode can page with `LIMIT` and `OFFSET` but may hit a plan usage cap; `view` mode pages with `start_cursor` over a saved view. Pick the mode the schema offers that can read every row, and check `has_more`.

### REST (`lib/notion_rest.py`)

- Select: `{"<property>": {"select": {"name": "<option>"}}}`. A `status` payload returns a 400 error on a select property.
- Date: `{"<property>": {"date": {"start": "YYYY-MM-DD"}}}`.
- Checkbox: `{"<property>": {"checkbox": true}}`.
- Relation: `{"<property>": {"relation": [{"id": "<page id>"}, ...]}}`, the full list.
- Rich text: `{"<property>": {"rich_text": [{"type": "text", "text": {"content": "..."}}]}}`, each piece under 2000 characters.
- Title: `{"<property>": {"title": [{"type": "text", "text": {"content": "..."}}]}}`.
- Create uses the parent `{"type": "data_source_id", "data_source_id": "<id>"}` and Notion-Version `2025-09-03` (set in the script). Append uses PATCH on `blocks/<page_id>/children`, at most 100 blocks per call (the script chunks).

### Status properties

Every choice field in the gtm schema is a select. If a mapped workspace uses a real Notion `status` property, setup records it in `notion.select_payload` (for example `{"contacts.status": "status"}`); REST then uses `{"status": {"name": ...}}` for that property only, and MCP filters use the status filter type. Check the live schema; do not assume.

## Select options

- Validate every select value against the live schema before a write. Read the schema once per run (`notion-fetch` or `notion_rest.py schema`). An unknown option either fails the write or creates a new option, depending on the path.
- Never create a new select option, except during `/gtm:setup` when the user agrees. If a needed option is missing, skip that write and list it under Needs you with the fix ("add option X to property Y, or map it in config").

## Hard stops

- A 400 error, or a tool warning, about deleting child pages or child databases is a hard stop. Do not retry with a changed payload. Do not pass a flag that allows deleting content. Report it under Needs you.
- Never use a whole-page replace (`replace_content` or any command that rewrites the full body) on a contact, company or campaign page. It can wipe log lines and campaign markers, and lost markers cause repeat sends. Append with `insert_content` at the end, or with REST `append`. Only the funnel page is replaced in full, by `/gtm:funnel`.
- Never use `update_content` search-and-replace on log lines or markers. They are append-only.
- Never move or re-parent a page by writing a URL into its content. Use the connector's move tool only when the user asks.
- Never delete a page, database or block. Skills only create, update properties and append.

## Tokens

The token lives only in `~/.config/gtm/credentials.json` (mode 600) or the environment variable `GTM_NOTION_TOKEN`. Only `lib/*.py` reads it. Never `cat` the credentials file, never print the token, headers or exception text, and never put the token in a command line. See `${CLAUDE_PLUGIN_ROOT}/reference/safety.md`.
