# Configuration

All runtime files live in one config folder outside the plugin folder, because a plugin update replaces that folder. Every path below lives in the active folder, including the imports folder and the default voice and ICP files. Never hardcode a runtime path: run `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py paths` and use the location it prints (keys `config`, `credentials`, `state`, `run_log`, `imports`, `voice`, `icp`).

## Which folder is active

`config.py` picks the first match:

1. `GTM_CONFIG_DIR`, when the environment variable is set (tests, a second workspace, a scheduled run pointed at a project folder). `paths` prints `"source": "env"`.
2. A `.gtm/` folder that holds `config.json`, in the current working directory or any parent. `paths` prints `"source": "project"`. `config.py init --project` creates `./.gtm/` in the current folder, writes `config.json` from the template, and writes `.gtm/.gitignore`, which keeps `credentials.json` out of git.
3. `~/.config/gtm`. `paths` prints `"source": "home"`.

`paths` also prints `dir` (the active folder), `reason` (why it was chosen) and `runtime`. Discovery starts from the shell's current folder. In Cowork that may not be the connected project folder: in every preflight, check `source` and `dir`, and when they are not the project folder you expect, run the command again with `cd <project folder> &&` in front, or with `GTM_CONFIG_DIR=<project folder>/.gtm` set in the same command. A `.gtm/` folder without `config.json` is ignored.

| File (`paths` key) | Holds | Who writes it |
|---|---|---|
| `config.json` (`config`) | Settings below. No secrets. | `/gtm:setup`, `config.py set`, the user |
| `credentials.json` (`credentials`) | Notion token and API keys. Mode 600. | `config.py set-secret` only |
| `state.json` (`state`) | Per-adapter cursors, the import progress (`import`) and the funnel baseline (`funnel`). | sweep and import through `config.py state-set`; `lib/funnel.py` for its baseline. campaign-run keeps no state here. |
| `imports/<run_id>/` (`imports`) | Work files of one import (contacts.csv, raw/, mapping.json, status_table.json, keys.json, plan.json, done.jsonl). They hold contact data, never a key. They live here, not in the session scratchpad, so `/gtm:import resume` works in a later session. | `/gtm:import` |
| `logs.md` (`run_log`) | Run log, one entry per run. | every skill (`${CLAUDE_PLUGIN_ROOT}/reference/run-log.md`) |
| `voice.md` (`voice`) | The user's writing voice. | setup, campaign-write |
| `icp.md` (`icp`) | The ideal customer profile. | setup, campaign-build |

Templates: `${CLAUDE_PLUGIN_ROOT}/templates/config.example.json`, `voice.example.md`, `icp.example.md`, `schema.json`.

## The config CLI

Run as `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py <command>`:

| Command | Does |
|---|---|
| `show` | Prints the config with defaults filled in, secret-like values masked, the list of saved secret names (`_secrets_saved`) and the file locations. |
| `check` | Validates. Prints `error:` and `warning:` lines, then `ok` or the error count. Exit 0 ok, 1 errors. See Validation below. |
| `get <dotted.key>` | Prints one value (strings bare, others as JSON). Refuses secret names. |
| `set <dotted.key> <value>` | Writes one value into config.json. The value is parsed as JSON when it can be (`10`, `true`, `["a"]`, `null`), else kept as a string. Refuses secret-like keys. |
| `init` | Writes config.json from the template into the active folder when none exists. |
| `init --project` | Creates `./.gtm/` in the current folder with config.json (from the template, when absent) and a `.gitignore` for `credentials.json`. Prints a note when another folder stays active (`GTM_CONFIG_DIR` is set). |
| `paths` | Prints the active folder (`dir`), `source` (`env`, `project` or `home`), `reason`, `runtime`, and the file locations: config, credentials, state, run log, `imports` (the import work folder), `voice` and `icp` (the resolved files), and whether config exists. |
| `set-secret <name>` | Reads a secret at a hidden prompt and saves it to credentials.json with mode 600. Needs a real terminal: the user runs it, not the agent. Refuses when `runtime` is `cowork`. |
| `has-secret <name>` | Exit 0 when the secret is saved, 1 when not. Prints only `set` or `not set`. With `runtime` = `cowork` it always exits 1 (`not set`), so no skill takes a token path there. |
| `state-get [adapter]` | Prints state.json, or one adapter's cursor. |
| `state-set <adapter> '<json>'` | Replaces one adapter's cursor. |

Secret names: `notion_token`, `gojiberry_api_key`, `lemlist_api_key`, `instantly_api_key`, `apollo_api_key`, `hubspot_token`, `pipedrive_api_token`, `attio_api_key`, `fathom_api_key`, `hunter_api_key`, `fireflies_api_key`. An environment variable `GTM_<NAME>` (for example `GTM_NOTION_TOKEN`) overrides the file. Skills never read credentials.json themselves and never `cat` it.

`set-secret` refuses when there is no terminal. Tell the user to run it in their own terminal (`python3 -I -B <plugin root>/lib/config.py set-secret notion_token`, with the plugin root path filled in). The agent's shell has no terminal, so the agent cannot run it. Never ask the user to paste a key into the chat.

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
| `notion.access` | `"mcp"` or `"rest"` | `"mcp"` | all | `rest` means a token is saved and bulk work uses `lib/notion_rest.py`. See `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`. |
| `notion.parent_page_id` | str | `""` | setup | The page that holds the five databases and the Funnel page. Must hold a 32-hex Notion id (dashes optional, a URL is accepted). |
| `notion.data_sources.contacts` / `companies` / `pipeline` / `campaigns` / `meetings` | str | `""` | all | Data source ids (not page ids, not database ids). Each must be a 32-hex Notion id, dashes optional. |
| `notion.views.contacts` / `companies` / `pipeline` / `campaigns` / `meetings` | str | `""` | all (MCP path) | URL of one unfiltered saved view per database. Both forms are accepted: `view://<view id>` (the form `notion-fetch` on a database returns, which the query tool accepts as `view_url`) or `https://www.notion.so/<database id>?v=<view id>`. Setup records the `view://` form. MCP reads every row through it in view mode, which has no plan quota. Setup records it by fetching the database (`${CLAUDE_PLUGIN_ROOT}/skills/setup/references/databases.md`). Empty: skills find a view for the run and ask you to rerun setup; `check` warns when `notion.access` is `mcp`. See `${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows. |
| `notion.field_map.<database>.<logical_field>` | map | from `templates/schema.json` | all | Actual property name for each logical field. |
| `notion.status_map.<logical_status>` | map | identity | all | Actual Status option for `New`, `Contacted`, `Responded`, `Discovery`, `Lead`, `Archived`, `Do Not Contact`, `Disqualified`. |
| `notion.option_map.<database>.<logical_field>.<logical_option>` | map | identity, from schema | all | Actual option names for other select fields: `contacts.email_status`, `contacts.lead_source`, `contacts.designation`, `companies.icp`, `companies.vertical`, `pipeline.stage`, `pipeline.likelihood`, `campaigns.status`, `campaigns.type`, `meetings.source`. |
| `notion.select_payload` | map with flat keys `"<database>.<logical_field>"` → `"select"` or `"status"` | `{}` (all select) | all | Set only when a mapped workspace uses a real Notion status property for a field, for example `{"contacts.status": "status"}`. The key is one flat string, not a nested path: set it with `config.py set notion.select_payload '{"contacts.status":"status"}'`, never with a dotted key. |
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

Option names in `pilot_stages`, `customer_stages`, `warm_lead_sources` and `inbound_lead_sources` are logical; `lib/funnel.py` maps them through `notion.option_map` (`pipeline.stage`, `contacts.lead_source`). A name with no map entry is used as the actual option name, and the run report says so.

The funnel baseline (the last accepted counts) is stored in `state.json` under `adapters.funnel`. Only `lib/funnel.py` writes it.

### paths

| Key | Type | Default | Read by |
|---|---|---|---|
| `paths.voice` | str | `""` (means `<config dir>/voice.md`) | setup, campaign-write |
| `paths.icp` | str | `""` (means `<config dir>/icp.md`) | setup, campaign-build, campaign-write |

An empty path follows the active config folder. Set a path only to keep the file somewhere else; `~` is expanded. `config.py paths` prints the resolved files.

## Runtime: cowork

Claude Cowork runs shell commands in a virtual machine whose network reaches only Anthropic hosts by default, has no terminal for the user, and may not keep files in its home folder between sessions. With `runtime` = `cowork`:

- Notion goes through the Notion connector only. `notion.access` must be `mcp`; `check` reports an error for `rest`.
- `lib/notion_rest.py` and `lib/readonly_api.py` are never called. Both refuse to run (notion_rest exit 1, readonly_api exit 2) as a second guard.
- An adapter that needs an API key and has no connector in the session is blocked with the fix "connect a connector for <tool>, or run this routine from Claude Code" (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`).
- `set-secret` is never offered, and refuses. No key is saved anywhere.
- Keep the config in the connected project folder (`init --project`). `check` warns when the config is in the home folder.
- The runtime belongs to the config, not the app: a Claude Code run on a config with `runtime` = `cowork` follows the same rules.

## No Python

Some environments (often Cowork) have no `python3`. Test it once per run with the preflight's first command, `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py check`. When it fails with `command not found` (or `python3: not found`), every skill still runs, with these changes:

1. Find the folder by hand, in the same order: `GTM_CONFIG_DIR` if set, else the nearest `.gtm/config.json` from the project folder upward, else `~/.config/gtm`. One shell command does it:
   `if [ -n "$GTM_CONFIG_DIR" ]; then echo "$GTM_CONFIG_DIR"; else d="$PWD"; while :; do if [ -f "$d/.gtm/config.json" ]; then echo "$d/.gtm"; break; fi; if [ "$d" = "/" ]; then echo "$HOME/.config/gtm"; break; fi; d=$(dirname "$d"); done; fi`
   Run it from the project folder (`cd <project folder> &&` in front).
2. Read `config.json` and `state.json` with the Read tool. Fill a missing key from `${CLAUDE_PLUGIN_ROOT}/templates/config.example.json` and the defaults in this file.
3. To change a value, Read the file, change only that key, and Write the whole file back as valid JSON with two-space indent. Never write a secret-like key. Never Read, Write or create `credentials.json`: with no Python there are no keys, so treat every secret as not set and `notion.access` as `mcp`.
4. Setup without Python: Write `.gtm/config.json` from the template and Write `.gtm/.gitignore` with the line `credentials.json`.
5. Before you use the config, check it by hand. Stop on any of these, as `check` would:
   - `owner.emails` empty, or any address, `owner.own_domains` entry or `sending.sender_email` on `example.com`, `example.org` or `example.net`; `owner.name` is `Your Name`.
   - `owner.timezone` is not an IANA name (see Time zone by hand, below the list); `owner.working_days` is empty or holds a value other than `Mon`..`Sun`; `owner.send_window` is not `HH:MM` to `HH:MM` with start before end.
   - `notion.parent_page_id` or a `notion.data_sources.*` value has no 32-hex id, or is all zeros (a placeholder).
   - `notion.status_map` lacks one of the eight statuses, or two statuses share one option.
   - `notion.access` is not `mcp` (without Python REST cannot run); `runtime` is not `claude-code` or `cowork`.
   - A `notion.select_payload` value is an object (nested), or is not `select` or `status`.
   - `sending.mode` is not `live` or `dry-run`; a cap or day count in `sending.*` or `sweep.*` is not a whole number of 0 or more.
   - A `notion.field_map.*.*` value is empty or not a string (the skills could not find a property such as Do Not Contact or Status).
   - An `adapters.*` value names a tool not listed in the adapters table above; `adapters.meetings`, `adapters.outreach` or `adapters.enrichment` is not a list; `adapters.notify.kind` is not `push`, `slack` or `none`, or is `slack` with an empty `slack_channel`.
   - `sweep.exclude_labels` is not a list of non-empty names.
   - `funnel.start_month` is not `YYYY-MM` or null; `funnel.pilot_stages`, `customer_stages`, `warm_lead_sources`, `inbound_lead_sources` or `inbound` is not a list of non-empty names; `funnel.customer_stages` is empty; `funnel.drop_tolerance_pct` or `max_blank_pct` is not a number of 0 or more; `funnel.rise_tolerance_pct` is not null or a number of 0 or more.
   - Any key in config.json looks like a secret (its name holds `token`, `secret`, `password` or `api_key`).
   Time zone by hand: the name is `UTC`, or `Area/City` (one or two `/`, no spaces) with Area one of `Africa`, `America`, `Antarctica`, `Asia`, `Atlantic`, `Australia`, `Europe`, `Indian`, `Pacific`. If `test -f /usr/share/zoneinfo/<name>` works in this shell, it decides. Otherwise, when the form is right, confirm the name with the user once in setup and accept it, and record that in the run log; later runs accept a name of the right form.
   For every other rule, if you cannot tell whether it holds, treat it as failed and stop. This hand check replaces `check` only; it does not replace any safety gate.
6. State: `state.json` is `{"version": 1, "adapters": {...}}`. Replace only the one adapter key you move, at the same point the skill would run `state-set`.
7. Run log: append the entry to `logs.md` in the active folder (Read, add the entry at the end, Write).
8. `/gtm:import` takes only a CSV of 200 rows or fewer. Map the columns yourself, show the mapping and a preview of the first rows, dedupe by email and LinkedIn URL against the view-mode index, and write in batches of 20 with a yes before the first batch and a check after each one. HubSpot, Pipedrive and Attio: ask for a CSV export instead.
9. `/gtm:funnel` reports `BLOCKED: needs Python` and stops. Never count the funnel by hand.
10. Every safety gate applies unchanged without Python: Do Not Contact, reply stop, verify before marker, forward-only Status, the daily caps and the send window (`${CLAUDE_PLUGIN_ROOT}/reference/safety.md` and `${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`). A missing script is never a reason to skip or weaken one. When a gate cannot be checked, do not send or write that item; list it under Needs you.

## Validation

`check` reports errors (exit 1) for, among others:

- `owner.emails` empty, or an address on a template domain (`example.com`, `example.org`, `example.net`); the same for `owner.own_domains` and `sending.sender_email`; `owner.name` still `Your Name`.
- `notion.parent_page_id` or a `notion.data_sources.*` value that is empty, a placeholder, or not a 32-hex Notion id.
- `notion.access` = `rest` with no saved `notion_token`, or with `runtime` = `cowork`.
- `runtime` other than `claude-code` or `cowork`.
- A nested `notion.select_payload` value (keys must be flat).
- A secret-like key in config.json.

It warns (exit 0) for, among others: an empty `notion.views.*` with `notion.access` = `mcp`, an empty `notion.funnel_page_id`, an empty `owner.own_domains`, a voice or ICP file that does not exist yet, and with `runtime` = `cowork` a config in the home folder or an adapter whose only fallback is an API key.

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

- Two keys are not adapter cursors: `import` (written by `/gtm:import`: `{run_id, source, folder, phase, written, updated}`) and `funnel` (the funnel baseline, written only by `lib/funnel.py`). No adapter may use these names.
- Keys under `adapters` are free-form per adapter; each adapter file defines its own cursor shape in its Cursor section.
- A cursor that holds a time (not a date) is ISO 8601 with an explicit offset, for example `2026-11-16T12:33-05:00` or `2026-11-16T07:03Z`. Never store a local time without an offset.
- When an outreach adapter is incomplete, the email and LinkedIn message cursors do not move past the earliest unmirrored event date (`${CLAUDE_PLUGIN_ROOT}/skills/sweep/references/batch.md`, Cursors).
- A missing or null cursor means no earlier run: look back `sweep.first_run_lookback_days` days. Dedupe makes a repeat safe.
- Move a cursor only when that adapter read everything back to its old cursor in this run. A blocked or incomplete adapter keeps its old cursor, so the next run retries the same period.
- Write cursors with `config.py state-set <adapter> '<json>'` at the end of the run, after the CRM writes are verified.

## logs.md

The `run_log` path printed by `config.py paths`, newest entry last. One entry per run. Format per skill: `${CLAUDE_PLUGIN_ROOT}/reference/run-log.md`.
