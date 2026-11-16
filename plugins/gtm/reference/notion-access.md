# Notion access

Every gtm skill works with only the Notion MCP connector. When the user saved a Notion integration token in setup, bulk work goes through REST with `${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py`. This file says which path each operation uses.

## Choose the path

1. Read `notion.access` from config (`python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py get notion.access`).
2. Check for a token: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py has-secret notion_token` (exit 0 = saved). It prints only `set` or `not set`.
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
| Read every row of a database (index, export) | `notion-query-data-sources` in view mode with `notion.views.<db>` (Query rows, below) | `query <data_source_id> [--filter F] [--simple]` | token present; always for a CRM with active campaigns or more than about 200 contacts |
| Small targeted lookup with a filter | `notion-query-data-sources` in rows or SQL mode, counted against the quota (Query rows) | `query <data_source_id> --filter F [--simple]` | token present |
| Read one page's properties | `notion-fetch` | `get-page <page_id> --simple` | in a REST batch |
| Read page body blocks with exact text | `notion-fetch` (see Exact copy text below) | `blocks <page_id> [--recursive]` | token present, always for copy that will be sent or compared |
| Read a page's created time | SQL mode, `createdTime` column (counted, Query rows) | `get-page <page_id>` (`created_time`) | token present |
| Create a page in a data source | `notion-create-pages` with the data source as parent, up to 20 pages per call (Payload rules) | `create <data_source_id> --in F` | imports over about 200 rows |
| Update properties | `notion-update-page` (check its schema for the update command) | `update <page_id> --in F` | in a REST batch |
| Append text to a page body | `notion-update-page`, command `insert_content`, position end (never `replace_content`) | `append <page_id> --in F` | token present, or more than a few lines |
| Create a database | `notion-create-database` | none | never; setup uses MCP |
| Add or change properties or select options | `notion-update-data-source` | none | never; only setup does this |

All REST commands are run as `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py <command> ...`. Exit code 0 is done, 1 is bad input, 2 is a Notion error (the message holds only the status and a short body excerpt). Write input and output files in the session scratchpad, never in the plugin folder or the user's repo. One exception: `/gtm:import` keeps its work files in `<imports>/<run_id>/` (the `imports` path printed by `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py paths`), so that `resume` works in a later session (`${CLAUDE_PLUGIN_ROOT}/reference/config.md`).

## Query rows

The Notion MCP query tool `notion-query-data-sources` has three modes. They do not cost the same.

| Mode | What it does | Quota |
|---|---|---|
| `view` | Runs a saved view (its own filters and sorts) by `view_url`. Takes no filter of its own. Pages with `start_cursor` = `next_cursor` while `has_more` is true, up to 100 rows per page. | No plan quota. |
| `rows` | One data source, a structured filter and sort, at most 100 rows, no cursor. | Shares a small workspace-level allowance with SQL. |
| `sql` | Read-only SQLite on one data source. Can page with `LIMIT` and `OFFSET`. The only MCP mode that returns `createdTime`. | Shares the same allowance. A query over several data sources needs a Business plan and fails with `entitlement_required`; always query one data source. |

The rows and SQL allowance is a workspace quota, not a per-run one. In testing it ran out after one rows-mode call, with the message "Your workspace has used up its Query Data Source allowance for SQL and rows-mode queries." It resets within about 60 minutes. View mode kept working.

Rules for every skill:

1. Default index path: view mode with the saved view URL in `notion.views.<db>` (contacts, companies, pipeline, campaigns, meetings). A view URL has one of two forms, and both are accepted: `view://<view id>` (the form `notion-fetch` on a database returns, which the query tool accepts as `view_url`) or `https://www.notion.so/<database id>?v=<view id>`. Pass the stored value as `view_url` as it is. Setup records one view URL per database, in the `view://` form, by fetching the database (not the data source); the fetch result lists its views as `view://` URLs (`${CLAUDE_PLUGIN_ROOT}/skills/setup/references/databases.md`). Follow every `next_cursor` until `has_more` is false. Filter the rows in memory (Status, relation, dates). A view that has its own filter can hide rows: setup records a view with no filter, and a reader that sees fewer rows than expected reports it.
2. If `notion.views.<db>` is empty, `notion-fetch` the database once, take a `view://` view from the result, use that `view://` URL as `view_url` for this run (the `https://www.notion.so/<database id without dashes>?v=<view id without dashes>` form also works), and suggest under Needs you that the user run `/gtm:setup` to record it.
3. Rows and SQL mode only for small targeted lookups (one key, a short OR list, a created time). Count each call and put the count in the run log line for Notion. Never read a whole database in rows or SQL mode.
4. On the allowance error, switch to view mode (or REST) at once and finish the run. Never retry rows or SQL mode in the same run. Targeted lookups that remain become in-memory lookups on the view-mode rows. A value only SQL gives (created time) is skipped for this run and recorded as a Decision.
5. The REST path (`notion_rest.py query`) has no such quota. Recommend a Notion integration token under Needs you for any CRM with an Active campaign or more than about 200 contacts.

### Relation filters

- In rows mode, a relation filter (`relation_contains`) takes the related page URL as its value: `https://www.notion.so/<page id without dashes>`. A bare page id is silently ignored and the query returns every row.
- View mode takes no filter, so filter on the relation in memory. Report only the counts (rows read, rows kept); the other rows are not an error.
- Compare page ids, never full URLs. Reduce the target page and every relation value to its page id: the 32 hex characters, dashes removed, lower case, extracted from any form (`https://app.notion.com/p/<id>`, `https://www.notion.so/<id>`, `https://www.notion.so/<title>-<id>`, a dashed or bare id). Relation values arrive as page URLs in MCP rows (often a JSON string of a list) and as ids in REST; the same page in two forms never matches as a string.
- Sanity check, filtered reads only (rows mode with a relation filter, or REST `query --filter`): drop each returned row whose relation does not contain the target page id, and report the count under Needs you. A row count equal to the whole database is a sign the filter was ignored.

## Where MCP alone is limited

- Large CRMs. Use view mode (Query rows). If a read still cannot reach every row, report the check as incomplete, apply what you read, and suggest under Needs you that the user add a Notion token in `/gtm:setup` for bulk reads.
- Created time. Rows mode, view mode and `notion-fetch` do not return a page's created time. Only SQL (`createdTime` column, counted against the quota) and REST (`created_time`) give it. Without them, a rule that needs created time is skipped and recorded as a Decision.
- Relations. Some responses return at most 25 related items. Never read a campaign's contact list from the campaign side. Read Contacts and filter on the relation instead (Relation filters above, and `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Relations).

### Exact copy text

An MCP fetch returns the page as converted text, not the stored text. With a token, always read copy with `notion_rest.py blocks` and use each block's `plain_text`. Without a token, `notion-fetch` the page and normalize the text before you parse or compare it (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`, Reading the page):

1. Un-escape backslash-escaped `_`, `{`, `}`, `*`, `[` and `]` (`first\_name` is `first_name`).
2. Turn mailto links back into the address (`[ada@example.com](mailto:ada@example.com)` is `ada@example.com`).
3. Split a paragraph on `<br />` into separate lines.
4. Ignore a code block's language label, whatever it is: `txt`, `text`, `plain text`, `plaintext`, `javascript`, `markdown`, `none` or no label at all, or any other. The fetch view labels an unlabelled fence `javascript`, and the label a writer sets may not persist. The label never matters and is never part of the copy.

Before any live send, show the normalized text in the run log. If it still looks altered after these steps (escaped quotes, `\n` sequences, missing blank lines inside a code block), skip the step and list it under Needs you. Never repair copy by guessing.

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
- Append to a page body: `notion-update-page` with command `insert_content`, `position` `{"type": "end"}`, and `content` as Notion-flavored Markdown. Read the connector's Markdown spec resource before the first write if it says so.
- Line breaks in content (create and append): separate every line with a blank line. Lines with only a single newline between them merge into one paragraph joined by `<br />`, and log lines then no longer start a paragraph.
- Batches: up to 20 pages per `notion-create-pages` call. Verify each batch before the next one. Set `allow_async` to false when the next step needs the new page ids (for example a contact that links a company or campaign created in the same run); with an async result, wait for the task before using the pages.
- Query: `notion-query-data-sources`. Use view mode for full reads and rows or SQL mode only for counted lookups (Query rows). Relation filter values are page URLs (Relation filters).

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

The token lives only in the credentials file in the gtm config folder (mode 600) or the environment variable `GTM_NOTION_TOKEN`. Only `lib/*.py` reads it. Never `cat` the credentials file, never print the token, headers or exception text, and never put the token in a command line. See `${CLAUDE_PLUGIN_ROOT}/reference/safety.md`.
