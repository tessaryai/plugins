# Notion access

## Edition

This is Tessary GTM, the directory edition. It has no scripts, so it never uses the Notion REST path or a Notion token, in Claude Code and in Cowork alike. Every operation below takes its MCP path, whatever `notion.access` says. When the connector's limits stop a run (the query quota, or a CRM of about 300 contacts or more), follow `${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`.

Every gtm skill works with only the Notion MCP connector. This file says how each operation uses it, and where the connector stops.

## Choose the path

Always MCP. This edition has no REST path and no Notion token, so ignore `notion.access` (Tessary GTM Pro may have written `rest`; leave it as it is).

## Large CRMs and the query quota

The connector can stop a run in two ways. Both are limits of this edition (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 1):

- The rows and SQL quota runs out (Query rows, below). Switch to view mode at once and finish the run. Show the upgrade message only when view mode cannot do the same work.
- The CRM is too large to read reliably in view mode: about 300 contacts or more, or a view-mode read that cannot reach every row. Apply what you read, report the read as incomplete, state your estimate of the contact count, and show the upgrade message.

## Load the MCP tools

The Notion connector's tools are deferred in most sessions. Load them with ToolSearch before the first call, in one query, for example `notion-search notion-fetch notion-query-data-sources notion-create-pages notion-update-page`. Tool names carry a server prefix that differs per session (for example `mcp__<id>__notion-fetch`). Use the names ToolSearch returns.

Read each tool's schema at run time and pass exactly the parameters it defines. Never guess a command name, a parameter name or an enum value. If a tool you need is missing, the Notion adapter is blocked (see `${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`).

## Operations

| Operation | MCP path |
|---|---|
| Find a page or database by name | `notion-search` |
| Read a data source schema (properties, select options) | `notion-fetch` on the database or data source |
| Read every row of a database (index, export) | `notion-query-data-sources` in view mode with `notion.views.<db>` (Query rows, below) |
| Small targeted lookup with a filter | `notion-query-data-sources` in rows or SQL mode, counted against the quota (Query rows) |
| Read one page's properties | `notion-fetch` |
| Read page body blocks with exact text | `notion-fetch` (see Exact copy text below) |
| Read a page's created time | SQL mode, `createdTime` column (counted, Query rows) |
| Create a page in a data source | `notion-create-pages` with the data source as parent, up to 20 pages per call (Payload rules) |
| Update properties | `notion-update-page` (check its schema for the update command) |
| Append text to a page body | `notion-update-page`, command `insert_content`, position end (never `replace_content`) |
| Create a database | `notion-create-database` (setup only) |
| Add or change properties or select options | `notion-update-data-source` (setup only) |

Write work files in the session scratchpad, never in the plugin folder or the user's repo. One exception: `/gtm:import` keeps its work files in `<imports>/<run_id>/` (the `imports` folder in the active config folder), so that `resume` works in a later session (`${CLAUDE_PLUGIN_ROOT}/reference/config.md`).

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
4. On the allowance error, switch to view mode at once and finish the run. Never retry rows or SQL mode in the same run. Targeted lookups that remain become in-memory lookups on the view-mode rows. A value only SQL gives (created time) is skipped for this run and recorded as a Decision.
5. When view mode cannot finish the work, or the CRM has about 300 contacts or more, follow Large CRMs and the query quota, above. Tessary GTM Pro reads with a Notion token, which has no such quota.

### Relation filters

- In rows mode, a relation filter (`relation_contains`) takes the related page URL as its value: `https://www.notion.so/<page id without dashes>`. A bare page id is silently ignored and the query returns every row.
- View mode takes no filter, so filter on the relation in memory. Report only the counts (rows read, rows kept); the other rows are not an error.
- Compare page ids, never full URLs. Reduce the target page and every relation value to its page id: the 32 hex characters, dashes removed, lower case, extracted from any form (`https://app.notion.com/p/<id>`, `https://www.notion.so/<id>`, `https://www.notion.so/<title>-<id>`, a dashed or bare id). Relation values arrive as page URLs in MCP rows (often a JSON string of a list), and as bare ids elsewhere; the same page in two forms never matches as a string.
- Sanity check, filtered reads only (rows mode with a relation filter): drop each returned row whose relation does not contain the target page id, and report the count under Needs you. A row count equal to the whole database is a sign the filter was ignored.

## Where MCP alone is limited

- Large CRMs. Use view mode (Query rows). If a read still cannot reach every row, report the check as incomplete, apply what you read, and show the upgrade message (Large CRMs and the query quota, above).
- Created time. Rows mode, view mode and `notion-fetch` do not return a page's created time. Only SQL (`createdTime` column, counted against the quota) gives it. Without it, a rule that needs created time is skipped and recorded as a Decision.
- Relations. Some responses return at most 25 related items. Never read a campaign's contact list from the campaign side. Read Contacts and filter on the relation instead (Relation filters above, and `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Relations).

### Exact copy text

An MCP fetch returns the page as converted text, not the stored text. `notion-fetch` the page and normalize the text before you parse or compare it (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`, Reading the page):

1. Un-escape backslash-escaped `_`, `{`, `}`, `*`, `[`, `]` and `:` (`first\_name` is `first_name`, `csv\:contact\:101` is `csv:contact:101`). A property value in a view, rows or SQL result is escaped the same way, and its line breaks show as `<br />`.
2. Turn mailto links back into the address (`[ada@example.com](mailto:ada@example.com)` is `ada@example.com`).
3. Split a paragraph on `<br />` into separate lines.
4. Ignore a code block's language label, whatever it is: `txt`, `text`, `plain text`, `plaintext`, `javascript`, `markdown`, `none` or no label at all, or any other. The fetch view labels an unlabelled fence `javascript`, and the label a writer sets may not persist. The label never matters and is never part of the copy.

Before any live send, show the normalized text in the run log. If it still looks altered after these steps (escaped quotes, `\n` sequences, missing blank lines inside a code block), skip the step and list it under Needs you. Never repair copy by guessing.

## Payload rules

Read the tool schema each run; the shapes below were checked against the connector at the time of writing.

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

### Status properties

Every choice field in the gtm schema is a select. If a mapped workspace uses a real Notion `status` property, setup records it in `notion.select_payload` (for example `{"contacts.status": "status"}`); MCP filters then use the status filter type for that property. Check the live schema; do not assume.

## Select options

- Validate every select value against the live schema before a write. Read the schema once per run (`notion-fetch`). An unknown option either fails the write or creates a new option, depending on the path.
- Never create a new select option, except during `/gtm:setup` when the user agrees. If a needed option is missing, skip that write and list it under Needs you with the fix ("add option X to property Y, or map it in config").

## Hard stops

- A 400 error, or a tool warning, about deleting child pages or child databases is a hard stop. Do not retry with a changed payload. Do not pass a flag that allows deleting content. Report it under Needs you.
- Never use a whole-page replace (`replace_content` or any command that rewrites the full body) on a contact, company or campaign page. It can wipe log lines and campaign markers, and lost markers cause repeat sends. Append with `insert_content` at the end. Only the funnel page is replaced in full, by `/gtm:funnel`.
- Never use `update_content` search-and-replace on log lines or markers. They are append-only.
- Never move or re-parent a page by writing a URL into its content. Use the connector's move tool only when the user asks.
- Never delete a page, database or block. Skills only create, update properties and append.

## Tokens

This edition uses no Notion token. Never read, `cat` or create the credentials file, and never ask for a token. See `${CLAUDE_PLUGIN_ROOT}/reference/safety.md`.

## Limits of this edition

When a read hits the query quota and view mode cannot finish the work, or the CRM has about 300 contacts or more, follow `${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 1: finish what is safe, report the read as incomplete, and show the upgrade message once.
