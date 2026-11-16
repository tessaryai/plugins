# Funnel export

`lib/funnel.py run` reads two exports: Contacts rows and Pipeline (deal) rows. This file says how to build them. Choose the path as in `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`: REST when `notion.access` is `rest` and the token is saved, MCP otherwise.

Write every file in the work folder in the session scratchpad. Never in the plugin folder or the user's repo.

## Fields the script reads

Resolve each through `notion.field_map` (`config.py show`):

| Database | Logical fields |
|---|---|
| contacts | `name`, `status`, `lead_source`, `first_contacted`, `deal` |
| pipeline | `stage`, `contacts` |

Each row also needs its page id or page URL. The deal relation can come from either side (`contacts.deal` or `pipeline.contacts`); the script reads both and needs at least one.

## REST path

```bash
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/funnel.py export --out <work>
```

It reads every row of both data sources (following every cursor) and writes `<work>/contacts.json` and `<work>/deals.json`. Exit 2 is a Notion error. If the message says status 401 or 403, fall back to the MCP path for this run and add the token note from `notion-access.md` under Needs you. Any other exit 2 or exit 1: Notion is blocked for this run.

## MCP path

Use `notion-query-data-sources` (the name ToolSearch returns). Read its schema first and use only the modes and parameters it defines.

1. Get the view URLs from `notion.views.contacts` and `notion.views.pipeline`. Both forms work as `view_url`: `view://<view id>` (the form `notion-fetch` on a database returns, which the query tool accepts as `view_url`) or `https://www.notion.so/<database id>?v=<view id>`; pass the stored value as it is. If one is empty, `notion-fetch` the database (not the data source) once, take a `view://` view from the result, use it for this run, and suggest under Needs you that the user run `/gtm:setup` to record it.
2. Read every row in view mode: `mode` `view`, `view_url`, `page_size` 100, and pass `next_cursor` as `start_cursor` until `has_more` is false. View mode has no plan quota (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows). Do not export with rows or SQL mode: they share a small workspace allowance that one call can use up, and splitting the export into many filtered queries uses it up faster.
3. If a view read fails or cannot reach every row (for example the view has its own filter and the row count looks short), the export is incomplete: go to Blocked in `SKILL.md` and suggest a Notion token under Needs you. If a rows or SQL call returns the allowance error, never retry it in this run.
4. Save each query result as its own file with the Write tool, exactly as the tool returned it: `<work>/raw-contacts-1.json`, `raw-contacts-2.json`, ..., `raw-deals-1.json`, .... Paste the tool output as it is (a JSON array, an object with a `results` array, or the tool's text with the JSON inside). Do not retype, merge, sort, edit or reformat rows by hand.
5. Normalize each database once, passing every raw page file:

   ```bash
   python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/funnel.py normalize --in <work>/raw-contacts-1.json [--in <work>/raw-contacts-2.json ...] --out <work>/contacts.json
   python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/funnel.py normalize --in <work>/raw-deals-1.json [--in ...] --out <work>/deals.json
   ```

   The script tells contacts from pipeline rows by the mapped property names it finds. If it says it cannot tell (exit 1), add `--db contacts` or `--db pipeline`.

   It reads the rows out of each file and adds every property the script needs (resolved through `notion.field_map`) that a row leaves out, with `null`, because the MCP tool omits empty properties. A date property (`first_contacted`) is added in the MCP form `date:<property>:start`, unless the row has it under the plain property name; every other property is added under its plain property name. The script accepts both forms. Nothing else changes. Exit 1 means a file holds no JSON rows: save that page again from the tool output.
6. Pass the two normalized files to the script: `--contacts <work>/contacts.json --deals <work>/deals.json`. The script drops duplicate rows by page id, so overlapping pages are safe.

Accepted row shapes, for reference (the script handles all of them):

- `notion_rest.py --simple`: `{"_id": "...", "Status": "Contacted", "First Contacted": "2026-03-04", "Deal": ["<id>"]}`
- raw REST page: `{"id": "...", "properties": {"Status": {"type": "select", "select": {"name": "Contacted"}}, ...}}`
- MCP row: `{"url": "https://www.notion.so/...", "Status": "Contacted", "date:First Contacted:start": "2026-03-04", "Deal": "[\"https://www.notion.so/...\"]"}`

Relation values can be ids, page URLs, a list of either, or a JSON string of such a list.

## Empty pipeline

A workspace with no deals yet is fine. Write `[]` to `deals.json` and pass it. Pilot / Trial and Customer are then 0.
