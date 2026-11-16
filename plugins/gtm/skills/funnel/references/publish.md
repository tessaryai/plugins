# Publish the funnel

Publishing always uses the Notion MCP tools (`notion-fetch`, `notion-create-pages`, `notion-update-page`), loaded with ToolSearch. `lib/notion_rest.py` has no replace command, so the REST path is never used here. Read each tool's schema at run time and use only the parameters it defines.

## 1. Find or create the Funnel page

1. Read `notion.funnel_page_id` from config. Treat an empty value, or a placeholder of only zeros, as not set.
2. Set: `notion-fetch` the page.
   - The page is gone, in the trash, or not shared with the connector: report under BLOCKED ("the Funnel page cannot be read; restore it or clear notion.funnel_page_id so the next run creates a new one"). Do not create a second page on your own.
   - The result is a database or a data source, not a page: stop and report under Needs you. Never replace a database.
3. Not set, and `notion.parent_page_id` is set: create the page, unless the run is a dry run.
   - `notion-create-pages` with the parent page as parent (check the schema for the page-parent shape), title `Funnel`, content `As of: not run yet. Run /gtm:funnel to fill this page.` (from `${CLAUDE_PLUGIN_ROOT}/templates/schema.json`, `pages[0]`).
   - Save the new id: `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py set notion.funnel_page_id <id>`.
   - Record it under Decisions ("created the Funnel page under <parent title> (was: not set)").
4. Not set, and no parent page: do not publish. Under Needs you: "Pick the page for the funnel: run /gtm:setup, or set notion.funnel_page_id to an empty page."

## 2. Check the page is safe to replace

From the fetch in step 1, look for child pages, child databases or linked databases inside the page body. A full replace would delete them. If there are any, do not replace. Report under Needs you: "The Funnel page holds child pages or databases; move them out, or point notion.funnel_page_id at an empty page."

## 3. Replace the content

1. Read `<work>/out/funnel_tables.md` in full.
2. Call `notion-update-page` with the page id and the command the schema gives for replacing the whole page content (at the time of writing `replace_content`, with the new text in `new_str`). Pass the file's full text, unchanged.
3. Do not pass any parameter that allows deleting child pages or content. If Notion answers that content or child pages would be deleted, stop. That is a hard stop (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Hard stops). Report it under BLOCKED; do not retry with a changed payload.
4. Any other error: retry once after a few seconds. If it fails again, the publish failed: go to Blocked in `SKILL.md`.

This is the only full-page replace in the gtm plugin. Never use it on any page other than the one in `notion.funnel_page_id`.

## 4. Verify

`notion-fetch` the page again and check:

- The first line holds `As of <as_of date>` from `funnel_summary.json`.
- There is a `Cold outbound` and a `Warm outbound` heading (and `Inbound` when the run had an inbound file).
- Each table has a `Total` row whose numbers match the `Total` rows in `funnel_tables.md`.

A mismatch means the publish did not take. Report it under BLOCKED with what you saw. Do not try to patch single cells.

Report `published: yes` only after this check passes. Link the page in the final report.
