# Schedule routines

Setup step 9.

## Routines

| Routine | When (default, local time) | Needs Chrome | Mode |
|---|---|---|---|
| sweep | every day, 08:00 | yes, when `adapters.linkedin` is `chrome` | read and CRM writes, never sends |
| campaign-run | working days, 30 minutes after `owner.send_window.start` | yes, when any campaign uses LinkedIn | `sending.mode` (live by default) |
| funnel | weekly, Monday 07:30 | no | CRM read, writes the Funnel page |

Run sweep before campaign-run on the same day, so replies stop sequences before the next send. Build the cron day field from `owner.working_days` (Mon=1 ... Sun=0). Ask the user to confirm or change the times.

## Where they run

1. Desktop scheduled-tasks tools present (`create_scheduled_task`, found in step 1): use them. They run locally while the Claude desktop app is open, so Claude in Chrome works. Tell the user: "A task due while the app is closed runs the next time you open it."
   - The cron expression is in the machine's local time. If the machine's time zone differs from `owner.timezone`, convert the times and say so.
   - Call `list_scheduled_tasks` first. If a gtm task exists (ids `gtm-sweep`, `gtm-campaign-run`, `gtm-funnel`), update it with `update_scheduled_task` instead of creating a second one.
2. No scheduled-tasks tools: explain the two options and let the user choose:
   - `/schedule` creates a cloud routine. Say both limits plainly. (1) Every gtm skill reads `~/.config/gtm/config.json`, `state.json` and `credentials.json` on this machine. A cloud run does not have them, so it fails at preflight unless the user sets up the same config there. (2) Cloud runs have no Chrome, so the LinkedIn adapter is blocked there every day. Recommend a local option for every routine, funnel included.
   - `/loop` repeats a command in an open Claude Code session on this machine, for example `/loop 24h /gtm:sweep`. It stops when the session ends.
   Give the exact commands; do not run them yourself unless the user asks.

## Live sends need a yes

Before you schedule campaign-run with `sending.mode` = `live`, ask: "Schedule campaign-run to send live on working days at <time>? It sends only for campaigns you set to Active." Schedule it only on an explicit yes. On no, schedule it with the `dry-run` argument, or not at all, as the user prefers.

## Task prompts

Each run starts with no memory of this session, so each prompt must stand alone. Use these, with the values filled in:

sweep:

```
Run /gtm:sweep. It is the gtm plugin's daily CRM sweep: it reads the adapters in ~/.config/gtm/config.json and updates the Notion CRM. It never sends a message. Follow the skill exactly, report BLOCKED items first, and send one notification if anything is blocked. Never sign in, re-authorize or solve a CAPTCHA.
```

campaign-run:

```
Run /gtm:campaign-run<" dry-run" when chosen>. It is the gtm plugin's campaign sender. It sends only for Notion campaigns with Status Active, only the steps and text on the campaign and contact pages, with every gate in the skill (DNC, reply stop, working days and send window, daily caps, verify before marker). Follow the skill exactly, report BLOCKED items first, and send one notification if anything is blocked. Never sign in, re-authorize or solve a CAPTCHA.
```

funnel:

```
Run /gtm:funnel. It is the gtm plugin's weekly funnel report: it reads the Notion CRM and replaces the Funnel page. Follow the skill exactly and report BLOCKED items first.
```

Task ids: `gtm-sweep`, `gtm-campaign-run`, `gtm-funnel`. Titles: "gtm sweep", "gtm campaign run", "gtm funnel". Description: one line saying what it does.

## Record

Log each routine in the setup run log entry: `<routine> — <when> — <local scheduled task | /schedule | /loop | none>`.
