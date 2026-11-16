# Funnel definitions

What `lib/funnel.py` counts. All names below are logical; the script resolves them through `notion.status_map`, `notion.option_map` and `funnel.*` in the gtm config. The script is the source of truth; this file explains it.

## Who is counted

- Counted contacts have Status `Contacted`, `Responded`, `Discovery` or `Lead`. `New` and the terminal statuses (`Archived`, `Do Not Contact`, `Disqualified`) are not counted.
- A Status value that is not in `notion.status_map` is left out and reported as a note.
- Each contact counts once, in the month of its First Contacted date. A counted contact with a blank First Contacted is listed in `funnel_blanks.txt` and left out of the tables.
- Contacts dated before `funnel.start_month` are left out (counted in the summary). When `start_month` is null, the tables start at the earliest First Contacted month.

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
| Missing property | A mapped property (`status`, `lead_source`, `first_contacted`; deals `stage`) is not in any exported row, or neither side of the deal relation is. This usually means a wrong `field_map` or an incomplete MCP export. |
| Missing ids | Some rows have no page id or URL. |
| Blanks | More than `funnel.max_blank_pct` percent of counted contacts, and at least 3, have a blank First Contacted. |
| Drop | A count for a past month in the cold or warm table fell by more than `funnel.drop_tolerance_pct` percent against the baseline (default: any drop). |
| Rise | A count for a past month rose by more than `funnel.rise_tolerance_pct` percent (default 25; null turns it off). |
| Inbound gaps | An inbound file was given and has no data for a month in the table. |

The current month is never part of the drop and rise checks, because it is still filling. Inbound numbers are never part of them either, because traffic sources revise recent days.

## Baseline

- The baseline is the last accepted run's counts. It lives in the state file (the `state` path printed by `config.py paths`) under `adapters.funnel`. Only `lib/funnel.py` writes it.
- The script saves it only when every check passes (and `--no-save-baseline` is not given).
- `--accept-baseline` records the drop and rise checks as accepted, saves this run as the new baseline, and leaves the other checks in force. Use it only when the user asks.
- The first run has no baseline: `funnel_delta.txt` says so, and no drop or rise check runs.
- `funnel_delta.txt` lists every count that changed against the baseline, also in the current month and in inbound.

## Output files

| File | Holds |
|---|---|
| `funnel_tables.md` | The page text: the "As of" line and the tables. Published as written. |
| `funnel_checks.txt` | `ok` or failed checks. |
| `funnel_delta.txt` | Changes since the baseline, `no changes since last run`, or `no baseline yet (first run)`. |
| `funnel_blanks.txt` | `name | status | lead source | page id` per blank contact, or `none`. |
| `funnel_summary.json` | `as_of`, `partial_month`, `months`, `totals` per table, `counts`, `checks`, `accepted_baseline_checks`, `notes`, `baseline_saved`. Use it for the report. |

## Inbound hook

No inbound adapter ships in v1. The hook exists so one can be added later without changing the script.

- An inbound adapter is a file `${CLAUDE_PLUGIN_ROOT}/adapters/inbound/<tool>.md` that the user turns on by adding `<tool>` to `funnel.inbound`. It follows `${CLAUDE_PLUGIN_ROOT}/adapters/README.md` (read-only, preflight, blocked signs).
- Its read procedure writes one JSON file for the funnel run:

  ```json
  {
    "source": "<tool>",
    "metrics": ["impressions", "clicks", "signups"],
    "months": {"2026-03": {"impressions": 1200, "clicks": 40, "signups": 3}}
  }
  ```

  `metrics` is the column order. Every month in the table must be present (an empty month is an object of zeros), or the inbound check fails.
- The skill passes it with `--inbound <file>`. The script adds an `## Inbound` table with one column per metric and the conversion between neighbouring metrics.
- With several inbound adapters, the adapter files must agree on one combined file; the script takes one `--inbound` file.
- If `funnel.inbound` names a tool with no adapter file, or the adapter is blocked, run without `--inbound` and report it under BLOCKED. The outbound tables still publish.
