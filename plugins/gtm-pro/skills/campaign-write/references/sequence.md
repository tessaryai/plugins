# Sequence

The sequence lives on the campaign page in the format of `${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`. This file gives the default and the rules for fitting it.

## Header lines

Header lines are paragraphs before the first step heading, one `Label: value` per paragraph, with a blank line between lines (`page-writes.md`):

```
Campaign key: <slug>

Audience: <one sentence>

Sender email: <address>

LinkedIn daily invite cap: <n>

Email daily cap: <n>

Approval: all contacts
```

- `Campaign key:` and `Audience:` are usually written by `/gtm-pro:campaign-build`. Append only the lines that are missing.
- Campaign key rules: lower case letters, digits and hyphens, at most 24 characters, unique across campaigns. Never change a key after the first send.
- `Sender email:` defaults to `sending.sender_email`. Include it whenever the sequence has an email step.
- Caps: propose `sending.linkedin_daily_invite_cap` and `sending.email_daily_cap` or lower. A higher page value does not raise the global cap. Above 20 LinkedIn invites a day, repeat the account-risk warning from `${CLAUDE_PLUGIN_ROOT}/reference/safety.md`.
- `Approval: all contacts` (default): the Active switch approves every step for every contact. `Approval: per contact`: campaign-run sends a step to a contact only when the user has added `Approved: <campaign_key> S<n>` or `Approved: <campaign_key> all` to that contact page. This skill never writes `Approved:` lines.
- Never write `Runs: external`.

## Trigger forms campaign-run accepts

| Form | Meaning |
|---|---|
| `day <n>` | n days after the contact's day 0 (the date of the contact's first marker in this campaign). |
| `<n> days after step <m>` | n days after the marker of step m. Use it only when step m is on the same channel. |
| `on accept, within <n> days` | After a `LinkedIn connection accepted` line appears on the contact page. |
| `on reply`, `on meeting booked` | Never use. A reply stops the contact and a booked meeting moves Status to Discovery, so such a step can never send. |

Each step has exactly one channel. To touch both channels at the same point, use two steps with two numbers. A step on email that should follow a LinkedIn step uses `day <n>`, not `<n> days after step <m>`.

Conditions: `no reply`, `not connected`, `connected`, `connected, no reply`, `no reply, not accepted`. Actions (LinkedIn only): `invite without a note`, `invite with note`, `profile visit`, `message`.

## Default sequence (Mixed)

Use this when the campaign is Mixed and most contacts have both a LinkedIn URL and an email. Explain each step in one line when you propose it.

| Step | Name | Channel | Action | Trigger | Condition | Copy source | Subject / Thread |
|---|---|---|---|---|---|---|---|
| 1 | LinkedIn invite | LinkedIn | invite without a note | day 0 | not connected | none | |
| 2 | Profile visit | LinkedIn | profile visit | day 2 | not connected | none | |
| 3 | Message after accept | LinkedIn | message | on accept, within 7 days | connected, no reply | contact page | |
| 4 | First email | email | | day 3 | no reply | contact page | subject on contact page, new thread |
| 5 | Email follow-up | email | | 4 days after step 4 | no reply | this page | `Re: <step 4 subject>`, reply to step 4 |
| 6 | LinkedIn follow-up | LinkedIn | message | 5 days after step 3 | connected, no reply | this page | |

Step 6 counts from step 3 (both LinkedIn), so it never fires right after a late accept message. If step 3 lapses (no accept within 7 days), step 6 never becomes due, because its condition needs a connection.

Why this shape: an invite without a note is accepted more often and spends no copy; the visit is a light second touch; the first real message and the first email carry the personal hook, so they live on each contact page; follow-ups are short and generic, so they live on the campaign page with `{{first_name}}` only.

Variants:

- LinkedIn only: steps 1, 2, 3, 6 of the default, renumbered 1 to 4. The follow-up becomes `5 days after step 3`.
- Email only: steps 4 and 5 of the default, renumbered 1 and 2: step 1 `day 0`, step 2 `4 days after step 1`, thread `reply to step 1`, and an optional step 3 on email `5 days after step 2`, thread `reply to step 1`.
- Always renumber steps from 1 with no gaps, and update every `step <m>` reference, `Thread:` line and `subject_<n>` field to the new numbers.
- Few contacts with LinkedIn URLs: say so; campaign-run writes a skip marker for them and goes on with email.

## How the steps look on the page

Write each step as in `${CLAUDE_PLUGIN_ROOT}/reference/campaign-page.md`: a blank line between the heading and every label line, and the copy fence labelled `plain text`. Example for steps 3 and 5:

````
## Step 3 — Message after accept

Trigger: on accept, within 7 days

Channel: LinkedIn

Action: message

Condition: connected, no reply

Copy source: contact page

## Step 5 — Email follow-up

Trigger: 4 days after step 4

Channel: email

Condition: no reply

Subject: Re: {{subject_4}}

Thread: reply to step 4

Copy source: this page

```plain text
Hi {{first_name}}, ...
```
````

When step 4's subject is per contact, step 5's subject must be per contact too. Either put `subject_4` in each contact's `Run fields:` line (as above), or make step 5's copy source `contact page` with its own `Subject:` line. Choose the first when the follow-up body is the same for everyone.

Steps without copy (invite without a note, profile visit) have no `Copy source:` line and no code block.
