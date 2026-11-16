# Configuration

## Edition

This is Tessary GTM, the directory edition. It has no scripts: there is no `lib/` folder and nothing to run with Python. Every skill always takes the No Python path below and the connectors-only rules of Runtime: cowork, in Claude Code and in Cowork alike. Read and write `config.json` and `state.json` with the Read and Write tools. The config format is the same as in Tessary GTM Pro, so a config written by either edition works in the other. Limits of this edition and the upgrade message: `${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`.

All runtime files live in one config folder outside the plugin folder, because a plugin update replaces that folder. Every path below lives in the active folder, including the imports folder and the default voice and ICP files. Never hardcode a runtime path: find the active folder as Which folder is active says, and use the files in it (`config.json`, `state.json`, `logs.md`, `imports/`, `voice.md`, `icp.md`; `paths.voice` and `paths.icp` can move the last two).

## Which folder is active

The first match wins, in this order (the folder command in No Python, step 1, does it in one line):

1. `GTM_CONFIG_DIR`, when the environment variable is set (a second workspace, a scheduled run pointed at a project folder).
2. A `.gtm/` folder that holds `config.json`, in the current working directory or any parent. Setup creates `./.gtm/` in the project folder with `config.json` from the template and a `.gtm/.gitignore` that holds the line `credentials.json`.
3. `~/.config/gtm`.

A `.gtm/` folder without `config.json` is ignored. Discovery starts from the shell's current folder. In Cowork that may not be the connected project folder: in every preflight, run the folder command with `cd <project folder> &&` in front, and check that the folder it prints is the one you expect.

| File | Holds | Who writes it |
|---|---|---|
| `config.json` | Settings below. No secrets. | `/gtm:setup`, the user |
| `credentials.json` | Notion token and API keys of Tessary GTM Pro. This edition never reads, writes or creates it. | Tessary GTM Pro only |
| `state.json` | Per-adapter cursors, the import progress (`import`) and the funnel baseline (`funnel`). | sweep, import and funnel, with the Read and Write tools (No Python, step 6). campaign-run keeps no state here. |
| `imports/<run_id>/` | Work files of one import (contacts.csv, raw/, mapping.json, status_table.json, keys.json, plan.json, done.jsonl). They hold contact data, never a key. They live here, not in the session scratchpad, so `/gtm:import resume` works in a later session. | `/gtm:import` |
| `logs.md` | Run log, one entry per run. | every skill (`${CLAUDE_PLUGIN_ROOT}/reference/run-log.md`) |
| `voice.md` | The user's writing voice. | setup, campaign-write |
| `icp.md` | The ideal customer profile. | setup, campaign-build |

Templates: `${CLAUDE_PLUGIN_ROOT}/templates/config.example.json`, `voice.example.md`, `icp.example.md`, `schema.json`.

## Secrets

This edition has no keys. Never Read, Write or create `credentials.json`, never `cat` it, and never offer to save a key. Treat every secret as not set. Never ask the user to paste a key into the chat. A tool that needs a key and has no connector is blocked, with the upgrade message as its fix (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`).

## Keys

Types: str, int, bool, list, map. "Read by" lists the skills that use the key; every skill reads `notion.*`.

### runtime

| Key | Type | Default | Read by | Meaning |
|---|---|---|---|---|
| `runtime` | `"claude-code"` or `"cowork"` | `"claude-code"` | all | Where the skills run. `cowork` means connectors only (Runtime: cowork, below). |

### owner

| Key | Type | Default | Read by | Meaning |
|---|---|---|---|---|
| `owner.name` | str | `""` | campaign-write, campaign-run | The user's name, for sign-offs and reports. |
| `owner.emails` | list of str | `[]` | sweep, campaign-run | Every address the user sends from. Mail from these is outbound. Required. |
| `owner.own_domains` | list of str | `[]` | sweep | Domains that are the user's own. Calendar attendees on them are not external. |
| `owner.timezone` | str (IANA) | `"UTC"` | sweep, campaign-run, funnel | Time zone for "today", weekends and the send window. |
| `owner.working_days` | list of `Mon`..`Sun` | `["Mon","Tue","Wed","Thu","Fri"]` | campaign-run | Days campaign-run may send. A step due on another day goes out on the next working day. |
| `owner.send_window` | map `{start, end}` HH:MM | `{"start":"09:00","end":"17:00"}` | campaign-run | Local hours in which sends may happen. Outside it, campaign-run sends nothing and says so. |

### notion

| Key | Type | Default | Read by | Meaning |
|---|---|---|---|---|
| `notion.access` | `"mcp"` or `"rest"` | `"mcp"` | all | Tessary GTM Pro writes `rest` when a Notion token is saved. This edition always uses MCP: it reads `rest` as `mcp` and leaves the value as it is. See `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`. |
| `notion.parent_page_id` | str | `""` | setup | The page that holds the five databases and the Funnel page. Must hold a 32-hex Notion id (dashes optional, a URL is accepted). |
| `notion.data_sources.contacts` / `companies` / `pipeline` / `campaigns` / `meetings` | str | `""` | all | Data source ids (not page ids, not database ids). Each must be a 32-hex Notion id, dashes optional. |
| `notion.views.contacts` / `companies` / `pipeline` / `campaigns` / `meetings` | str | `""` | all (MCP path) | URL of one unfiltered saved view per database. Both forms are accepted: `view://<view id>` (the form `notion-fetch` on a database returns, which the query tool accepts as `view_url`) or a database view link (`<database link>?v=<view id>`). Setup records the `view://` form. MCP reads every row through it in view mode, which has no plan quota. Setup records it by fetching the database (`${CLAUDE_PLUGIN_ROOT}/skills/setup/references/databases.md`). Empty: skills find a view for the run and ask you to rerun setup; `check` warns when `notion.access` is `mcp`. See `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows. |
| `notion.field_map.<database>.<logical_field>` | map | from `templates/schema.json` | all | Actual property name for each logical field. |
| `notion.status_map.<logical_status>` | map | identity | all | Actual Status option for `New`, `Contacted`, `Responded`, `Discovery`, `Lead`, `Archived`, `Do Not Contact`, `Disqualified`. |
| `notion.option_map.<database>.<logical_field>.<logical_option>` | map | identity, from schema | all | Actual option names for other select fields: `contacts.email_status`, `contacts.lead_source`, `contacts.designation`, `companies.icp`, `companies.vertical`, `pipeline.stage`, `pipeline.likelihood`, `campaigns.status`, `campaigns.type`, `meetings.source`. |
| `notion.select_payload` | map with flat keys `"<database>.<logical_field>"` → `"select"` or `"status"` | `{}` (all select) | all | Set only when a mapped workspace uses a real Notion status property for a field, for example `{"contacts.status": "status"}`. The key is one flat string, not a nested path: in config.json it reads `"select_payload": {"contacts.status": "status"}` inside `notion`, never a nested `contacts` object. |
| `notion.funnel_page_id` | str | `""` | funnel | The page the funnel report replaces. |

Logical field names per database (the keys of `field_map`):

- contacts: `name`, `email`, `linkedin`, `phone`, `location`, `status`, `do_not_contact`, `dnc_reason`, `dnc_set_on`, `email_status`, `first_contacted`, `lead_source`, `designation`, `notes`, `company`, `campaign`, `deal`, `meetings`
- companies: `name`, `website`, `linkedin`, `description`, `employees`, `headquarters`, `icp`, `icp_notes`, `vertical`, `contacts`, `deals`
- pipeline: `name`, `stage`, `company`, `contacts`, `value`, `expected_close`, `next_steps`, `likelihood`
- campaigns: `name`, `status`, `type`, `start_date`, `end_date`, `notes`, `contacts`
- meetings: `name`, `date`, `contacts`, `recording_url`, `summary`, `source`

When the user maps an existing workspace that lacks a field, setup either adds the property (with the user's agreement) or leaves the mapping pointing at a property that does not exist; skills then skip writes to that field and report it once under Needs you.

### adapters

| Key | Type | Default | Read by | Allowed values |
|---|---|---|---|---|
| `adapters.email` | str or null | `"gmail"` | sweep, campaign-run | `gmail`, `outlook`, or null/`none` |
| `adapters.calendar` | str or null | `"google"` | sweep | `google`, `outlook`, or null/`none` |
| `adapters.linkedin` | str or null | `"chrome"` | sweep, campaign-run, campaign-build, campaign-write | `chrome` (Claude in Chrome), or null/`none` |
| `adapters.meetings` | list | `[]` | sweep | `fathom`, `granola`, `fireflies`, `otter` |
| `adapters.outreach` | list | `[]` | sweep | `gojiberry`, `lemlist`, `instantly`, `apollo` (read-only mirrors) |
| `adapters.enrichment` | list | `[]` | campaign-build | `exa`, `apollo`, `hunter`, `mcp` |
| `adapters.notify.kind` | str | `"push"` | all | `push` (PushNotification), `slack`, `none` |
| `adapters.notify.slack_channel` | str | `""` | all | Channel name or id, required when kind is `slack` |

Each value names an adapter file `${CLAUDE_PLUGIN_ROOT}/adapters/<kind>/<tool>.md`. See `${CLAUDE_PLUGIN_ROOT}/adapters/README.md`. Import sources (`csv`, `hubspot`, `pipedrive`, `attio`) are chosen per run by `/gtm:import`, not stored here.

### sending

| Key | Type | Default | Read by | Meaning |
|---|---|---|---|---|
| `sending.mode` | `"live"` or `"dry-run"` | `"live"` | campaign-run | `live` sends with all gates. `dry-run` sends nothing and writes nothing. A `dry-run` argument on any run overrides `live`. |
| `sending.sender_email` | str | `""` | campaign-run | The From address campaign-run expects. A sent message from another address stops sending and is reported as BLOCKED. A campaign page line `Sender email:` overrides it for that campaign. |
| `sending.linkedin_daily_invite_cap` | int | `10` | campaign-run | Most LinkedIn invites per day across all campaigns. A campaign page line can set a lower cap for that campaign, never a higher total. |
| `sending.email_daily_cap` | int | `40` | campaign-run | Most campaign emails per day across all campaigns. |
| `sending.reply_lookback_days` | int | `30` | campaign-run | How far back the reply check reads email and LinkedIn when a campaign has no earlier step dates. |
| `sending.event_window_days` | int | `14` | campaign-run | Default window for an event step (for example "on accept") when the campaign page states none. |

### sweep

| Key | Type | Default | Read by | Meaning |
|---|---|---|---|---|
| `sweep.first_run_lookback_days` | int | `7` | sweep | Days to look back for an adapter with no cursor, outreach tools included. A first outreach mirror reads only this far back unless the user asks for full history in that run (a full-history mirror can create hundreds of pages, so the sweep asks first). |
| `sweep.max_meeting_attendees` | int | `15` | sweep | A calendar event with more external attendees than this is skipped (a webinar, an all-hands, a conference block). |
| `sweep.calendar_lookahead_days` | int | `7` | sweep | Days ahead the calendar check reads for booked meetings. |
| `sweep.exclude_labels` | list | `[]` | sweep, setup | Gmail label names (display names, not ids) whose mail the sweep and the voice profile skip, for example a mailbox warm-up label. Setup asks for them. The Gmail queries add `-label:"<name>"` for each. |

### funnel

| Key | Type | Default | Read by | Meaning |
|---|---|---|---|---|
| `funnel.start_month` | `YYYY-MM` or null | `null` | funnel | First month in the tables. Null means the month of the earliest First Contacted date. |
| `funnel.pilot_stages` | list | `["Pilot"]` | funnel | Logical pipeline stages that count as Pilot / Trial. |
| `funnel.customer_stages` | list | `["Won"]` | funnel | Logical pipeline stages that count as Customer. Customer stages also count as Pilot / Trial. |
| `funnel.warm_lead_sources` | list | `["Warm Intro"]` | funnel | Logical Lead Source options that put a contact in the warm table. |
| `funnel.inbound_lead_sources` | list | `["Inbound"]` | funnel | Logical Lead Source options left out of both outbound tables. All other contacts, also those with a blank Lead Source, are cold. |
| `funnel.drop_tolerance_pct` | number | `0` | funnel | A past-month count that falls by more than this percent against the baseline fails the checks. `0` means any drop fails. |
| `funnel.rise_tolerance_pct` | number or null | `25` | funnel | A past-month count that rises by more than this percent fails the checks. Null turns the rise check off. |
| `funnel.max_blank_pct` | number | `10` | funnel | The checks fail when more than this percent of counted contacts (and at least 3) have a blank First Contacted. |
| `funnel.inbound` | list | `[]` | funnel | Inbound adapters that write a metrics file for the optional Inbound table. No inbound adapter ships in v1; see `${CLAUDE_PLUGIN_ROOT}/skills/funnel/references/definitions.md`, Inbound hook. |

Option names in `pilot_stages`, `customer_stages`, `warm_lead_sources` and `inbound_lead_sources` are logical; the funnel maps them through `notion.option_map` (`pipeline.stage`, `contacts.lead_source`). A name with no map entry is used as the actual option name, and the run report says so.

The funnel baseline (the last accepted counts) is stored in `state.json` under `adapters.funnel`. Only the funnel skill writes it, in the shape `${CLAUDE_PLUGIN_ROOT}/skills/funnel/SKILL.md` gives, which Tessary GTM Pro also reads.

### paths

| Key | Type | Default | Read by |
|---|---|---|---|
| `paths.voice` | str | `""` (means `<config dir>/voice.md`) | setup, campaign-write |
| `paths.icp` | str | `""` (means `<config dir>/icp.md`) | setup, campaign-build, campaign-write |

An empty path follows the active config folder. Set a path only to keep the file somewhere else; `~` is expanded.

## Runtime: cowork

Claude Cowork runs shell commands in a virtual machine whose network reaches only Anthropic hosts by default, has no terminal for the user, and may not keep files in its home folder between sessions. This edition follows the rules below in Cowork and in Claude Code alike, whatever `runtime` says:

- Notion goes through the Notion connector only.
- Never call a vendor API with curl or a script. An adapter that has no connector in the session is blocked (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`, Cowork). When the tool would need an API key, the fix is the upgrade message (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`).
- No key is saved anywhere.
- In Cowork, keep the config in the connected project folder (`.gtm/`). Warn when the config is in the home folder.
- Setup sets `runtime` to `cowork` in Cowork and to `claude-code` otherwise, so that Tessary GTM Pro reads the same config correctly after a switch.

## No Python

This edition has no scripts, so every skill always runs this way, in Claude Code and in Cowork. Never run `python3` for a gtm task, even when it is installed:

1. Find the folder by hand, in the same order: `GTM_CONFIG_DIR` if set, else the nearest `.gtm/config.json` from the project folder upward, else `~/.config/gtm`. One shell command does it:
   `if [ -n "$GTM_CONFIG_DIR" ]; then echo "$GTM_CONFIG_DIR"; else d="$PWD"; while :; do if [ -f "$d/.gtm/config.json" ]; then echo "$d/.gtm"; break; fi; if [ "$d" = "/" ]; then echo "$HOME/.config/gtm"; break; fi; d=$(dirname "$d"); done; fi`
   Run it from the project folder (`cd <project folder> &&` in front).
2. Read `config.json` and `state.json` with the Read tool. Fill a missing key from `${CLAUDE_PLUGIN_ROOT}/templates/config.example.json` and the defaults in this file.
3. To change a value, Read the file, change only that key, and Write the whole file back as valid JSON with two-space indent. Never write a secret-like key. Never Read, Write or create `credentials.json`: this edition has no keys, so treat every secret as not set and `notion.access` as `mcp`. A `rest` value that Tessary GTM Pro wrote stays as it is.
4. Setup without Python: Write `.gtm/config.json` from the template and Write `.gtm/.gitignore` with the line `credentials.json`.
5. Before you use the config, check it by hand. Stop on any of these:
   - `owner.emails` empty, or any address, `owner.own_domains` entry or `sending.sender_email` on `example.com`, `example.org` or `example.net`; `owner.name` is `Your Name`.
   - `owner.timezone` is not an IANA name (see Time zone by hand, below the list); `owner.working_days` is empty or holds a value other than `Mon`..`Sun`; `owner.send_window` is not `HH:MM` to `HH:MM` with start before end.
   - `notion.parent_page_id` or a `notion.data_sources.*` value has no 32-hex id, or is all zeros (a placeholder).
   - `notion.status_map` lacks one of the eight statuses, or two statuses share one option.
   - `notion.access` is not `mcp` or `rest` (this edition reads `rest` as `mcp`); `runtime` is not `claude-code` or `cowork`.
   - A `notion.select_payload` value is an object (nested), or is not `select` or `status`.
   - `sending.mode` is not `live` or `dry-run`; a cap or day count in `sending.*` or `sweep.*` is not a whole number of 0 or more.
   - A `notion.field_map.*.*` value is empty or not a string (the skills could not find a property such as Do Not Contact or Status).
   - An `adapters.*` value names a tool not listed in the adapters table above; `adapters.meetings`, `adapters.outreach` or `adapters.enrichment` is not a list; `adapters.notify.kind` is not `push`, `slack` or `none`, or is `slack` with an empty `slack_channel`.
   - `sweep.exclude_labels` is not a list of non-empty names.
   - `funnel.start_month` is not `YYYY-MM` or null; `funnel.pilot_stages`, `customer_stages`, `warm_lead_sources`, `inbound_lead_sources` or `inbound` is not a list of non-empty names; `funnel.customer_stages` is empty; `funnel.drop_tolerance_pct` or `max_blank_pct` is not a number of 0 or more; `funnel.rise_tolerance_pct` is not null or a number of 0 or more.
   - Any key in config.json looks like a secret (its name holds `token`, `secret`, `password` or `api_key`).
   Time zone by hand: the name is `UTC`, or `Area/City` (one or two `/`, no spaces) with Area one of `Africa`, `America`, `Antarctica`, `Asia`, `Atlantic`, `Australia`, `Europe`, `Indian`, `Pacific`. If `test -f /usr/share/zoneinfo/<name>` works in this shell, it decides. Otherwise, when the form is right, confirm the name with the user once in setup and accept it, and record that in the run log; later runs accept a name of the right form.
   For every other rule, if you cannot tell whether it holds, treat it as failed and stop. This hand check is the config check of this edition (Tessary GTM Pro runs the same rules with a script); it does not replace any safety gate.
6. State: `state.json` is `{"version": 1, "adapters": {...}}`. Replace only the one adapter key you move, at the point where the skill says to write that cursor. Read the file again just before you write it, and keep every other key as it is.
7. Run log: append the entry to `logs.md` in the active folder (Read, add the entry at the end, Write).
8. `/gtm:import` takes a CSV of about 200 rows or fewer, or a HubSpot, Pipedrive or Attio import of about 200 contacts or fewer through that tool's connector. Map the columns yourself, show the mapping and a preview of the first rows, dedupe by email, LinkedIn URL and Source ID against the view-mode index, and write in batches of 20 with a yes before the first batch and a check after each one. A larger import, or a CRM with no connector in the session, needs Tessary GTM Pro (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`); a CSV export of 200 rows or fewer still works here.
9. `/gtm:funnel` counts by hand only when there are about 150 counted contacts or fewer, and publishes only when a second, independent count gives the same numbers (`${CLAUDE_PLUGIN_ROOT}/skills/funnel/SKILL.md`). Above that it reports `BLOCKED` and shows the upgrade message (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`).
10. Every safety gate applies unchanged in this edition: Do Not Contact, reply stop, verify before marker, forward-only Status, the daily caps and the send window (`${CLAUDE_PLUGIN_ROOT}/reference/safety.md` and `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`). A missing script is never a reason to skip or weaken one. When a gate cannot be checked, do not send or write that item; list it under Needs you.

## Validation

This edition checks the config by hand, with the rules in No Python, step 5. Tessary GTM Pro runs the same rules with a script. Warn (and go on) when a `notion.views.*` value is empty, `notion.funnel_page_id` is empty, `owner.own_domains` is empty, the voice or ICP file does not exist yet, or, in Cowork, the config is in the home folder.

## state.json

```json
{
  "version": 1,
  "adapters": {
    "gmail": {"after": "2026-03-01", "updated": "2026-03-02T08:00:00Z"},
    "google-calendar": {"after": "2026-03-01"},
    "linkedin-connections": {"top_profile": "https://www.linkedin.com/in/someone/"},
    "linkedin-messages": {"newest": "2026-03-01T17:20-05:00"},
    "gojiberry": {"log_cursors": {"<campaign id>": 1234}},
    "fathom": {"after": "2026-03-01T00:00:00Z"}
  }
}
```

- Two keys are not adapter cursors: `import` (written by `/gtm:import`: `{run_id, source, folder, phase, written, updated}`) and `funnel` (the funnel baseline, written only by the funnel skill). No adapter may use these names.
- Keys under `adapters` are free-form per adapter; each adapter file defines its own cursor shape in its Cursor section.
- A cursor that holds a time (not a date) is ISO 8601 with an explicit offset, for example `2026-11-16T12:33-05:00` or `2026-11-16T07:03Z`. Never store a local time without an offset.
- When an outreach adapter is incomplete, the email and LinkedIn message cursors do not move past the earliest unmirrored event date (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/batch.md`, Cursors).
- A missing or null cursor means no earlier run: look back `sweep.first_run_lookback_days` days. Dedupe makes a repeat safe.
- Move a cursor only when that adapter read everything back to its old cursor in this run. A blocked or incomplete adapter keeps its old cursor, so the next run retries the same period.
- Write cursors into `state.json` (No Python, step 6) at the end of the run, after the CRM writes are verified.

## logs.md

`logs.md` in the active config folder, newest entry last. One entry per run. Format per skill: `${CLAUDE_PLUGIN_ROOT}/reference/run-log.md`.
