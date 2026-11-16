# Funnel definitions

What the funnel counts. All names below are logical; resolve them through `notion.status_map`, `notion.option_map` and `funnel.*` in the gtm config. This file is the source of truth for both hand counts (`${CLAUDE_PLUGIN_ROOT}/skills/funnel/SKILL.md`). Tessary GTM Pro counts the same way with a script, so the tables, the checks and the baseline agree across editions.

## Who is counted

- Counted contacts have Status `Contacted`, `Responded`, `Discovery` or `Lead`. `New` and the terminal statuses (`Archived`, `Do Not Contact`, `Disqualified`) are not counted.
- A Status value that is not in `notion.status_map` is left out and reported as a note.
- Each contact counts once, in the month of its First Contacted date. A counted contact with a blank First Contacted is listed under Needs you and left out of the tables.
- Contacts dated before `funnel.start_month` are left out (counted in the summary). When `start_month` is null, the tables start at the earliest First Contacted month of a counted contact. When no counted contact has a First Contacted date yet (for example right after an import), the tables have one row, the current month, with every count 0.

## Tables

| Table | Who |
|---|---|
| Cold outbound | Counted contacts whose Lead Source is not in `funnel.warm_lead_sources` or `funnel.inbound_lead_sources`. A blank Lead Source is cold. |
| Warm outbound | Counted contacts whose Lead Source is in `funnel.warm_lead_sources` (default `Warm Intro`). |
| Inbound (optional) | Metrics from an inbound adapter (see Inbound hook). Contacts whose Lead Source is in `funnel.inbound_lead_sources` are in neither outbound table. |

## Stages

| Stage | Cold | Warm |
|---|---|---|
| Contacted (warm: Intro) | every counted contact | same |
| Responded | Status `Responded` or later, or a Pilot / Trial deal | not shown |
| Discovery | Status `Discovery` or later, or a Pilot / Trial deal | same |
| Pilot / Trial | a linked deal at a stage in `funnel.pilot_stages` or `funnel.customer_stages` | same |
| Customer | a linked deal at a stage in `funnel.customer_stages` | same |

- Responded means a real reply on email or LinkedIn. A LinkedIn accept is not a reply (`${CLAUDE_PLUGIN_ROOT}/reference/crm-rules.md`).
- A deal link is read from both sides of the relation (`contacts.deal` and `pipeline.contacts`). The best stage of all linked deals counts.
- Columns alternate a stage count and the conversion to the next stage. Each percentage is the next stage divided by this stage, with one decimal; `–` when this stage is 0.
- Rows: latest month first, then a `Total` row. The current month is labelled `(to date)`, and the first line of the page says it is a partial month.

## Checks

`funnel_checks.txt` is `ok`, or one line per failed check. The skill publishes only on `ok`.

| Check | Fails when |
|---|---|
| Empty export | The contacts export has no rows. |
| Missing property | A mapped contacts property (`status`, `lead_source`, `first_contacted`, `deal`) is not in the Contacts data source schema, or a mapped pipeline property (`stage`, `contacts`) is not in the Pipeline data source schema. `notion-fetch` each data source once to read its schema. Do not check the rows for this: the connector leaves out empty properties, so a property that no row has (for example First Contacted right after an import) is blank, not missing. This usually means a wrong `field_map`. |
| Missing ids | Some rows have no page id or URL. |
| Blanks | More than `funnel.max_blank_pct` percent of counted contacts, and at least 3, have a blank First Contacted. |
| Drop | A count for a past month in the cold or warm table fell by more than `funnel.drop_tolerance_pct` percent against the baseline (default: any drop). |
| Rise | A count for a past month rose by more than `funnel.rise_tolerance_pct` percent (default 25; null turns it off). |
| Inbound gaps | An inbound file was given and has no data for a month in the table. |

The current month is never part of the drop and rise checks, because it is still filling. Inbound numbers are never part of them either, because traffic sources revise recent days.

## Baseline

- The baseline is the last accepted run's counts. It lives in `state.json` in the active config folder under `adapters.funnel`. Only the funnel skill writes it.
- Save it only after every check passed and the publish was verified, and never on a dry run.
- `accept-baseline` records the drop and rise checks as accepted, saves this run as the new baseline, and leaves the other checks in force. Use it only when the user asks.
- The first run has no baseline: the delta says `no baseline yet (first run)`, and no drop or rise check runs.
- The delta lists every count that changed against the baseline, also in the current month, one line each: `<table> <YYYY-MM> <stage>: <old> -> <new>`. With no change it says `no changes since last run`.
- Shape, the same as Tessary GTM Pro writes, so either edition can read it. Write a zero for a stage that has none:

  ```json
  {
    "as_of": "2026-03-18",
    "months": ["2026-02", "2026-03"],
    "tables": {
      "cold": {"2026-02": {"contacted": 9, "responded": 3, "discovery": 1, "pilot": 0, "customer": 0},
               "2026-03": {"contacted": 4, "responded": 1, "discovery": 0, "pilot": 0, "customer": 0}},
      "warm": {"2026-02": {"contacted": 2, "discovery": 1, "pilot": 0, "customer": 0},
               "2026-03": {"contacted": 0, "discovery": 0, "pilot": 0, "customer": 0}}
    },
    "inbound": null
  }
  ```

## Page format

`funnel_tables.md` is the page text, in this exact format:

1. First line: `As of <YYYY-MM-DD>. <Mon YYYY> is a partial month.` (today in `owner.timezone`, and the current month as a three-letter month and the year, for example `Mar 2026`).
2. A blank line, `## Cold outbound`, a blank line, then the cold table with the header `| Month | Contacted | Contacted to Responded | Responded | Responded to Discovery | Discovery | Discovery to Pilot | Pilot / Trial | Pilot to Customer | Customer |`.
3. A blank line, `## Warm outbound`, a blank line, then the warm table with the header `| Month | Intro | Intro to Discovery | Discovery | Discovery to Pilot | Pilot / Trial | Pilot to Customer | Customer |`.
4. Each header is followed by a separator row: `|`, then `---|` once per column. Then one row per month from the start month to the current month, latest first, every month present even when all its counts are 0. The current month is labelled `<Mon YYYY> (to date)`. Then a `Total` row with the sum of each count column.
5. Counts are whole numbers with a comma for thousands. A percentage is the next stage divided by this stage, times 100, with one decimal and a `%` sign (for example `33.3%`), or `–` when this stage is 0. In the Total row, compute each percentage from the totals, never as an average of the months.

## Inbound hook

No inbound adapter ships, and this edition counts no inbound table. If `funnel.inbound` names a tool, leave the inbound table out, publish the outbound tables, and report it under Needs you.
