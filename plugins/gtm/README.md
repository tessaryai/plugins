# gtm

A plugin for Claude Code and Claude Cowork that hosts your CRM in Notion and runs your go-to-market flow with skills.
It is for founders and small sales teams who want a CRM they own, kept current by an agent.

The plugin sets up (or maps) five Notion databases, imports your existing CRM, sweeps your
inbox, calendar, LinkedIn, meeting recorders and outreach tools into the CRM every day, builds
campaign audiences from your ideal customer profile, writes sequences in your own voice, sends
them with safety gates, and reports your funnel.

Everything works with only the Notion connector. Other tools plug in through adapters.

## Requirements

- Claude Code, or Claude Cowork in the Claude desktop app (see Use gtm in Cowork). Use the
  desktop app for the scheduled routines: its local scheduled tasks run on your computer, so
  Claude in Chrome works in them.
- The Notion connector, added in Claude settings. This is the only required connector.
- Optional, one per adapter you want: Gmail or Outlook, Google Calendar or Outlook calendar,
  Slack, a meeting recorder (Fathom, Granola, Fireflies, Otter), an outreach tool (Gojiberry,
  lemlist, Instantly, Apollo), enrichment (Exa, Apollo, Hunter, or any enrichment connector).
  Some tools also work with an API key instead of a connector (see Adapters).
- Claude in Chrome, signed in to LinkedIn, for anything that reads or sends on LinkedIn.
- Python 3 (standard library only) for the helper scripts in `lib/`. Without it, most skills still
  run with smaller limits; the funnel report needs it (see
  [`reference/config.md`](./reference/config.md), No Python).
- Recommended: a Notion integration token for a CRM with more than about 200 contacts or any
  active campaign. The Notion connector's row queries share a small workspace quota; REST has
  none, and it makes bulk reads, big imports and exact copy reads reliable.

## Install

In any Claude Code session:

```
/plugin marketplace add tessaryai/plugins
/plugin install gtm@tessary
```

In Claude Cowork, see [Use gtm in Cowork](#use-gtm-in-cowork).

## Use gtm in Cowork

1. Install. In the Claude desktop app, open the Plugins page, choose Add marketplace, enter
   `tessaryai/plugins`, and install gtm. A plugin installed with the Claude Code CLI does not
   carry over to Cowork.
2. Connect a project folder to the task, then run `/gtm:setup`. Keep the settings in that folder
   when setup asks: it creates `.gtm/` there, with a `.gitignore` that keeps keys out of git.
   Files outside the connected folder may not last between Cowork sessions.
3. Connectors only. Cowork cannot reach the Notion API or other tools' APIs directly, and has no
   terminal for typing a key. Setup sets `runtime` to `cowork`, and gtm then uses connectors
   only.

What works: Notion through its connector, Gmail or Outlook, Google or Outlook calendar, Slack, any
meeting recorder, outreach or enrichment tool that has a connector, and LinkedIn through Claude
in Chrome. What does not: a Notion integration token, API keys (a tool without a connector is
blocked), and, if Python is missing, the funnel report and imports of more than 200 rows.

Scheduling: if Cowork offers no scheduled tasks, run the skills when you want them (for example
"run the gtm sweep"), or schedule them from Claude Code on the same computer, pointed at the
same project folder. Both then share one config, state and run log.

## Get started in three steps

1. Run `/gtm:setup`. It checks your connectors, asks a few questions, creates the five
   databases under a Notion page you pick (or maps the ones you have), writes the config file
   (in `~/.config/gtm/`, or in a `.gtm/` folder in your project), builds your voice and ICP
   files, shows the LinkedIn warning, and offers to schedule the routines.
2. Run `/gtm:import` if you have contacts somewhere else (a CSV or Google Sheets export,
   HubSpot, Pipedrive or Attio). It shows a preview and writes nothing until you say yes.
3. Run a dry run: `/gtm:sweep dry-run` and `/gtm:campaign-run dry-run`. They read everything,
   write nothing, send nothing, and show what a real run would do and what is blocked. Setup
   runs both for you at the end.

Then build your first campaign with `/gtm:campaign-build`.

## Skills

| Skill | What it does | Schedule | Reads | Writes | Sends? |
|---|---|---|---|---|---|
| `/gtm:setup` | Onboarding: connectors, databases, config, voice, ICP, LinkedIn cap, schedules, dry runs. Re-run it to change settings; it shows a diff first. | manual | session connectors, Notion | Notion databases and Funnel page, the config folder | no |
| `/gtm:import` | Imports contacts, companies, deals and notes from another CRM, with dedupe, a preview and resumable batches. | manual | CSV, HubSpot, Pipedrive, Attio (read-only) | Contacts, Companies, Pipeline | no |
| `/gtm:sweep` | Keeps the CRM current: replies, bounces, sent mail, bookings, meetings, LinkedIn accepts and messages, outreach-tool touches. | daily | email, calendar, LinkedIn, meeting recorders, outreach tools (all read-only) | contact Status, log lines, First Contacted, Meetings pages, outreach mirror pages | no |
| `/gtm:campaign-build` | Builds a campaign audience from your ICP: sources, scores, finds and verifies emails, dedupes, asks, then writes. | manual | `icp.md`, enrichment adapters, LinkedIn profiles (optional, read-only) | Campaign page (Status Review), Companies, Contacts | no |
| `/gtm:campaign-write` | Writes the sequence and copy in your voice onto the campaign page, and personalized copy plus a `Run fields:` line onto each contact page. | manual | `voice.md`, ICP, research tools, LinkedIn profiles (optional) | campaign and contact page bodies | no |
| `/gtm:campaign-run` | Sends the steps that are due today for every Active campaign, after a reply check and all gates. | working days, in your send window | campaign and contact pages, email, LinkedIn inbox | markers, Status, First Contacted | yes: email and LinkedIn, only text on the pages |
| `/gtm:funnel` | Recounts the monthly funnel (cold and warm outbound) and replaces the Funnel page, only when its checks pass. | weekly | Contacts, Pipeline | the Funnel page only | no |

sweep, campaign-build, campaign-write, campaign-run and funnel accept a `dry-run` argument. Only
`/gtm:campaign-run` sends anything.

## Data model

Setup creates these databases from [`templates/schema.json`](./templates/schema.json), plus a
plain Funnel page, all under one parent page:

| Database | Holds | Key properties |
|---|---|---|
| Contacts | People | Name, Email, LinkedIn, Status, Do Not Contact, DNC Reason, DNC Set On, Email Status, First Contacted, Lead Source, Company, Campaign, Deal, Meetings |
| Companies | Organizations | Name, Website, LinkedIn, ICP, ICP Notes, Vertical, Contacts, Deals |
| Pipeline | Deals | Name, Stage, Company, Contacts, Value, Expected Close, Likelihood |
| Campaigns | Outreach campaigns | Campaign Name, Status (Review, Active, Paused, Completed), Type, Start Date, End Date, Contacts |
| Meetings | Recorded meetings | Meeting name, Date, Contacts, Recording URL, Summary, Source |

If you map an existing workspace instead, your own property and option names are stored in
`notion.field_map`, `notion.status_map` and `notion.option_map`. Every skill reads names through
these maps and never hardcodes them.

### Contact status

Status moves forward only:

```
New < Contacted < Responded < Discovery < Lead
```

- Contacted: the first confirmed outbound message went out.
- Responded: the contact sent a real reply. A LinkedIn connection accept is not a reply.
- Discovery: a meeting is booked, or a recorded meeting took place.
- Lead: a deal exists. Only you set it, or a skill when you ask.

`Archived`, `Do Not Contact` and `Disqualified` are terminal. Nothing moves a contact out of
them, and nothing clears the Do Not Contact box. Automation sets Do Not Contact only on a
genuine negative reply ("stop", "unsubscribe", "remove me", "not interested").

Contacts are matched by LinkedIn URL or email only, never by name. A domain match is used only
when exactly one contact has that domain and it is not a free-mail domain.

### Log lines and markers

Each event is one dated paragraph on the contact page, written once:

```
2026-03-05 — Email reply received (neutral). Status → Responded. Action: sweep email check.
```

campaign-run writes one marker per step it sends or skips, and a stop marker when a contact
leaves a campaign. The markers are campaign-run's state:

```
2026-03-02 — [GTM:q2-founders:S1-LI] LinkedIn invite sent, no note. Action: campaign-run (Chrome).
2026-03-09 — [GTM:q2-founders:STOP] Stopped: reply received. Action: campaign-run reply check.
```

`q2-founders` is the campaign key, from the `Campaign key:` line on the campaign page. Page
bodies are append-only: no skill replaces a contact, company or campaign page. Full rules:
[`reference/crm-rules.md`](./reference/crm-rules.md) and
[`reference/campaign-page.md`](./reference/campaign-page.md).

## Adapters

An adapter connects one outside tool. When the session has an MCP connector for the tool, the
adapter uses it. Otherwise it uses the read-only API client `lib/readonly_api.py` (GET only, fixed
paths) with a key you save. A tool with neither is blocked.

| Kind | Tool | Connector or API key | Access |
|---|---|---|---|
| email | `gmail` | Gmail connector | read; send from campaign-run only |
| email | `outlook` | Outlook / Microsoft 365 connector | read; send from campaign-run only |
| calendar | `google` | Google Calendar connector | read-only |
| calendar | `outlook` | Outlook calendar connector | read-only |
| linkedin | `chrome` | Claude in Chrome | read; send from campaign-run only |
| meetings | `fathom` | connector, or `fathom_api_key` | read-only |
| meetings | `granola` | connector only | read-only |
| meetings | `fireflies` | connector, or `fireflies_api_key` | read-only |
| meetings | `otter` | connector only | read-only |
| outreach | `gojiberry` | `gojiberry_api_key` (preferred), or a connector's read tools | read-only mirror |
| outreach | `lemlist` | connector, or `lemlist_api_key` | read-only mirror |
| outreach | `instantly` | connector, or `instantly_api_key` (email log only) | read-only mirror |
| outreach | `apollo` | Apollo connector (the API fallback cannot list contacts) | read-only mirror |
| enrichment | `exa` | Exa connector only | read-only |
| enrichment | `apollo` | Apollo connector (the API fallback cannot search) | read-only |
| enrichment | `hunter` | connector, or `hunter_api_key` | read-only |
| enrichment | `mcp` | any enrichment connector in the session | read-only |
| notify | `push` | the PushNotification tool | one message per run |
| notify | `slack` | Slack connector | one message per run |
| import | `csv` | none (a file) | read-only |
| import | `hubspot` | connector, or `hubspot_token` | read-only |
| import | `pipedrive` | connector, or `pipedrive_api_token` | read-only |
| import | `attio` | connector, else a CSV export | read-only |

Salesforce, Airtable and any other CRM import through a CSV export. Each adapter file is in
[`adapters/<kind>/<tool>.md`](./adapters/). The contract is in
[`adapters/README.md`](./adapters/README.md).

Choose adapters in setup, or with `config.py set` (keys `adapters.email`, `adapters.calendar`,
`adapters.linkedin`, `adapters.meetings`, `adapters.outreach`, `adapters.enrichment`,
`adapters.notify.kind`, `adapters.notify.slack_channel`).

## Campaign lifecycle

1. Build. `/gtm:campaign-build` creates the campaign page at Status `Review` with a campaign key,
   finds the audience, shows it, and writes the contacts after your yes.
2. Write. `/gtm:campaign-write` proposes the steps (channels, day offsets, conditions) and the
   copy, gets your OK, writes them onto the campaign page, then writes personalized copy and a
   `Run fields:` line onto each contact page. Every personalized claim has a source on the page.
3. Review. Read the campaign page and a few contact pages. Edit anything by hand. What is on the
   pages is exactly what will be sent.
4. Approve. Set the campaign Status to `Active`. That is the approval. No skill ever sets
   `Active`. For tighter control, an `Approval: per contact` line on the campaign page needs an
   `Approved: <campaign_key> S<n>` line on each contact page.
5. Run. `/gtm:campaign-run` sends the steps that are due today, in your send window, on your
   working days, inside the daily caps. It verifies each send on the channel before it writes
   the marker.
6. Replies stop. A reply on any channel stops that contact in every campaign. campaign-run never
   answers a reply; you do. It lists replies under Needs you.

Test any time with `/gtm:campaign-run dry-run`: it prints the plan and the exact text that would
go out.

## Configuration, state and logs

Runtime files live in one config folder, outside the plugin folder, because a plugin update
replaces that folder. The active folder is the first of: `$GTM_CONFIG_DIR`; a `.gtm/` folder
holding `config.json` in the current folder or a parent (create it with `config.py init --project`);
`~/.config/gtm/`. `config.py paths` prints which one is active and why.

| File | Holds |
|---|---|
| `config.json` | Settings. No secrets. |
| `credentials.json` | Notion token and API keys, mode 600. Only `lib/*.py` reads it. Never used in Cowork. |
| `state.json` | Per-adapter cursors, import progress, the funnel baseline. |
| `logs.md` | Run log, one entry per run. |
| `voice.md` | Your writing voice. |
| `icp.md` | Your ideal customer profile. |
| `imports/<run_id>/` | Work files of one import, so `/gtm:import resume` works later. |

The config CLI (run from a terminal, with the plugin's install path as `<plugin root>`):

```
python3 -I -B <plugin root>/lib/config.py show          # config with secrets masked
python3 -I -B <plugin root>/lib/config.py check         # validate
python3 -I -B <plugin root>/lib/config.py get sending.mode
python3 -I -B <plugin root>/lib/config.py set sending.email_daily_cap 30
python3 -I -B <plugin root>/lib/config.py set-secret notion_token
python3 -I -B <plugin root>/lib/config.py paths         # which folder is active, and where the files are
```

Save keys only with `set-secret`, in your own terminal. It reads the key at a hidden prompt.
Never paste a key into the chat. Every key is documented in
[`reference/config.md`](./reference/config.md).

Main settings:

| Key | Default | Meaning |
|---|---|---|
| `sending.mode` | `live` | `dry-run` sends nothing and writes nothing. A `live` argument never overrides a `dry-run` config. |
| `sending.linkedin_daily_invite_cap` | `10` | Most LinkedIn invites per day, all campaigns. |
| `sending.email_daily_cap` | `40` | Most campaign emails per day, all campaigns. |
| `sending.sender_email` | | The From address campaign-run expects. |
| `owner.timezone` | `UTC` | Time zone for "today", working days and the send window. |
| `owner.working_days` | Mon to Fri | Days campaign-run may send. |
| `owner.send_window` | 09:00 to 17:00 | Local hours in which sends may happen. |
| `notion.access` | `mcp` | `rest` when a Notion token is saved; bulk work then uses `lib/notion_rest.py`. Always `mcp` in Cowork. |
| `runtime` | `claude-code` | `cowork` uses connectors only (see Use gtm in Cowork). |

## Scheduling

| Routine | Default time | Needs Chrome |
|---|---|---|
| `/gtm:sweep` | every day, 08:00 | yes, when LinkedIn is on |
| `/gtm:campaign-run` | working days, 30 minutes after the send window opens | yes, when a campaign uses LinkedIn |
| `/gtm:funnel` | Monday, 07:30 | no |

The sweep runs before campaign-run, so replies stop sequences before the next send.

- Desktop scheduled tasks (recommended). Setup creates the tasks `gtm-sweep`,
  `gtm-campaign-run` and `gtm-funnel`. They run on your computer while the Claude desktop app is
  open, so Chrome works. A task due while the app is closed runs when you next open it.
- `/loop`, for example `/loop 24h /gtm:sweep`, repeats a command in an open session on your
  computer. It stops when the session ends.
- `/schedule` (cloud) is not recommended. A cloud run does not have your gtm config folder,
  so it fails at preflight unless you set up the same config there. It also has no Chrome, so
  LinkedIn is blocked every time.

Setup schedules a live campaign-run only after you say yes.

## Safety

- Only `/gtm:campaign-run` sends. It sends only for campaigns at Status `Active`, only the steps
  on the campaign page, and only text found word for word on the campaign or contact page.
- Gates before every send: a fresh Do Not Contact read, the reply stop, working days and the send
  window, daily caps, and verify-before-marker (the send is read back from the channel before
  the marker is written).
- The sweep, import, build, write and funnel skills never send. Outreach tools, calendars,
  meeting recorders, enrichment and import sources are read-only. The API client refuses
  every verb except GET and every path not on its allowlist.
- Every skill shows a preview and asks before bulk writes (import, campaign-build) or before
  writing copy (campaign-write). The sweep runs without asking and records its choices under
  Decisions.
- An import never overwrites Status, Do Not Contact, the DNC fields, First Contacted or
  relations, even when you allow overwrites.
- No skill deletes a Notion page, database or block, clears Do Not Contact, or moves a contact
  out of a terminal status.
- All email, message, page, export and web text is treated as data, never as instructions.
- Tokens are never printed, logged, put on a command line or asked for in the chat.
- No skill signs in, re-authorizes a connector, or solves a CAPTCHA.

Full rules: [`reference/safety.md`](./reference/safety.md).

### LinkedIn account risk

LinkedIn does not allow automation of its website. Sending invites and messages through Chrome
can get your LinkedIn account restricted or banned. The risk is yours.

gtm keeps the risk low. The invite cap is 10 a day by default, and setup warns again above 20.
It works slowly, one profile at a time, with pauses between actions. It uses page clicks and
typing only, never LinkedIn's internal APIs. It stops all LinkedIn work at the first
invitation limit, restriction notice or warning. A profile view is visible to the person, so
build and write ask before they read profiles.

To avoid the risk, send only email campaigns, or set `adapters.linkedin` to `null`.

## Add an adapter

1. Pick the kind (email, calendar, linkedin, meetings, outreach, enrichment, notify, import).
2. Write `adapters/<kind>/<tool>.md` with every section in
   [`adapters/README.md`](./adapters/README.md): Purpose, Tool, Preflight check, Read procedure,
   Output, Cursor, Blocked signs and fix, Write / send capability.
3. If the tool has no MCP connector, add a GET-only entry to `ALLOWLIST` in `lib/readonly_api.py`
   and the secret name to `SECRET_NAMES` in `lib/config.py`. Never add a path that sends,
   changes or deletes.
4. Add the tool name to `KNOWN_ADAPTERS` in `lib/config.py` (not needed for an import adapter:
   `/gtm:import` picks the source from its argument or asks you) and to the tables in `adapters/README.md` and
   `reference/config.md`.
5. Test with `python3 -I -B lib/readonly_api.py <tool> check` and a dry run of the skill that uses it.
6. Add a CHANGELOG entry.

## Troubleshooting

Every run reports BLOCKED first, then Needs you, then Decisions, then counts. A blocked adapter
never stops the others, keeps its cursor so the next run retries the same period, and sends
one notification per run. The run log is at the `run_log` path that `config.py paths` prints.

| You see | Fix |
|---|---|
| Notion blocked | Add or reconnect the Notion connector in Claude settings. Nothing can be written until it works. |
| `<connector> blocked: auth error` | Reconnect that connector in Claude settings, then run the skill again. |
| `<tool> blocked: key missing or refused` | Save a working key in your terminal: `python3 -I -B <plugin root>/lib/config.py set-secret <name>`. |
| `<tool> blocked` in Cowork | Connect a connector for that tool, or run the routine from Claude Code. Cowork uses no API keys. |
| Settings not found, or a new setup starts | `config.py paths` shows the active folder. Run from the project folder that holds `.gtm/`, or set `GTM_CONFIG_DIR`. |
| LinkedIn blocked: login page, CAPTCHA, extension not connected | Open Chrome, sign in to LinkedIn, and check that the Claude extension is connected. |
| LinkedIn blocked: invitation limit or warning | Stop LinkedIn sends for some days. Lower `sending.linkedin_daily_invite_cap`. |
| From address differs from the sender email | Send from the address in `sending.sender_email`, or change that key (or the campaign's `Sender email:` line). |
| REST auth error, fell back to MCP | Share the CRM pages with your Notion integration, or save the token again with `set-secret notion_token`. |
| `Query Data Source allowance` used up | The Notion connector's rows and SQL queries share a small workspace quota. Skills read in view mode (`notion.views`) and switch to it on this error. For a large CRM or active campaigns, save a Notion token in `/gtm:setup`; REST has no such quota. |
| `config.py check` errors | Run `/gtm:setup` again; it shows the keys to fix. |
| Campaign skipped: no campaign key | Add a `Campaign key: <slug>` line to the campaign page. |
| Step skipped: merge gap | Add the missing value to the contact's `Run fields:` line, or run `/gtm:campaign-write personalize-only`. |
| Nothing sent: not a working day, or outside window | Expected. Check `owner.working_days`, `owner.send_window` and `owner.timezone`. |
| Funnel not published: check failed | A count went down or rose too much against the last run. If the change is real (a CRM cleanup), ask the funnel to accept the new baseline. |
| Funnel not published: too many blank First Contacted | Common after a large import. Run `/gtm:sweep` to backfill dates, set them by hand, or raise `funnel.max_blank_pct`. |
| A scheduled run did nothing | Desktop tasks run only while the Claude desktop app is open. A cloud `/schedule` run has no config and no Chrome. |

## Uninstall or reset

1. Delete the scheduled tasks `gtm-sweep`, `gtm-campaign-run` and `gtm-funnel` (ask Claude, or
   use the scheduled tasks list in the desktop app), and stop any `/loop`.
2. Uninstall the plugin from the `/plugin` menu.
3. To reset settings, delete the config folder that `config.py paths` prints (`~/.config/gtm/`,
   a project's `.gtm/`, or `$GTM_CONFIG_DIR`). This removes your config,
   keys, cursors, run log, voice and ICP files. Run `/gtm:setup` to start again.
4. Your Notion databases, pages and log lines stay. Delete them in Notion if you want them gone.
   To stop gtm reaching your workspace, remove the Notion connector, and remove the integration
   from the CRM pages if you created one.

## Privacy

gtm runs in your Claude session. It sends nothing to Tessary and has no telemetry. It reads and
writes your Notion workspace and the tools you turn on. It sends email and LinkedIn messages
only from `/gtm:campaign-run`, for campaigns at Status `Active`. It stores settings, state, the
run log and API keys locally in the active config folder, with keys in `credentials.json`
(mode 600). Full policy: https://tessary.ai/privacy-policy

### Credentials

gtm works with connectors alone. Keys are optional, for the REST path on large CRMs and for tools with no connector. You save them yourself in a terminal (`config.py set-secret`), never in chat, and they stay in `credentials.json` (mode 600) in your config folder. Each key goes only to its own vendor's API:

| Key | Sent only to |
|---|---|
| `notion_token` | api.notion.com |
| `hubspot_token` | api.hubapi.com |
| `pipedrive_api_token` | api.pipedrive.com |
| `attio_api_key` | api.attio.com |
| `fathom_api_key` | api.fathom.ai |
| `fireflies_api_key` | api.fireflies.ai |
| `gojiberry_api_key` | ext.gojiberry.ai |
| `lemlist_api_key` | api.lemlist.com |
| `instantly_api_key` | api.instantly.ai |
| `apollo_api_key` | api.apollo.io |
| `hunter_api_key` | api.hunter.io |

`lib/readonly_api.py` enforces this with a fixed host and path allowlist per tool, and sends GET requests only (Fireflies: GraphQL read queries only). In Cowork mode gtm reads no keys at all.


## License

MIT — see `LICENSE`.
