# email: gmail

## Purpose

Reads the user's Gmail for replies, bounces, auto-replies and mail the user sent by hand, and turns them into normalized events. `/gtm:sweep` reads with it. `/gtm:campaign-run` reads replies with it and sends campaign emails through it.

## Tool

The Gmail MCP connector. It is the only path; there is no `readonly_api.py` entry for Gmail.

- Load the tools with ToolSearch, for example the query `gmail search_threads get_thread send_message`. The names carry a server prefix that differs per session. Use the names ToolSearch returns.
- Read each tool's schema at run time and pass exactly the parameters it defines. The parameter names below were correct at the time of writing; the live schema wins.
- Read tools: `search_threads`, `get_thread`, and `list_labels` (read-only; only to map label ids such as `Label_123` to display names, for `sweep.exclude_labels`).
- Send tool: `send_message`, used only by `/gtm:campaign-run` (see Write / send capability).
- Forbidden in every skill: `create_draft`, `update_draft`, `reply`, `forward`, every tool that creates, changes, applies or removes a label, every spam, trash and untrash tool, and attachment downloads. The sweep uses only the read tools.

## Preflight check

Call `search_threads` with the query `newer_than:1d` and `pageSize` 1. A result, or an empty result `{}`, is ok. A missing tool or an authentication or permission error is blocked.

## Read procedure

Window: from the cursor date (`after`) to now. With no cursor, `sweep.first_run_lookback_days` days back. Gmail `after:` takes `YYYY/MM/DD` and is inclusive.

Excluded labels: for each name in `sweep.exclude_labels` (a mailbox warm-up or sequencer label), add `-label:"<name>"` to the main and sent queries. The operator takes the display name; a label id such as `Label_123` matches nothing. When a thread still shows a label id you cannot place, call `list_labels` once per run to map ids to names, and skip threads that carry an excluded label. Count skipped threads in the run log.

1. Main query: `after:<date> -category:updates -category:promotions -category:social -category:forums`, plus the excluded labels. The category filters remove most newsletters and notifications; in practice they cut the volume by about three quarters.
2. System mail query: `after:<date> (from:mailer-daemon OR from:postmaster OR subject:"out of office" OR subject:"automatic reply" OR subject:"undeliverable")`.
3. Sent query: `after:<date> in:sent`, plus the excluded labels. This finds mail the user sent by hand. The main query already returns most sent threads, so run this one with `view` = `THREAD_VIEW_IDS_ONLY` and `pageSize` 50, follow `pageToken` to the end, and open with `get_thread` only the thread ids the main query did not return.
4. For the main and system mail queries, use `view` = `THREAD_VIEW_METADATA_ONLY` and `pageSize` 20 (the sent query: step 3). A page of 50 metadata threads passed the tool's output limit in testing. Follow `pageToken` until no token is returned. If you stop before the last page, the read is incomplete: report it, apply what you read, and do not move the cursor.
   - Dedupe threads by thread id across the three queries: a thread can appear in both the main and the `in:sent` query. Process each thread once.
   - `search_threads` returns at most 5 messages per thread, and some can be older than the window. Use each message's own date: drop messages dated before the window, and never treat an old message as new activity.
5. From the metadata, collect every address in `sender`, `toRecipients` and `ccRecipients`. Drop addresses in `owner.emails` and on `owner.own_domains`.
6. Resolve the remaining addresses against the CRM in one pass (the sweep's matching step). Do not search Gmail one contact at a time: a person can reply from a second address.
7. `THREAD_VIEW_METADATA_ONLY` has no subject and no snippet, so the prospect, newsletter and system-mail rules cannot be applied from the list. Open a thread in full (`get_thread`, `messageFormat` `PLAIN_TEXT`) before you apply them, and only when it may matter: an address matched a contact, the sending domain matches exactly one contact, it is system mail that names a contact's address, or the sender looks like a prospect (a person at a company domain, not a newsletter or a tool). Mailbox warm-up mail often reads like a prospect: signs are an excluded or unknown user label, near-uniform send times, and stock replies such as "Hi <name>, Thanks for ..." between strangers. Treat such threads as warm-up, never list them under Needs you, and if `sweep.exclude_labels` is empty, suggest once under Needs you that the user add the warm-up label in `/gtm:setup`. Read the whole thread in both directions.
8. Resolve each inbound message by sender address, then reply-to address, then a quoted earlier message in the thread that went to a known contact address, then the sending domain (domain rule in `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Matching). Only after all four fail is it unmatched.

### Reply check for a set of contacts (campaign-run)

`/gtm:campaign-run` reads replies with a narrower search and never reads or moves the sweep's `gmail` cursor.

1. Window: back to the oldest send marker of the run's contacts, or `sending.reply_lookback_days` days when none has one (`newer_than:<n>d` or `after:<date>`).
2. Inbound: `from:<email1> OR from:<email2> ...` in batches of about 15 addresses, plus the window. Follow `pageToken` to the end.
3. Bounces: `(from:mailer-daemon OR from:postmaster OR subject:"undeliverable")` plus the window.
4. Open each hit with `get_thread` (`messageFormat` `PLAIN_TEXT`). Return the same events as below.

## Output

One event per relevant message (format in `${CLAUDE_PLUGIN_ROOT}/adapters/README.md`, Normalized event). `source` is `gmail`. `external_id` is `msg:<message id>`. `detail` holds `subject`, `thread_id`, `direction` and, for outbound, the recipient list.

| Message | Event `kind` | Notes |
|---|---|---|
| From a contact address (inbound, not system mail) | `reply` | `text` = the new part of the message, without the quoted history. The skill classifies it (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`, Reply classification). |
| Auto-reply or out of office | `reply` | Put `"auto": true` in `detail`. The skill logs it as an auto-reply. |
| mailer-daemon or postmaster naming a dead address | `bounce` | `contact_key.email` = the address in the bounce text, not the sender. |
| Sent by the user (label SENT) to a contact | `outbound` | One event per recipient contact. Sent messages only; drafts never appear in search and never count. |

In `detail`, set `user_answered: true` when the user's own message is the latest one in the thread after the inbound message. The skill then logs the reply but does not list it under Needs you.

Drop: newsletters, notifications, calendar invitation mails (the calendar adapter covers meetings), mail between the user's own addresses, and threads with no contact or prospect address.

## Cursor

`state.json` key `gmail`:

```json
{"after": "YYYY-MM-DD", "updated": "<ISO timestamp>"}
```

`after` becomes today's date (in `owner.timezone`) when all three queries were read to the last page. Gmail's `after:` is day-granular, so the next run reads today again; dedupe by date and event makes that safe.

When an outreach adapter was incomplete in this run, `after` moves no later than the earliest unmirrored event date (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/batch.md`, Cursors), so replies from contacts that have no page yet are read again next run.

## Blocked signs and fix

- Tools missing after ToolSearch: "Add the Gmail connector in Claude settings."
- Authentication, permission or token error: "Reconnect the Gmail connector in Claude settings."
- Never try another route (Chrome Gmail, IMAP, a script) for reads when the connector is blocked.

## Write / send capability

Only `/gtm:campaign-run` sends, and only after all its gates passed (`${CLAUDE_PLUGIN_ROOT}/reference/safety.md`, Sending). The sweep and every other skill never send, reply, draft, label or archive.

### Choose the path

Scan the final subject and body (after merge fields are filled) for a link: `http://`, `https://`, `www.`, or a bare domain with a path such as `example.com/page`.

- No link: send with the connector (`send_message`).
- A link: send through Chrome in Gmail on the web (below). The Gmail connector rewrites every link into a Google redirect URL, which looks like phishing to the recipient and breaks tracking. If the Chrome adapter is blocked, skip the step and report it; never fall back to the connector for linked copy.

### Send with the connector

Call `send_message` with:

- `to`: an array with one address, exactly the contact's `email` property. Never take a recipient from an earlier thread.
- `subject`: the step's subject after merge fields. For a follow-up in a thread, the same subject as the first message.
- `body`: the exact copy, plain text, with real line breaks. No HTML (`htmlBody` unset), no Markdown.
- `includeSignature`: false. The copy carries its own sign-off.
- No `cc` or `bcc`.
- First email of a thread (`Thread: new`): no thread parameter.
- Follow-up (`Thread: reply to step <m>`): pass `replyThreadId` = the thread id recorded for step m (take it from the step m marker's evidence, or find it with `search_threads` `to:<contact email> in:sent subject:"<subject>"`). Still set `to` explicitly. If the thread cannot be found, skip the step and list it under Needs you; never start a new thread instead.

### Send through Chrome (copy with a link)

Use `${CLAUDE_PLUGIN_ROOT}/adapters/linkedin/chrome.md`, Chrome basics, for tab handling.

1. Open a new tab on `https://mail.google.com/mail/u/0/#inbox`. A login page means blocked; never sign in.
2. Check the account shown (top right avatar, or the page title) is the expected sender address. If not, stop and report BLOCKED.
3. For a follow-up, open the step m thread from Sent and click Reply. For a new thread, click Compose.
4. Fill To (new thread only), Subject (new thread only) and the body. Click into the body, then insert the text with `document.execCommand('insertText', false, <text>)` through the page-script tool, one call for the whole body, so line breaks and the link stay exactly as written.
5. Read the draft back from the page (the body element's text) and compare it with the copy, paragraph by paragraph. A mismatch: discard the draft, skip the step, report it.
6. Click Send. Wait 3 seconds. Close the tab.
7. Verify with the connector (below), or by opening the message in Sent when the connector is blocked.

### Verify (every message)

1. `get_thread` with `messageFormat` `PLAIN_TEXT` on the returned thread id (Chrome path: find it with `search_threads` `in:sent to:<email> newer_than:1d`).
2. The last message must carry the `SENT` label, `toRecipients` must equal exactly the contact's email, `sender` must equal the expected sender address (`Sender email:` on the campaign page, else `sending.sender_email`), and the subject must match.
3. Compare `plaintextBody` with the copy. Normalize line endings and trailing spaces only. Every paragraph must match. For a reply in a thread, compare only the new part above the quoted history.
4. Any failure is an unconfirmed send. Do not write the marker. List it under Needs you as an unconfirmed send with what you saw. Do not resend in the same run; the next run's already-sent check finds it.
5. A wrong From address stops all email sends for the run and is reported as BLOCKED ("the email connector sends from <address>, expected <address>; reconnect it with the right account").

Bounces arrive later; the next reply check or sweep finds them.
