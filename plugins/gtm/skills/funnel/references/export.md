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
python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/funnel.py export --out <work>
```

It reads every row of both data sources (following every cursor) and writes `<work>/contacts.json` and `<work>/deals.json`. Exit 2 is a Notion error. If the message says status 401 or 403, fall back to the MCP path for this run and add the token note from `notion-access.md` under Needs you. Any other exit 2 or exit 1: Notion is blocked for this run.

## MCP path

Use `notion-query-data-sources` (the name ToolSearch returns). Read its schema first and use only the modes and parameters it defines.

1. Get the data source ids from `notion.data_sources.contacts` and `notion.data_sources.pipeline`.
2. Read every row you need. The tool's modes differ in how far they can read (see `notion-access.md`, Payload rules: `rows` mode stops at 100 rows with no cursor, `sql` mode pages with `LIMIT` and `OFFSET`, `view` mode pages with a cursor). Pick a mode that can read every row and follow every page or cursor until `has_more` is false or a page comes back short.
3. If no mode can page, narrow the reads so no single result reaches the cap, and query several times:
   - Contacts: one query per counted Status option (the actual names for `Contacted`, `Responded`, `Discovery`, `Lead` from `notion.status_map`). The script counts only these statuses, so other rows are not needed. If one result still reaches the cap, split it again by a First Contacted date range (for example one query per quarter, plus one for an empty date).
   - Deals: one query per stage in `funnel.pilot_stages` and `funnel.customer_stages` (actual names from `notion.option_map.pipeline.stage`). Only these stages count.
   - A result that has exactly the cap size may be cut off. Split it again. If you cannot get every row, the export is incomplete: go to Blocked in `SKILL.md` and suggest a Notion token under Needs you.
4. Save each query result as its own file, as the tool returned it: `<work>/contacts-1.json`, `contacts-2.json`, ..., `deals-1.json`, .... A file may hold a JSON array of rows or an object with a `results`, `rows`, `pages` or `data` array. Do not merge, sort, edit or reformat rows by hand.
5. Make sure every row carries each needed property key. When the tool leaves out a property that is empty, add that key with `null`. Change nothing else. A missing key makes the script report the property as absent from the export.
6. Pass every file to the script: repeat `--contacts <file>` and `--deals <file>`. The script drops duplicate rows by page id, so overlapping queries are safe.

Accepted row shapes, for reference (the script handles all of them):

- `notion_rest.py --simple`: `{"_id": "...", "Status": "Contacted", "First Contacted": "2026-03-04", "Deal": ["<id>"]}`
- raw REST page: `{"id": "...", "properties": {"Status": {"type": "select", "select": {"name": "Contacted"}}, ...}}`
- MCP row: `{"url": "https://www.notion.so/...", "Status": "Contacted", "date:First Contacted:start": "2026-03-04", "Deal": "[\"https://www.notion.so/...\"]"}`

Relation values can be ids, page URLs, a list of either, or a JSON string of such a list.

## Empty pipeline

A workspace with no deals yet is fine. Write `[]` to `deals.json` and pass it. Pilot / Trial and Customer are then 0.
