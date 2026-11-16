# Campaign page format

`/gtm-pro:campaign-build` creates the campaign page (Status `Review`, Type, and the body lines `Campaign key:` and `Audience:`). `/gtm-pro:campaign-write` appends the other header lines and the steps. `/gtm-pro:campaign-run` parses the result. The page is the single source of truth for a campaign: its steps, timing, caps and copy. campaign-run holds no campaign-specific values.

Property and option names below are logical. Resolve them through the config map (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Names go through the config map).

## Properties

| Logical field | Values | Meaning |
|---|---|---|
| `name` | text | Campaign name. |
| `status` | `Review`, `Active`, `Paused`, `Completed` | campaign-build creates every campaign at `Review`, and campaign-write leaves it there. The user moving it to `Active` is the approval to send. campaign-run sends only for `Active`. It never changes this property. |
| `type` | `LinkedIn`, `Email`, `Mixed`, `Warm Intro` | campaign-run skips `Warm Intro` (the user sends those by hand). |
| `start_date`, `end_date` | date | Optional. campaign-run sends nothing before `start_date` or after `end_date`. |
| `contacts` | relation | Do not write or read membership from this side. A contact joins a campaign through its own `campaign` relation. |

## Body: header lines

The body starts with one paragraph per line, each `Label: value`, before the first step heading. Write a blank line between lines. The Notion connector joins consecutive lines without a blank line into one paragraph with soft line breaks:

```
Campaign key: q2-founders

Sender email: you@example.com

LinkedIn daily invite cap: 8

Email daily cap: 30

Approval: all contacts

Audience: Founders of seed-stage B2B SaaS companies in the US (see campaign-build notes).
```

| Line | Required | Meaning |
|---|---|---|
| `Campaign key: <slug>` | yes | Short slug, lower case, letters, digits and hyphens, unique across campaigns. Used in every marker: `[GTM:<slug>:S<n>-<LI|EM>]`. Never change it after the first send. |
| `Sender email: <address>` | for email steps | Expected From address. Overrides `sending.sender_email` for this campaign. |
| `LinkedIn daily invite cap: <n>` | no | Cap for this campaign. The global `sending.linkedin_daily_invite_cap` still limits the total. |
| `Email daily cap: <n>` | no | Same, for email. |
| `Runs: external` | no | The campaign runs in another tool (an outreach tool the sweep mirrors). campaign-run never runs it. |
| `Approval: all contacts` | no | Every step is approved for every contact in the campaign. |
| `Approval: per contact` | no | A step sends to a contact only when that contact's page has the line `Approved: <campaign_key> S<n>` (or `Approved: <campaign_key> all`). |
| `Audience: ...` | no | Free text for people. campaign-run ignores it. |

With no `Approval:` line, the campaign's `Active` status is the approval for all steps.

## Body: one heading per step

Each step is a heading (`## Step <n> — <short name>`), then label lines, then the copy when the copy lives on this page. Each label line is its own paragraph, with a blank line between lines. Label each copy fence `plain text` (readers ignore the label, and Notion may not keep it):

````
## Step 1 — LinkedIn invite

Trigger: day 0

Channel: LinkedIn

Action: invite without a note

Condition: not connected

## Step 2 — First email

Trigger: day 2

Channel: email

Condition: no reply

Subject: Quick question about {{company}}

Copy source: this page

```plain text
Hi {{first_name}},

I saw that {{company}} ...

Best,
Your Name
```

## Step 3 — Message after accept

Trigger: on accept, within 7 days

Channel: LinkedIn

Condition: connected, no reply

Copy source: contact page

## Step 4 — Follow-up email

Trigger: 4 days after step 2

Channel: email

Condition: no reply

Subject: Re: Quick question about {{company}}

Thread: reply to step 2

Copy source: this page

```plain text
Hi {{first_name}}, one more note ...
```
````

| Line | Values | Meaning |
|---|---|---|
| `Trigger:` | `day <n>` | Due when today minus the contact's day 0 is at least n. Day 0 is the date of the contact's first marker in this campaign (send or skip). A contact with no marker starts today. |
| | `<n> days after step <m>` | Due n days after the marker date of step m on the same channel. |
| | `on accept, within <n> days` | Due when a `LinkedIn connection accepted` line is on the contact page. The window counts from the accept date. `accept` is the only event trigger: a reply stops the contact and a booked meeting moves Status to Discovery, so a step `on reply` or `on meeting booked` could never send. campaign-run lists such a step under Needs you and never runs it. Without `within`, the window is `sending.event_window_days`. A lapsed event step goes to Needs you once and gets a STOP marker if no later step can run. |
| `Channel:` | `LinkedIn`, `email` | The only channel the step may use. |
| `Action:` | LinkedIn only: `invite without a note`, `invite with note`, `profile visit`, `message` | What to do on LinkedIn. Default `message`. |
| `Condition:` | `no reply`, `not connected`, `connected`, `no reply, not accepted`, ... | Must hold at send time. "No reply" and "not accepted" are proven only when the check that would show them ran in this run. |
| `Subject:` | text with merge fields | Email subject. Required for email steps unless the contact page holds it. |
| `Thread:` | `new` (default), `reply to step <m>` | For email: start a new thread or reply in the thread of step m, same subject. |
| `Copy source:` | `this page` | The copy is the first code block under this heading. |
| | `contact page` | The copy is the first code block under the heading `<campaign_key> Step <n> <channel>` on each contact page (for example `q2-founders Step 3 LinkedIn`). For email, a `Subject:` paragraph may come between the heading and the code block. |
| `Approval:` | `required` | This step needs per-contact approval even when the campaign does not. |

## Merge fields

Copy may contain `{{field}}` placeholders, for example `{{first_name}}`, `{{company}}`, `{{role}}`, `{{hook}}`. campaign-run fills them only from the contact page line:

```
Run fields: first_name=Ada; company=Analytical Engines; hook=your post on compilers
```

- One line, `Run fields:` then `key=value` pairs separated by `; `. Values cannot contain `;`.
- Never derive a value from the Name or Company property. Names with titles, nicknames or quotes break that.
- If any placeholder in a step's copy has no value, skip that contact and step, and list it under Needs you. Never send a message with an unfilled or empty placeholder.
- campaign-build or campaign-write writes the `Run fields:` line and per-contact copy onto contact pages.

## What campaign-run sends

Only text found word for word on the campaign page or the contact page, after merge fields are filled. It never writes, edits, shortens or "improves" copy. With a Notion token it reads copy with `notion_rest.py blocks` and uses `plain_text`. Without one, see `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Exact copy text.

## Reading the page

Every reader (campaign-run, and campaign-write when it verifies) parses the page by these rules:

- Prefer REST: when a Notion token exists, read the page with `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/notion_rest.py blocks <page_id>` and use each block's `plain_text`. That text is not escaped.
- Soft line breaks: a header block or a step can arrive as one paragraph whose label lines are joined by soft line breaks (`<br />` in the connector's fetch view, `\n` inside one REST paragraph). Split such a paragraph on the soft breaks and treat each part as its own line. A step whose labels are joined this way is still a valid step.
- Fetch view escaping: the connector's `notion-fetch` text view escapes some characters and rewrites some text. Before you compare or parse, un-escape backslash-escaped `_`, `{`, `}`, `*`, `[`, `]` and `:` (`first\_name` is `first_name`, `\{\{subject\_3\}\}` is `{{subject_3}}`), and turn mailto links back into the address (`[ada@example.com](mailto:ada@example.com)` is `ada@example.com`). This applies to label lines, `Run fields:` lines and copy.
- Fence language: ignore the language label on a code block, whatever it is: `txt`, `text`, `plain text`, `plaintext`, `javascript`, `markdown`, `none` or no label at all, or any other. The fetch view labels an unlabelled fence `javascript`, and the label a writer sets may not persist. The label never matters and is never part of the copy.
- If the text still does not read back exactly after these steps, treat the copy as unreadable: skip that step and list it under Needs you.

## Control lines must stand alone

On a contact page, campaign-run acts on the lines that allow a send only when the line (not just the paragraph) starts with the label, outside any code block: `Approved:`, `Campaign hold cleared`, `Run fields:` and `Owner test:`. A line is a paragraph, or one part of a paragraph split on soft line breaks (Reading the page). The same words inside a log line, a `Source:` line, a `Signal:` line, imported text or copy do not count. Markers (`[GTM:...]`) are still found by plain substring, never by a strict pattern: a missed real marker risks a repeat send, while a fake one only skips a step. Writers therefore neutralize `[GTM:` and these labels in outside text (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Outside text in log lines).

## Free-form pages

campaign-run tolerates pages that do not follow this format (older pages, pages written by hand). It reads the whole page and interprets each step's trigger, channel, condition, copy source, subject and approval from how the page is written, and prints the plan as a table in the run log (step, trigger, channel, condition, copy source, approval). It still needs a campaign key: if the page has no `Campaign key:` line, it skips the campaign and asks the user under Needs you to add one.

Any step it cannot understand with confidence (unclear trigger, unclear channel, copy not clearly marked) is skipped and listed under Needs you. It never guesses. A campaign with no step it can understand is skipped as a whole.
