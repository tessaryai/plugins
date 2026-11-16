# Copy

campaign-run sends the copy exactly as written. Write it as the final message, not as a draft for someone to polish.

## Voice

1. Follow the voice file (the `voice` path printed by `config.py paths`) in this order of weight: the sample messages (copy their rhythm, not their words), then Never use, then Shape, then Tone.
2. If the session has the user's own writing-voice skill (SKILL.md step 2.2), draft with it as well. Where it disagrees with the voice file, the voice file wins. Check every draft against the voice file's Never use list.
3. Without a voice file, write plain and short: peer to peer, one specific observation, one question, one low-effort ask, and no sign-off. Say in the report that no voice file was used.
4. Write as the user (`owner.name`), in the first person. Never claim a customer, a result, a number or a feature the user did not state in the voice file, the ICP or this conversation.

## Length and shape

Unless the voice file says otherwise:

| Step type | Length |
|---|---|
| LinkedIn invite note (only when the action is `invite with note`) | short, one or two sentences. LinkedIn's note limit differs by account type and changes over time; tell the user to check it against the counter in the invite dialog. campaign-run skips a note that does not fit. |
| LinkedIn message | under 60 words |
| First email | under 90 words, subject under 6 words |
| Follow-up email or message | under 50 words |

- One idea per message. One question or one ask, not both stacked.
- Plain text. No bold, no bullet lists, no emoji, no HTML, no Markdown inside the code block.
- Short paragraphs with a blank line between them. campaign-run keeps the line breaks exactly.
- Sign-off: use the voice file's `Sign-off:` line exactly; a ` / ` in it is a line break. A sign-off written as a block of lines (older voice files) is used as is. Email copy includes it, because campaign-run sends without an added signature. If the voice file has no sign-off (the section is empty, says `none`, or is still in angle brackets), use none, never invent one, and say so in the report.

## Links

No links in copy unless the user asks. A link in an email forces campaign-run onto the browser path (the email connector rewrites links), which is slower and more fragile. When the user asks for a link, put it in the copy as a full `https://` URL, and tell them which steps now use the browser path.

## Merge fields

Campaign-page copy may use only these placeholders, filled from each contact's `Run fields:` line:

| Field | Value source |
|---|---|
| `{{first_name}}` | `Source fields:` line from campaign-build, else the provider record, else ask the user. Never parsed from the Name property. |
| `{{company}}` | `Source fields:` line, else the company page name as the user would write it (drop legal suffixes such as Inc or Ltd). |
| `{{role}}` | `Source fields:` title, shortened to how a person would say it. |
| `{{subject_<n>}}` | The subject written for step n on the contact page, for a follow-up in the same thread. |

- Add another field only when the user asks, and only when every contact can have a sourced value.
- Values cannot contain `;`. Rephrase or leave the field out.
- A placeholder without a value makes campaign-run skip that contact and step. Prefer copy that needs only `{{first_name}}`.
- Per-contact copy on a contact page is final text with no placeholders.

## Quality check before showing a draft

- Reads as the user, not as a template. No "I hope this finds you well", no "quick question", no hype words, nothing on the voice file's Never use list.
- Every specific claim about the contact is in the contact's sources (`personalize.md`).
- No link unless asked. No attachment references. No promise of a meeting time.
- Counts within the length limits.
- The subject and the body agree.
