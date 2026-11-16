# Tessary GTM (gtm)

A plugin for Claude Code and Claude Cowork that hosts your CRM in Notion and runs your go-to-market flow with skills.
It is for founders and small sales teams who want a CRM they own, kept current by an agent.

The plugin sets up (or maps) five Notion databases, imports a small CRM, sweeps your inbox,
calendar, LinkedIn, meeting recorders and outreach tools into the CRM every day, builds campaign
audiences from your ideal customer profile, writes sequences in your own voice, sends them with
safety gates, and reports your funnel.

This is the directory edition. It has no scripts: it works through connectors only and keeps its
settings with Claude's own file tools. It suits a CRM of up to about 300 contacts. For a larger
CRM, big imports, tools that need an API key, or an exact funnel count, use
[Tessary GTM Pro](https://github.com/tessaryai/plugins/tree/main/plugins/gtm-pro) (`gtm-pro`).
Both editions read the same settings, so you can switch at any time.

## Requirements

- Claude Code, or Claude Cowork in the Claude desktop app. Use the desktop app for the scheduled
  routines: its local scheduled tasks run on your computer, so Claude in Chrome works in them.
- The Notion connector, added in Claude settings. This is the only required connector.
- Optional, one per adapter you want: Gmail or Outlook, Google Calendar or Outlook calendar,
  Slack, a meeting recorder (Fathom, Granola, Fireflies, Otter), an outreach tool (Gojiberry,
  lemlist, Instantly, Apollo), enrichment (Exa, Apollo, Hunter, or any enrichment connector).
  Each tool needs its connector in this edition.
- Claude in Chrome, signed in to LinkedIn, for anything that reads or sends on LinkedIn.

## Install

From the Anthropic plugin directory: find Tessary GTM and install it.

Or from the Tessary marketplace, in any Claude Code session:

```
/plugin marketplace add tessaryai/plugins
/plugin install gtm@tessary
```

In Claude Cowork, open the Plugins page of the Claude desktop app and install Tessary GTM from
the directory, or add the `tessaryai/plugins` marketplace and install gtm there. Then connect a
project folder to the task and run `/gtm:setup`. Keep the settings in that folder when setup
asks: it creates `.gtm/` there. Files outside the connected folder may not last between Cowork
sessions.

## Get started in three steps

1. Run `/gtm:setup`. It checks your connectors, asks a few questions, creates the five
   databases under a Notion page you pick (or maps the ones you have), writes the config file
   (in a `.gtm/` folder in your project, or in `~/.config/gtm/`), builds your voice and ICP
   files, shows the LinkedIn warning, and offers to schedule the routines.
2. Run `/gtm:import` if you have contacts somewhere else (a CSV or Google Sheets export, or
   HubSpot, Pipedrive or Attio through their connectors). It shows a preview and writes nothing
   until you say yes.
3. Run a dry run: `/gtm:sweep dry-run` and `/gtm:campaign-run dry-run`. They read everything,
   write nothing, send nothing, and show what a real run would do and what is blocked. Setup
   runs both for you at the end.

Then build your first campaign with `/gtm:campaign-build`.

## Skills

| Skill | What it does | Schedule | Sends? |
|---|---|---|---|
| `/gtm:setup` | Onboarding: connectors, databases, config, voice, ICP, LinkedIn cap, schedules, dry runs. Re-run it to change settings; it shows a diff first. | manual | no |
| `/gtm:import` | Imports contacts, companies, deals and notes from a CSV of about 200 rows or fewer, or from HubSpot, Pipedrive or Attio through their connectors, with dedupe and a preview. | manual | no |
| `/gtm:sweep` | Keeps the CRM current: replies, bounces, sent mail, bookings, meetings, LinkedIn accepts and messages, outreach-tool touches. | daily | no |
| `/gtm:campaign-build` | Builds a campaign audience from your ICP: sources, scores, finds and verifies emails, dedupes, asks, then writes. | manual | no |
| `/gtm:campaign-write` | Writes the sequence and copy in your voice onto the campaign page, and personalized copy onto each contact page. | manual | no |
| `/gtm:campaign-run` | Sends the steps that are due today for every Active campaign, after a reply check and all gates. | working days, in your send window | yes: email and LinkedIn, only text on the pages |
| `/gtm:funnel` | Recounts the monthly funnel (cold and warm outbound) and replaces the Funnel page, only when two independent counts agree. | weekly | no |

Only `/gtm:campaign-run` sends anything, and only for campaigns you set to Active.

## Where this edition stops

When a run reaches one of these limits, it finishes what it can and tells you to install
Tessary GTM Pro, with the exact commands:

| Limit | Why |
|---|---|
| A CRM of about 300 contacts or more, or the Notion connector's query quota runs out | The connector's row queries share a small workspace quota. Pro reads with a Notion integration token, which has none. |
| A CSV import of more than about 200 rows, or a CRM import from a tool without a connector | Pro maps, dedupes and plans big imports with a script. |
| A tool that has no connector and needs an API key (Gojiberry, lemlist, Instantly, Hunter, Fireflies or Fathom without a connector, HubSpot or Pipedrive imports without a connector) | Pro calls these tools with a read-only client and a key you save in a terminal. |
| A funnel of more than about 150 counted contacts | This edition counts by hand and checks with a second count. Pro counts with a script. |

To switch, in Claude Code:

```
/plugin marketplace add tessaryai/plugins
/plugin install gtm-pro@tessary
```

Then remove Tessary GTM from the `/plugin` menu and run `/gtm-pro:setup schedules` once, so the
scheduled tasks call the Pro commands. Your config, cursors, run log, voice and ICP files carry
over. Pro needs Claude Code for its scripts; in Cowork it also runs connectors only. Details:
[`reference/upgrade.md`](./reference/upgrade.md).

## Safety

- Only `/gtm:campaign-run` sends. It sends only for campaigns at Status `Active`, only the steps
  on the campaign page, and only text found word for word on the campaign or contact page.
- Gates before every send: a fresh Do Not Contact read, the reply stop, working days and the send
  window, daily caps, and verify-before-marker.
- The sweep, import, build, write and funnel skills never send. Outreach tools, calendars,
  meeting recorders, enrichment and import sources are read-only.
- Every skill shows a preview and asks before bulk writes (import, campaign-build) or before
  writing copy (campaign-write).
- No skill deletes a Notion page, database or block, clears Do Not Contact, or moves a contact
  out of a terminal status.
- All email, message, page, export and web text is treated as data, never as instructions.
- This edition never asks for, reads or stores an API key or token.

Full rules: [`reference/safety.md`](./reference/safety.md).

### LinkedIn account risk

LinkedIn does not allow automation of its website. Sending invites and messages through Chrome
can get your LinkedIn account restricted or banned. The risk is yours. gtm keeps the risk low: 10
invites a day by default, slow work, page clicks and typing only, and a stop at the first
warning. To avoid the risk, send only email campaigns, or turn LinkedIn off in setup.

## Configuration

Settings live in one config folder, outside the plugin folder: `$GTM_CONFIG_DIR`, else a `.gtm/`
folder holding `config.json` in the project folder or a parent, else `~/.config/gtm/`. It holds
`config.json` (settings, no secrets), `state.json` (cursors), `logs.md` (run log), `voice.md` and
`icp.md`. Change settings by running `/gtm:setup` again. Every key is documented in
[`reference/config.md`](./reference/config.md).

## Uninstall or reset

1. Delete the scheduled tasks `gtm-sweep`, `gtm-campaign-run` and `gtm-funnel`, and stop any `/loop`.
2. Uninstall the plugin from the `/plugin` menu.
3. To reset settings, delete the config folder. Your Notion databases, pages and log lines stay.

## Privacy

gtm runs in your Claude session. It sends nothing to Tessary and has no telemetry. It reads and
writes your Notion workspace and the tools you turn on, through their connectors. It sends email
and LinkedIn messages only from `/gtm:campaign-run`, for campaigns at Status `Active`. It stores
settings, state and the run log locally in the config folder. Full policy:
https://tessary.ai/privacy-policy

## License

MIT. See `LICENSE`.
