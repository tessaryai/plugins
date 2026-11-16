# Questions and config keys

Setup step 2 and step 5. Ask in at most two `AskUserQuestion` rounds, then a few plain follow-ups for free text (names, addresses). Pre-select what step 1 found. On a re-run, the current config value is the default.

## Round 1: what you have

| Question | Options | Default | Goes to |
|---|---|---|---|
| Where is your CRM today? | None / Spreadsheet or CSV / HubSpot / Pipedrive / Attio / Salesforce or Airtable (CSV export) / Other (CSV export) | None | step 8 import offer |
| CRM databases in Notion? | Create new ones / Map my existing databases | Create new | step 4 |
| Email | Gmail / Outlook / None | the one found | `adapters.email` |
| Calendar | Google / Outlook / None | the one found | `adapters.calendar` |
| Meeting recorders (multi-select) | Fathom / Granola / Fireflies / Otter / None | the ones found | `adapters.meetings` |

## Round 2: how you work

| Question | Options | Default | Goes to |
|---|---|---|---|
| Outreach tools to mirror into the CRM (multi-select, read-only) | Gojiberry / lemlist / Instantly / Apollo / None | the ones found | `adapters.outreach` |
| Enrichment sources (multi-select) | Exa / Apollo / Hunter / another enrichment connector in this session (`mcp`) / None | the ones found | `adapters.enrichment` |
| Notifications when something is blocked | Push notification / Slack channel / None | Push | `adapters.notify.kind` |
| Working days | Mon-Fri / Mon-Sat / Sun-Thu / Other | Mon-Fri | `owner.working_days` |

## Free-text follow-ups

Ask in one message, with your best guesses filled in (for example the connected email account and the system time zone from `date +%Z` plus the user's confirmation):

- Your name (for sign-offs and reports).
- Every address you send from. Your own domains.
- Sender email for campaigns (must be one of your addresses).
- Time zone as an IANA name (for example `America/New_York`, `Europe/Berlin`). If the user gives an abbreviation, propose the IANA name and confirm.
- Send window (default 09:00 to 17:00 local).
- Slack channel, when notify is Slack.
- Email: do you use a mailbox warm-up or sequencer tool that labels its mail in Gmail? If yes, the label name as shown in Gmail (you may list the labels with the read-only `list_labels` tool to propose it). Goes to `sweep.exclude_labels`.

## Config keys

Write each into config.json with the Read and Write tools (`${CLAUDE_PLUGIN_ROOT}/reference/config.md`, No Python, step 3): the dotted key is the path in the JSON object (`owner.name` is `"name"` inside `"owner"`). The example values below are the JSON values, shown in single quotes.

| Key | Example value |
|---|---|
| `runtime` | `cowork` in Cowork; leave the default `claude-code` otherwise (step 0) |
| `owner.name` | `'"Ada Lovelace"'` |
| `owner.emails` | `'["ada@acme.example"]'` |
| `owner.own_domains` | `'["acme.example"]'` |
| `owner.timezone` | `Europe/London` |
| `owner.working_days` | `'["Mon","Tue","Wed","Thu","Fri"]'` |
| `owner.send_window` | `'{"start":"09:00","end":"17:00"}'` |
| `notion.access` | `mcp` (this edition never writes `rest`; keep a `rest` that Tessary GTM Pro wrote) |
| `notion.parent_page_id` | page id |
| `notion.data_sources` | `'{"contacts":"<id>","companies":"<id>","pipeline":"<id>","campaigns":"<id>","meetings":"<id>"}'` |
| `notion.field_map` | the full map from step 4 (all five databases) |
| `notion.status_map` | all eight logical statuses |
| `notion.option_map` | the full map from step 4 |
| `notion.select_payload` | `'{}'`, or `'{"contacts.status":"status"}'` when that property is a real Notion status property. Flat keys, never a nested object. |
| `notion.funnel_page_id` | page id |
| `adapters.email` / `adapters.calendar` / `adapters.linkedin` | `gmail`, `outlook`, `google`, `chrome`, or `null` |
| `adapters.meetings` / `adapters.outreach` / `adapters.enrichment` | JSON list, `'[]'` when none |
| `adapters.notify` | `'{"kind":"push","slack_channel":""}'` |
| `sending.mode` | `live` (default) or `dry-run` |
| `sending.sender_email` | address |
| `sending.linkedin_daily_invite_cap` | `10` |
| `sending.email_daily_cap` | `40` |
| `sweep.exclude_labels` | `'["Warmup"]'`, or `'[]'` when the user has no warm-up or sequencer label |
| `paths.voice` / `paths.icp` | keep the default `""` (the voice and ICP files in the config folder) |

The rest (`sending.reply_lookback_days`, `sending.event_window_days`, `sweep.*`, `funnel.*`) keep their defaults unless the user asks. Their meaning is in `${CLAUDE_PLUGIN_ROOT}/reference/config.md`.

Never put a secret in config.json: no key whose name holds `token`, `secret`, `password` or `api_key`.

## Re-run diff

Before any `set` on a re-run, show:

```
owner.timezone: "UTC" → "Europe/London"
adapters.meetings: [] → ["fathom"]
sending.linkedin_daily_invite_cap: 10 → 15
```

Then ask one yes or no. Set only the keys the user accepted.
