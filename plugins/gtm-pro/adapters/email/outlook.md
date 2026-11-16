# email: outlook

## Purpose

Reads the user's Outlook (Microsoft 365) mailbox for replies, bounces, auto-replies and mail the user sent by hand, and turns them into normalized events. `/gtm-pro:sweep` reads with it. `/gtm-pro:campaign-run` reads replies with it and sends campaign emails through it.

This adapter follows the same rules as `${CLAUDE_PLUGIN_ROOT}/adapters/email/gmail.md`. Only the tool calls differ. Where this file is silent, apply the Gmail file.

## Tool

Preferred: a Microsoft 365 / Outlook MCP connector in the session. Find it with ToolSearch (queries such as `outlook mail`, `microsoft 365 mail`, `office365 email`). Connector tool names differ between vendors, so never assume a name. Read the schemas and pick:

- a search or list tool for messages (with a date filter and paging),
- a tool that reads one message or one conversation in full,
- a send tool (only `/gtm-pro:campaign-run` may call it).

Forbidden in every skill: draft, reply, forward, move, delete, flag, categorize and rule tools. The sweep uses only read tools.

Fallback for sending only: Outlook on the web through Claude in Chrome (below). There is no `readonly_api.py` entry for Outlook, so with no connector the read side is blocked.

## Preflight check

List one message from the inbox with the connector's list or search tool. A result or an empty list is ok. A missing connector, or an auth or permission error, is blocked.

## Read procedure

Window: from the cursor date to now. With no cursor, `sweep.first_run_lookback_days` days back.

1. Inbox query: messages received on or after the cursor date. Exclude the `Other` tab (Focused Inbox) and folders such as Junk, newsletters and notifications when the tool can filter by folder or inference class; otherwise drop them yourself from the sender and subject.
2. System mail query: messages from `postmaster` or `mailer-daemon`, or with a subject that contains `Undeliverable`, `Automatic reply` or `Out of office`, on or after the cursor date.
3. Sent Items query: messages the user sent on or after the cursor date.
4. Request only metadata (sender, recipients, date, subject, conversation id) in the list calls when the tool allows field selection. Follow every page link or cursor until none is returned. Stopping early makes the read incomplete.
5. Collect addresses, drop the user's own (`owner.emails`, `owner.own_domains`), and resolve against the CRM in one pass.
6. Open a message or conversation in full only when it may matter (same rule as Gmail, Read procedure step 7). Read it in plain text.

### Reply check for a set of contacts (campaign-run)

As in Gmail, Reply check for a set of contacts: search messages from the run's contact addresses (batched, with the connector's filter syntax from its schema) in the window, then system mail in the window, and open each hit in full. `/gtm-pro:campaign-run` never reads or moves the sweep's `outlook-mail` cursor.

## Output

Same events and rules as Gmail (Output). `source` is `outlook`. `external_id` is `msg:<message id>`; `detail.thread_id` holds the conversation id.

## Cursor

`state.json` key `outlook-mail`:

```json
{"after": "YYYY-MM-DD", "updated": "<ISO timestamp>"}
```

Moves to today only when all three queries were read to the last page. When an outreach adapter was incomplete in this run, it moves no later than the earliest unmirrored event date (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/batch.md`, Cursors).

As with Gmail: keep list pages small enough for the tool's output limit, dedupe conversations that appear in both the inbox and Sent Items queries, and filter messages by their own date, because a conversation can carry messages older than the window.

## Blocked signs and fix

- No Outlook connector in the session: "Add a Microsoft 365 / Outlook connector in Claude settings."
- Auth or permission error: "Reconnect the Outlook connector in Claude settings."
- Never try another route for reads.

## Write / send capability

Only `/gtm-pro:campaign-run` sends, after all its gates. The rules of Gmail, Write / send capability, apply: exact copy, plain text, one recipient taken from the contact's `email` property, no signature, no cc or bcc, follow-ups in the thread of the earlier step, verify before the marker.

### Choose the path

1. Connector with a send tool: use it. Plain text body (set the content type to text when the schema has one). For a follow-up, use the connector's way to send into an existing conversation only if it does not add quoted text you cannot see; otherwise use the Chrome path for follow-ups.
2. Copy with a link: treat this connector like Gmail and send through Chrome, because Microsoft Safe Links and some connectors rewrite URLs. If the Chrome adapter is blocked, skip the step and report it; never fall back to the connector for linked copy.
3. A connector that reads but has no send tool: Chrome on Outlook on the web for every send. With no connector at all the read side is blocked, so the reply check cannot run and no email step sends (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`).

### Send through Chrome (Outlook on the web)

Tab handling as in `${CLAUDE_PLUGIN_ROOT}/adapters/linkedin/chrome.md`, Chrome basics.

1. Open a new tab on `https://outlook.office.com/mail/` (work accounts) or `https://outlook.live.com/mail/` (personal accounts). A login page means blocked.
2. Check the account shown is the expected sender address. If not, stop and report BLOCKED.
3. New thread: click New mail, fill To and Subject. Follow-up: open the earlier message in Sent Items and click Reply.
4. Click into the body and insert the copy with `document.execCommand('insertText', false, <text>)` through the page-script tool, in one call.
5. Read the body back from the page and compare paragraph by paragraph. A mismatch: discard, skip, report.
6. Click Send. Wait 3 seconds. Close the tab.

### Verify (every message)

Read the sent message back from Sent Items (with the connector's read tool, or in Chrome). Check: recipient is exactly the contact's email, sender is the expected address, subject matches, and the body matches the copy paragraph by paragraph (line endings and trailing spaces normalized). Any failure is an unconfirmed send: no marker, list it under Needs you as an unconfirmed send, no resend in the same run (the next run's already-sent check finds it). A wrong sender address stops all email sends and is reported as BLOCKED.
