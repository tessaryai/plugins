# Page writes

campaign-write writes headings and code blocks. Both must arrive in Notion as real heading and code blocks, because campaign-run finds a step by its heading and takes the copy from the first code block under it.

## Which tool writes

- Use the Notion connector: `notion-update-page` with the command `insert_content` and position at the end (check the tool's schema at run time for the exact command and parameter names). Pass Notion-flavored Markdown: `## ` for a heading, a fenced code block for copy, one paragraph per label line. If the connector offers a Markdown spec resource, read it before the first write.
- Write each label line as its own paragraph: separate lines with a blank line. This applies to header lines, step label lines, `Subject:`, `Source:` and `Run fields:` lines. The connector joins consecutive lines without a blank line into one paragraph with soft line breaks, and the page then has one paragraph where campaign-run expects several.
- Label every copy fence ```` ```plain text ````. The label may not persist (an unlabelled fence comes back from the fetch view labelled `javascript`, and Notion can change a label); it does not matter, because readers ignore it. Inside the fence, write the copy as is: blank lines between copy paragraphs, no escaping.
- Never use `replace_content` or `update_content`. Never rewrite a block. To fix a mistake, tell the user what is wrong and where; they fix it by hand.

## Before appending

1. Read the page body fresh.
2. Campaign page: confirm there is no step heading yet (no heading that starts with `Step `). Confirm which header lines exist; append only the missing ones, and only before any step.
3. Contact page: confirm there is no heading `<campaign_key> Step <n> <channel>` for the steps you will write and, when you will write one, no `Run fields:` line (see `personalize.md` for reuse).
4. If the page changed in a way that breaks these checks, skip it and list it under Needs you.

## Write order on the campaign page

One `insert_content` call with, in order: the missing header lines, then each step heading with its label lines and, for copy on this page, its code block. Writing it in one call keeps the header lines above the first step. Put a blank line between every header line, every heading, every label line and every code block:

````
Sender email: you@example.com

Email daily cap: 30

## Step 1 — First email

Trigger: day 0

Channel: email

Condition: no reply

Subject: A note about {{company}}

Copy source: this page

```plain text
Hi {{first_name}},

...
```
````

## Verify

`notion-fetch` the page and check, in its text view:

- Each step heading is a heading that matches what you wrote.
- Each label line is its own paragraph with the exact text. A paragraph that holds several label lines joined by soft line breaks means the blank lines were lost. campaign-run tolerates it (`${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`, Reading the page), so do not append a fix; note it in the report.
- Each copy block is a code block whose text equals the approved copy exactly. Compare after normalizing line endings and trailing spaces only. Ignore the code block's language. The fetch view is not the stored text. Before you compare:

1. Un-escape backslash-escaped `_`, `{`, `}`, `*`, `[`, `]` and `:`: `first\_name` is `first_name`, `\{\{subject\_3\}\}` is `{{subject_3}}`.
2. Strip mailto link syntax: `[ada@example.com](mailto:ada@example.com)` is `ada@example.com`.
3. Split a paragraph on `<br />` into separate lines.
4. Ignore the fence label, whatever it is (`txt`, `plain text`, `javascript`, none or any other).

If the text still differs after these steps (quotes look escaped, `\n` sequences appear, or blank lines are missing inside a code block), the copy may not read back exactly. Report it under Needs you, because campaign-run will skip copy it cannot read exactly.

A mismatch is never fixed by appending a second copy. Report the page, the step and the difference under Needs you.

## Dry run

In `dry-run`, show the exact Markdown each page would get, and write nothing.
