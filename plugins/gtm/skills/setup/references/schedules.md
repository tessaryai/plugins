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
   - Call `list_scheduled_tasks` first. Look for existing routines that do the same job: a task id `gtm-sweep`, `gtm-campaign-run` or `gtm-funnel`, and ALSO any task whose id, title or description mentions a CRM sweep, a campaign run or sender, or a funnel report (for example a routine the user built before this plugin). Show every match to the user and ask, per routine, whether to update it, replace it (disable the old one and create the gtm task), or keep both. Never create a second sweep or a second campaign sender next to an existing one without an explicit yes: two senders can send the same step twice.
2. No scheduled-tasks tools: explain the two options and let the user choose:
   - `/schedule` creates a cloud routine. Say both limits plainly. (1) Every gtm skill reads the config and state files in the gtm config folder on this machine. A cloud run does not have them, so it fails at preflight unless the user sets up the same config there. (2) Cloud runs have no Chrome, so the LinkedIn adapter is blocked there every day. Recommend a local option for every routine, funnel included.
   - `/loop` repeats a command in an open Claude Code session on this machine, for example `/loop 24h /gtm:sweep`. It stops when the session ends.
   Give the exact commands; do not run them yourself unless the user asks.

## Cowork

1. Look for a scheduled-tasks tool in this session (ToolSearch `scheduled-tasks create_scheduled_task list_scheduled_tasks`). Never schedule anything in Cowork without one, and never invent another way to schedule.
2. If one is present, use it as in Where they run, item 1, with the same task prompts. Add to each prompt: "Work in <project folder>; run every shell command with `cd <project folder> &&` in front." so the run finds `.gtm/`.
3. If none is present, tell the user in plain words: routines will not run on their own here. Two choices:
   - Run the skills on demand in Cowork, for example "run the gtm sweep" each morning, then "run the gtm campaigns".
   - Schedule them from Claude Code on the same computer (desktop scheduled tasks), pointed at the same project folder: each task prompt says "Work in <project folder>", or the task sets `GTM_CONFIG_DIR=<project folder>/.gtm`. Both apps then share one config, state and run log. While `runtime` is `cowork`, those Claude Code runs also use connectors only.
4. Record `none (on demand)` or `Claude Code` for each routine in the run log.

## Live sends need a yes

Before you schedule campaign-run with `sending.mode` = `live`, ask: "Schedule campaign-run to send live on working days at <time>? It sends only for campaigns you set to Active." Schedule it only on an explicit yes. On no, schedule it with the `dry-run` argument, or not at all, as the user prefers.

## Task prompts

Each run starts with no memory of this session, so each prompt must stand alone. Use these, with the values filled in. When the config is in a project `.gtm/` folder, add one sentence to each prompt: "Work in <project folder>; run every shell command with `cd <project folder> &&` in front." Otherwise the run may not find `.gtm/`.

sweep:

```
Run /gtm:sweep. It is the gtm plugin's daily CRM sweep: it reads the adapters in the gtm config and updates the Notion CRM. It never sends a message. Follow the skill exactly, report BLOCKED items first, and send one notification if anything is blocked. Never sign in, re-authorize or solve a CAPTCHA.
```

campaign-run:

```
Run /gtm:campaign-run<" dry-run" when `sending.mode` is dry-run or the user declined live sends>. It is the gtm plugin's campaign sender. It sends only for Notion campaigns with Status Active, only the steps and text on the campaign and contact pages, with every gate in the skill (DNC, reply stop, working days and send window, daily caps, verify before marker). Follow the skill exactly, report BLOCKED items first, and send one notification if anything is blocked. Never sign in, re-authorize or solve a CAPTCHA.
```

funnel:

```
Run /gtm:funnel. It is the gtm plugin's weekly funnel report: it reads the Notion CRM and replaces the Funnel page. Follow the skill exactly and report BLOCKED items first.
```

Task ids: `gtm-sweep`, `gtm-campaign-run`, `gtm-funnel`. Titles: "gtm sweep", "gtm campaign run", "gtm funnel". Description: one line saying what it does.

## Record

Log each routine in the setup run log entry: `<routine> — <when> — <local scheduled task | /schedule | /loop | none>`.
