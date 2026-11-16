# Funnel export

The funnel counts from two reads: Contacts rows and Pipeline (deal) rows. This edition reads them through the Notion connector in view mode only (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows).

Write every file in the work folder in the session scratchpad. Never in the plugin folder or the user's repo.

## Fields the count reads

Resolve each through `notion.field_map` in config.json:

| Database | Logical fields |
|---|---|
| contacts | `name`, `status`, `lead_source`, `first_contacted`, `deal` |
| pipeline | `stage`, `contacts` |

Each row also needs its page id or page URL. The deal relation can come from either side (`contacts.deal` or `pipeline.contacts`); read both and use the union.

## Read every row

Use `notion-query-data-sources` (the name ToolSearch returns). Read its schema first and use only the modes and parameters it defines.

1. Get the view URLs from `notion.views.contacts` and `notion.views.pipeline`. Both forms work as `view_url`: `view://<view id>` or `https://www.notion.so/<database id>?v=<view id>`; pass the stored value as it is. If one is empty, `notion-fetch` the database (not the data source) once, take a `view://` view from the result, use it for this run, and suggest under Needs you that the user run `/gtm:setup` to record it.
2. Read every row in view mode: `mode` `view`, `view_url`, `page_size` 100, and pass `next_cursor` as `start_cursor` until `has_more` is false. Do not export with rows or SQL mode: they share a small workspace allowance that one call can use up.
3. If a view read fails or cannot reach every row (for example the view has its own filter and the row count looks short), the export is incomplete: go to Blocked in `SKILL.md`, with the upgrade message as the fix (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 1).
4. Save each query result as its own file with the Write tool, exactly as the tool returned it: `<work>/raw-contacts-1.json`, `raw-contacts-2.json`, ..., `raw-deals-1.json`, .... Do not retype, merge, sort, edit or reformat rows by hand.
5. Count the rows in the saved files and report them (contacts <n>, deals <n>). The same page id in two files is one row.

## Reading a row

- An MCP row looks like `{"url": "https://www.notion.so/...", "Status": "Contacted", "date:First Contacted:start": "2026-03-04", "Deal": "[\"https://www.notion.so/...\"]"}`.
- The tool leaves out empty properties. A property that a row does not have is blank.
- A date can come as `date:<property>:start` or under the plain property name. Use the first 7 characters (`YYYY-MM`) for the month.
- Relation values can be page URLs, a list of them, or a JSON string of such a list. Reduce each to its page id (32 hex characters, dashes removed, lower case) before you compare (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Relation filters).

## Empty pipeline

A workspace with no deals yet is fine. Pilot / Trial and Customer are then 0.
