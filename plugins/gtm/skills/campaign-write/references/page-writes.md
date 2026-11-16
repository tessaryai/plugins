# Page writes

campaign-write writes headings and code blocks. Both must arrive in Notion as real heading and code blocks, because campaign-run finds a step by its heading and takes the copy from the first code block under it.

## Which tool writes

- Use the Notion connector: `notion-update-page` with the command `insert_content` and position at the end (check the tool's schema at run time for the exact command and parameter names). Pass Notion-flavored Markdown: `## ` for a heading, a fenced code block for copy, one paragraph per label line. If the connector offers a Markdown spec resource, read it before the first write.
- Do not use `notion_rest.py append` for these writes. It appends plain paragraphs only, so a heading or a code block would arrive as literal text. REST is still the best way to read the result back.
- Never use `replace_content` or `update_content`. Never rewrite a block. To fix a mistake, tell the user what is wrong and where; they fix it by hand.

## Before appending

1. Read the page body fresh.
2. Campaign page: confirm there is no step heading yet (no heading that starts with `Step `). Confirm which header lines exist; append only the missing ones, and only before any step.
3. Contact page: confirm there is no heading `<campaign_key> Step <n> <channel>` for the steps you will write and, when you will write one, no `Run fields:` line (see `personalize.md` for reuse).
4. If the page changed in a way that breaks these checks, skip it and list it under Needs you.

## Write order on the campaign page

One `insert_content` call with, in order: the missing header lines, then each step heading with its label lines and, for copy on this page, its code block. Writing it in one call keeps the header lines above the first step.

## Verify

With a Notion token, read the page with `python3 -I ${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py blocks <page_id> --out <scratchpad>/<page>.json` and check:

- Each step heading is a heading block (`heading_1`, `heading_2` or `heading_3`) whose `plain_text` matches what you wrote.
- Each label line is its own paragraph with the exact text.
- Each copy block is a `code` block whose `plain_text` equals the approved copy exactly. Compare after normalizing line endings and trailing spaces only.

Without a token, `notion-fetch` the page and check the same things in its text view. If quotes look escaped, `\n` sequences appear, or blank lines are missing inside a code block, the copy may not read back exactly. Report it under Needs you and suggest adding a Notion token in `/gtm:setup`, because campaign-run will skip copy it cannot read exactly.

A mismatch is never fixed by appending a second copy. Report the page, the step and the difference under Needs you.

## Dry run

In `dry-run`, show the exact Markdown each page would get, and write nothing.
