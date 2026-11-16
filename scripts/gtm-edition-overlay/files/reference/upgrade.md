# Upgrade to Tessary GTM Pro

This edition, Tessary GTM (`gtm`), has no scripts. It works through connectors only and keeps its settings with Claude's file tools. Tessary GTM Pro (`gtm-pro`) is the full edition: it adds helper scripts for a Notion integration token, large reads, big imports, API-key adapters and an exact funnel count. Both editions read the same config folder and the same `config.json`, `state.json`, `logs.md`, `voice.md` and `icp.md`, so a switch keeps every setting, cursor and log.

## The upgrade message

When a run hits one of the limits below, do not try a workaround. Finish the parts of the run that are inside the limits, then give this message, word for word:

> {{UPGRADE}}

Add one line before it that names the limit and what you saw, for example "The CRM has about 420 contacts, more than this edition can read reliably." or "Notion said: Your workspace has used up its Query Data Source allowance."

Where it goes. Write the full message once per run, in the run log and in the final report, never twice:

- When the limit blocks an adapter or the whole run (a `BLOCKED` line: an API-key tool with no connector, trigger 3; a funnel that cannot count, triggers 1 and 4), the message is the fix in that `BLOCKED` line. Do not copy it under Needs you.
- Otherwise (the run goes on, or stops before any write, as in triggers 1 and 2), put it under Needs you.
- When several limits apply in one run, write the message in the first place and, for each other limit, write only the line that names it plus "see the upgrade message above".

## When to show it

1. Notion reads. The Notion connector's rows and SQL queries share a small workspace quota. Show the message when (a) the quota error comes back ("used up its Query Data Source allowance") and a view-mode read cannot finish the same work, or (b) the CRM is too large to read reliably in view mode: about 300 contacts or more, or a view-mode read that cannot reach every row. State your estimate of the contact count. Pro reads with a Notion token, which has no such quota.
2. Imports. A CSV of more than about 200 rows, or a CRM import from a tool that has no connector in this session (HubSpot or Pipedrive without its connector). A CSV export of 200 rows or fewer still works here. Attio without a connector goes through a CSV export in both editions, so a large Attio export is a large CSV.
3. API-key tools. Any adapter that has no connector in this session and would need an API key: gojiberry, lemlist, instantly, hunter, fireflies and fathom without a connector, and the HubSpot and Pipedrive imports without a connector. Pro calls these tools with a read-only client and a key the user saves in a terminal. Mark the adapter blocked for this run, as `${CLAUDE_PLUGIN_ROOT}/reference/blocked.md` says, and use this message as its fix.
4. Funnel counts. The funnel counts by hand only when there are about 150 counted contacts or fewer, and only when a second, independent count gives the same numbers (`${CLAUDE_PLUGIN_ROOT}/skills/funnel/SKILL.md`). Above about 150 counted contacts, report `BLOCKED: too many contacts to count by hand` and show the message. Pro counts with a script.

## After the switch

1. Install Tessary GTM Pro as the message says, then remove Tessary GTM from the `/plugin` menu, so each skill runs only once.
2. Pro's slash commands are `/gtm-pro:<skill>`, for example `/gtm-pro:sweep`. Run `/gtm-pro:setup schedules` once: it updates the scheduled tasks so they call the Pro commands.
3. In Claude Code, Pro can save a Notion integration token for bulk reads (`/gtm-pro:setup`). In Cowork, Pro uses connectors only, the same as this edition.
