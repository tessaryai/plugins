# Send, verify, mark

The channel procedures (which tools, which clicks, how to read a message back) live in the adapter files. This file is the loop around them. Read the adapter file before the first send of the run:

- Email: `${CLAUDE_PLUGIN_ROOT}/adapters/email/<adapters.email>.md` (`gmail` or `outlook`), section Write / send capability.
- LinkedIn: `${CLAUDE_PLUGIN_ROOT}/adapters/linkedin/chrome.md`, section Write / send capability.

Only this skill sends, and only in a live run. Send one message at a time, in the order from `plan.md`, Order and caps.

## For each due step

1. Fresh gate read. Read the contact again (properties and body) and run every gate in `plan.md`, Gates. A new reply line, a STOP marker, suppression or a Status of Responded or later stops here.
2. Build the final text.
   - Copy source `this page`: the code block under the step heading. Copy source `contact page`: the block under `<campaign_key> Step <n> <channel>` on the contact page, and for email a `Subject:` line there if the campaign page has none.
   - Use the normalized fetch text (`plan.md`, Read a campaign page, step 2): never send text that still holds a fetch-view escape such as `\_` or a mailto link.
   - Fill each `{{field}}` from `Run fields:`, and nothing else. Change no other character.
   - Check for gaps (`plan.md`, Gates 7). A gap skips the step.
   - Keep the exact text for the verify step.
3. Already sent check. A crash, a timeout or an unconfirmed send in an earlier run can leave a message on the channel with no marker. Before you send, look for it on the channel, as the adapter describes:
   - Email: search sent mail to the contact's address with this subject since day 0.
   - LinkedIn invite: the profile shows Pending.
   - LinkedIn message: the thread with the contact already holds this text from the user.
   If you find it, do not send again. Verify the found message against the text (Verify, below). If it matches, write the marker with the date the message was sent and the Action `campaign-run (found on channel)`. If it does not match, write nothing and list it under Needs you.
4. Send through the adapter (channel rules below).
5. Verify on the channel (below). Every message, no sampling.
6. Mark. Only after a verified send, append the marker, then write Status:
   - Marker: `YYYY-MM-DD — [GTM:<campaign_key>:S<n>-<LI|EM>] <event>. Action: campaign-run (<adapter>).` Examples of `<event>`: `LinkedIn invite sent, no note`, `LinkedIn invite sent with note`, `LinkedIn profile visited`, `LinkedIn message sent`, `Email sent: "<subject>"`. Check that the same marker is not on the page before you append, in the normalized body text (`plan.md`, Contact state).
   - Status: if the logical Status is New, set Contacted (forward only, select payload, `crm-rules.md`, Gates before any Status write). Never move Status past Contacted in this step.
   - First Contacted: set it to today only when it is empty. It is write-once.
   - MCP: `notion-update-page` with `insert_content` at the end for the marker, and `update_properties` for Status and First Contacted. Shapes in `notion-access.md`, Payload rules.
7. Read the page again. Confirm the marker, Status and First Contacted. A mismatch goes under Reconcile.
8. Wait as the adapter says before the next contact.

## Failed and unconfirmed sends

- The send failed (tool error, the message is not on the channel): write no marker. List it under Failed sends. The next run retries it, after the already sent check.
- The send may have happened but the read-back does not confirm it (wrong recipient, wrong From, changed text, not found yet): write no marker. List it under Needs you as an unconfirmed send with what you saw. The already sent check in the next run finds it, so it is not sent twice.
- Never resend a step in the same run. Try each step at most once per run.
- A wrong From address blocks the email channel for the rest of the run (SKILL.md, Blocked).

## Email

- Recipient: exactly one address, the contact's `email` property. Never inherit recipients from a thread. No CC, no BCC.
- From: the effective sender email (`plan.md`, Effective values). It must be one of `owner.emails`. If not, stop email sends and list it under Needs you.
- Subject: from the step, after merge fields. `Thread: reply to step <m>`: reply in the thread of step m's sent message (find it by the already sent check for step m), keep the same subject the page gives, and still set the recipient explicitly. `Thread: new` or no `Thread:` line: a new thread.
- Body: the exact text, plain text, with its real line breaks. No HTML, no Markdown, no added signature (the copy holds its own sign-off).
- Links: some email connectors rewrite links in the body (for example into a redirect URL). Before a send, scan the subject and body for a link (`http://`, `https://`, `www.`, or a bare domain with a path). If the copy has a link and the adapter says its connector rewrites links, use the adapter's browser path for that message (compose in the web mail in Claude in Chrome). If the adapter has no safe path for linked copy, skip the step and list it under Needs you.
- Verify: open the sent message as plain text and check that it is in sent mail, the recipient is exactly the contact's address, the From address is the expected sender, the subject matches, and the body matches the text paragraph by paragraph. Normalize line endings and trailing spaces only.
- A bounce arrives later. The next reply check finds it and closes the email channel.

## LinkedIn

The adapter has the clicks. These points decide what the step does. LinkedIn automation can get an account restricted, so go slowly and stop at the first warning (`${CLAUDE_PLUGIN_ROOT}/reference/safety.md`, LinkedIn account risk).

1. Open the contact's profile (`https://www.linkedin.com/in/<slug>/`) in a tab this run opened. Read the state from a screenshot of the top card: name, connection degree, and the buttons. DOM selector scripts for this have returned empty values on the live page; screenshots are the reliable source, with the accessibility tree as a second check.
2. Confirm the name on the profile matches the contact. A mismatch means the URL is wrong: skip the step and list it under Needs you.
3. Act on the state:

| Profile state | Meaning | What the step does |
|---|---|---|
| 1st degree, Message button | Connected | The accept happened. If no accept line is on the page, append `YYYY-MM-DD — LinkedIn connection accepted (seen on profile). Action: campaign-run (Chrome).` and treat it as the accept event. Never send an invite. Message steps may run. |
| Pending | Invite sent, not accepted | Never send a second invite. Message steps that need "connected" wait. |
| Connect button (often hidden under the More menu) | Not connected, no invite | An invite step may send. Open More first if Connect is not shown. |
| Follow only, no Connect under More | Cannot connect | Skip LinkedIn steps for this contact: write the due step's `-SKIP` marker now, and each later LinkedIn step's `-SKIP` marker once, when that step becomes due (`plan.md`, Due rules). |

4. Invite: send exactly the action the step names. `invite without a note`: choose send without a note and never add one. `invite with note`: the note is the step's copy, word for word. Confirm the invitation notice, then re-read the profile: it must show Pending. That is the verify.
5. Profile visit: open the profile, wait, scroll once, close. The visit itself is the action; the marker records it. A dry run never visits.
6. Message: only to a 1st-degree connection. Type the text as the adapter says (a new line inside a message must not send it; plain Return can send a partial message). Compare the compose box with the text before sending. Take a new screenshot before clicking Send, because the box grows and the button moves. Verify by reading the sent message back from the open thread, paragraph by paragraph, and checking the compose box is empty.
7. Stop all LinkedIn work at once on a weekly invitation limit, a restriction notice, a login page, a CAPTCHA or any warning. Report it as BLOCKED.

Close every tab this run opened at the end of the run.

## Dry run

Do steps 1 and 2 for each due step and print the contact, the step, the channel and the exact final text (or the gap). For LinkedIn steps that need the profile state, print "profile state read at send time". Never send, never open a profile, never write a marker, Status or log line.
