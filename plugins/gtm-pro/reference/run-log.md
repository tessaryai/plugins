# Run log

Every gtm skill run appends exactly one entry to the run log, newest last, and ends with a final report in the chat that uses the same order. The run log is the `run_log` path printed by `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py paths`; it follows the active config folder, so never hardcode it. Create the file with the line `# gtm run log` when it does not exist. Never rewrite or delete earlier entries.

## Order inside an entry

1. `BLOCKED` (only when something was blocked): each blocked adapter, what you saw, the fix the user must do.
2. `Needs you`: items only a person can handle. Replies that need an answer (with channel and verbatim text), meeting requests, items the rules forbid you to change, missing select options, lapsed campaign steps, copy gaps. Write `none` when empty.
3. `Decisions`: best-guess calls, so the user can reverse them. Each item: the evidence, what you chose, and `(was: <old value>)`. Write `none` when empty.
4. Counts and details for the skill (below).

Keep each line short. Use contact names and page links, not page ids alone. Never put a token, key, header or raw exception text in the log.

Large sets (unmatched items, skipped contacts, contacts with no First Contacted, dropped rows): write the count, then at most 10 names or addresses, then the rest as a count, for example `Unmatched: 143 (gmail 120, google-calendar 23) — Ada Lovelace, ...; and 133 more`. Group the count by source or reason when that helps. Never paste hundreds of names into one line.

When a skill used Notion MCP rows or SQL mode, add `- Notion: view-mode reads <n>, rows/SQL lookups <n>` and say if the workspace query allowance ran out (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows).

## Common header

```
## YYYY-MM-DD HH:MM <timezone> — <skill> (<mode>)
```

`<mode>` is `live` or `dry-run` for campaign-run. Other skills leave it out on a normal run and write `(dry-run)` after the skill name on a dry run. Use `owner.timezone`.

## Per skill

### setup

```
## YYYY-MM-DD HH:MM <timezone> — setup
- BLOCKED: <adapter — what happened — fix>
- Needs you: <...>
- Decisions: <...>
- Notion: <created | mapped> databases <names>; access <mcp | rest>
- Adapters: <kind: tool — ok | blocked>
- Files: config.json <written | updated>, voice.md <...>, icp.md <...>
- Schedules: <routine — when — where (local scheduled task | /schedule | /loop | none)>
```

### import

```
## YYYY-MM-DD HH:MM <timezone> — import
- BLOCKED / Needs you / Decisions
- Source: <csv file name | hubspot | pipedrive | attio> via <MCP connector | readonly_api | CSV>
- Plan: rows <n>, create <n>, update <n>, unchanged <n>, skip <n>, conflict <n>; companies new <n>
- Applied: created <n>, updated <n>, unchanged <n>, failed <n>; verified <n of n>
- Conflicts left for you: <row — reason>
```

### sweep

```
## YYYY-MM-DD HH:MM <timezone> — sweep
- BLOCKED / Needs you / Decisions
- <adapter>: <n items read>, <n matched>, <changes> | incomplete: <why> | blocked: <reason>   (one line per adapter)
- CRM changes: <contact — old Status → new Status — reason>; mismatches: <contact — what>
- Pages created: <n contacts, n companies, n campaigns> (outreach mirrors), <n meetings> (meeting recorders)
- First Contacted set: <n>
- Unmatched: <count by source>; <at most 10 of: name or address — source — date>; and <n> more
- Notion: view-mode reads <n>, rows/SQL lookups <n>   (MCP path only)
- Cursors moved: <adapters>; kept: <adapters>; held back: <adapter — to date — why>
```

### campaign-build

```
## YYYY-MM-DD HH:MM <timezone> — campaign-build
- BLOCKED / Needs you / Decisions
- Campaign: <name> (<campaign_key>), Status Review
- Audience: <n found>, <n added>, <n already in CRM>, <n excluded by ICP or DNC>
- Enrichment: <adapter — n emails found — n verified>; credits spent: <adapter n of limit>
- Contacts linked to campaign: <n>
- Dropped: <reason — n> (one line per reason)
```

### campaign-write

```
## YYYY-MM-DD HH:MM <timezone> — campaign-write
- BLOCKED / Needs you / Decisions
- Campaign: <name> (<campaign_key>), Status Review
- Steps written: <n> (<step — channel — trigger>)
- Personalization: <n contact pages with Run fields>, <n with per-contact copy>, <n skipped — reason>
- Coverage: <step — n contacts campaign-run will skip — reason>
- Voice: <voice file | none> ; voice skill: <name | none> ; sign-off: <as in voice file | none>
- Research credits: <tool n of limit> | none
```

### campaign-run

```
## YYYY-MM-DD HH:MM <timezone> — campaign-run (<live | dry-run>)
- BLOCKED / Needs you / Decisions
- Campaigns run: <name — contacts — sends by step>
- Plan: <per campaign: step, trigger, channel, condition, copy source, approval>
- Campaigns skipped: <name — reason (not Active, Warm Intro, Runs: external, no key, cannot parse)>
- Replies found: <contact — channel — class — action>
- Sent: <step: n> ... | verified <n of n>
- Skipped steps: <contact — step — reason (gate, no email, no LinkedIn, capped, not a working day, outside window, blocked)>
- Failed sends: <contact — step — error>
- Reconcile: <mismatches or none>
```

### funnel

```
## YYYY-MM-DD HH:MM <timezone> — funnel
- BLOCKED / Needs you / Decisions
- As of: YYYY-MM-DD; published: <yes | no — reason>
- Totals: <table — stage counts>
- Changed since last run: <...>
- Blank First Contacted: <n contacts left out>
```

## Final report in the chat

Same order: BLOCKED, Needs you, Decisions, then the counts. Keep it short and link the pages. If nothing happened, say so in one line.
