#!/usr/bin/env python3
"""Count the monthly gtm funnel tables from a JSON export of the Notion CRM.

The model never counts. This script does all counting, from an export of
Contacts and Pipeline (deals) rows, and writes the tables that /gtm:funnel
publishes. It never writes to Notion. Python 3 stdlib only. Run as python3 -I.

Commands:

  funnel.py export [--out DIR]
      REST only (needs the notion_token secret). Reads every Contacts and
      Pipeline row and writes DIR/contacts.json and DIR/deals.json in the
      export format below. Without a token, /gtm:funnel builds the same two
      files from Notion MCP query results instead.

  funnel.py run --contacts F [--contacts F2 ...] --deals F [--deals F2 ...]
                [--out DIR] [--inbound F]
                [--today YYYY-MM-DD] [--accept-baseline] [--no-save-baseline]
      Repeat --contacts or --deals to pass several query result files (one per
      MCP query page); rows are deduplicated by page id. Counts the tables and writes to DIR:
        funnel_tables.md    the page text to publish (As of line + tables)
        funnel_checks.txt   "ok", or one failed check per line. Publish only on ok.
        funnel_delta.txt    every count that changed since the baseline
        funnel_blanks.txt   counted contacts with no First Contacted date, or "none"
        funnel_summary.json totals and notes for the run report
      The baseline (last accepted counts) lives in ~/.config/gtm/state.json
      under adapters.funnel. It is saved only when every check passes, or
      with --accept-baseline (use it only when the user asks). With
      --accept-baseline, baseline drop and rise checks are recorded as
      accepted; the other checks still apply. --no-save-baseline never saves
      it (for a dry run that does not publish).

  funnel.py self-test
      Runs the script on synthetic data in a temporary config folder and
      checks the counts. Touches no real file.

Export format (contacts.json and deals.json): a JSON array of rows, or an
object with a "results" or "rows" array. Each row is one page, keyed by the
actual Notion property names from config notion.field_map. These row shapes
are all accepted, also mixed in one file:
  - notion_rest.py --simple rows: {"_id": ..., "Status": "Contacted", "Deal": ["<id>"], ...}
  - raw Notion REST pages: {"id": ..., "properties": {...}}
  - Notion MCP query rows: {"url": ..., "Status": ..., "date:First Contacted:start": ...,
    "Deal": "[\\"https://www.notion.so/...\\"]"}
Relation values may be page ids, page URLs, a list of either, or a JSON
string of such a list. Only these fields are read: contacts name, status,
lead_source, first_contacted, deal; pipeline stage, contacts.

Inbound hook (--inbound F, optional): a JSON object
  {"source": "<adapter name>", "metrics": ["impressions", "clicks", ...],
   "months": {"YYYY-MM": {"impressions": 120, "clicks": 9}, ...}}
written by an inbound adapter the user enabled (config funnel.inbound). The
script adds an Inbound table with one column per metric, in the given order,
and a conversion % between neighbouring metrics. Inbound numbers are never
part of the baseline checks, because traffic sources revise recent days.

Definitions (logical names, resolved through config):
  Counted contacts: Status Contacted, Responded, Discovery or Lead. New and
    the terminal statuses (Archived, Do Not Contact, Disqualified) are left out.
  Month: the month of First Contacted. Blank First Contacted: listed in
    funnel_blanks.txt and left out.
  Warm: Lead Source in funnel.warm_lead_sources. Inbound-sourced contacts
    (funnel.inbound_lead_sources) are left out of both tables. Cold: the rest,
    including a blank Lead Source.
  Contacted: every counted contact.
  Responded (cold only): Status Responded or later, or a Pilot / Trial deal.
  Discovery: Status Discovery or later, or a Pilot / Trial deal.
  Pilot / Trial: a linked deal at a stage in funnel.pilot_stages or
    funnel.customer_stages (relation read from both sides).
  Customer: a linked deal at a stage in funnel.customer_stages.
  Each % is the next stage divided by this stage.

Exit codes: 0 done (read funnel_checks.txt for ok), 1 bad input or config,
2 Notion error during export.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as gtm_config  # noqa: E402

COUNTED = ("Contacted", "Responded", "Discovery", "Lead")
RESPONDED = ("Responded", "Discovery", "Lead")
DISCOVERY = ("Discovery", "Lead")
STATE_KEY = "funnel"
CHECKED_TABLES = ("cold", "warm")
BLANK_MIN_COUNT = 3
_ID_RE = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")

COLD_STAGES = ("contacted", "responded", "discovery", "pilot", "customer")
WARM_STAGES = ("contacted", "discovery", "pilot", "customer")
COLD_HEADER = ["Month", "Contacted", "Contacted to Responded", "Responded", "Responded to Discovery",
               "Discovery", "Discovery to Pilot", "Pilot / Trial", "Pilot to Customer", "Customer"]
WARM_HEADER = ["Month", "Intro", "Intro to Discovery", "Discovery", "Discovery to Pilot",
               "Pilot / Trial", "Pilot to Customer", "Customer"]


class InputError(Exception):
    """Bad export file, bad argument or bad config."""


# ---------------------------------------------------------------- row reading

def page_id(value) -> str | None:
    """Last Notion id found in a string (id or URL), as 32 lower-case hex chars."""
    if not isinstance(value, str):
        return None
    found = _ID_RE.findall(value)
    return found[-1].replace("-", "").lower() if found else None


def _rich_plain(items) -> str:
    return "".join((x.get("plain_text") or (x.get("text") or {}).get("content") or "") for x in items or [])


def _rest_value(prop):
    """Plain value of a raw REST property object."""
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in ("title", "rich_text"):
        return _rich_plain(value)
    if kind in ("select", "status"):
        return value.get("name") if value else None
    if kind == "date":
        return value.get("start") if value else None
    if kind == "relation":
        return [v.get("id") for v in value or []]
    return value


def normalize_row(row: dict) -> dict:
    """Flatten any accepted row shape to {name: plain value, '_id': hex id}."""
    if not isinstance(row, dict):
        raise InputError("each export row must be a JSON object")
    out = {}
    if isinstance(row.get("properties"), dict):
        for name, prop in row["properties"].items():
            out[name] = _rest_value(prop) if isinstance(prop, dict) and "type" in prop else prop
        for key in ("id", "url"):
            if key in row:
                out.setdefault("_" + key, row[key])
    else:
        out.update(row)
    pid = None
    for key in ("_id", "id", "_url", "url"):
        pid = page_id(out.get(key)) if isinstance(out.get(key), str) else None
        if pid:
            break
    out["_id"] = pid
    return out


def has_prop(row: dict, name: str) -> bool:
    return name in row or f"date:{name}:start" in row


def get_text(row: dict, name: str):
    value = row.get(name)
    if isinstance(value, dict):
        value = _rest_value(value) if "type" in value else value.get("name") or value.get("start")
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if v)
    if value is None or value == "":
        return None
    return str(value).strip() or None


def get_date(row: dict, name: str):
    value = row.get(f"date:{name}:start")
    if value in (None, ""):
        value = row.get(name)
    if isinstance(value, dict):
        value = value.get("start") or (value.get("date") or {}).get("start")
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return None
    return value[:10]


def get_relation(row: dict, name: str) -> list:
    value = row.get(name)
    if isinstance(value, dict) and "type" in value:
        value = _rest_value(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                value = _ID_RE.findall(text)
        else:
            value = [part for part in re.split(r"[,\s]+", text) if part]
    ids = []
    for item in value or []:
        if isinstance(item, dict):
            item = item.get("id") or item.get("url")
        pid = page_id(item) if isinstance(item, str) else None
        if pid:
            ids.append(pid)
    return ids


def load_all(paths) -> list:
    """Rows from one or more export files, deduplicated by page id (first wins)."""
    rows, seen = [], set()
    for path in paths:
        for row in load_rows(path):
            if row["_id"] and row["_id"] in seen:
                continue
            seen.add(row["_id"])
            rows.append(row)
    return rows


def load_rows(path) -> list:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON (line {exc.lineno})") from None
    if isinstance(data, dict):
        for key in ("results", "rows", "pages", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise InputError(f"{path} must hold a JSON array of rows")
    return [normalize_row(r) for r in data]


# ---------------------------------------------------------------- helpers

def months_range(start: str, end: str) -> list:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def pct(n, d) -> str:
    return "–" if not d else f"{100.0 * n / d:.1f}%"


def num(n) -> str:
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,}"


def month_label(m: str, this_month: str) -> str:
    s = datetime.date(int(m[:4]), int(m[5:]), 1).strftime("%b %Y")
    return s + " (to date)" if m == this_month else s


def today_in(tz_name: str) -> datetime.date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc).date()


def actual_options(cfg, database, logical_field, names, notes, key):
    """Map logical option names to actual ones; unmapped names are used as they are."""
    mapping = ((cfg["notion"].get("option_map") or {}).get(database) or {}).get(logical_field) or {}
    out = set()
    for name in names:
        if name in mapping and mapping[name]:
            out.add(mapping[name])
        else:
            out.add(name)
            notes.append(f"{key} {name!r} has no option_map.{database}.{logical_field} entry; used as the actual option name")
    return out


# ---------------------------------------------------------------- counting

def compute(cfg: dict, contacts: list, deals: list, today: datetime.date, inbound=None) -> dict:
    fm = cfg["notion"]["field_map"]
    fn = cfg.get("funnel") or {}
    notes, checks = [], []

    def prop(db, logical):
        name = (fm.get(db) or {}).get(logical)
        if not name:
            raise InputError(f"config has no notion.field_map.{db}.{logical}")
        return name

    c_name, c_status = prop("contacts", "name"), prop("contacts", "status")
    c_source, c_first = prop("contacts", "lead_source"), prop("contacts", "first_contacted")
    c_deal = prop("contacts", "deal")
    d_stage, d_contacts = prop("pipeline", "stage"), prop("pipeline", "contacts")

    # Export sanity: the mapped properties must exist in the export.
    if not contacts:
        checks.append("the contacts export is empty; check the Contacts data source id and the export step")
    else:
        for logical, name in (("status", c_status), ("lead_source", c_source), ("first_contacted", c_first)):
            if not any(has_prop(r, name) for r in contacts):
                checks.append(f"property {name!r} (notion.field_map.contacts.{logical}) is not in the contacts export")
    if deals:
        if not any(has_prop(r, d_stage) for r in deals):
            checks.append(f"property {d_stage!r} (notion.field_map.pipeline.stage) is not in the deals export")
        if not any(has_prop(r, d_contacts) for r in deals) and not any(has_prop(r, c_deal) for r in contacts):
            checks.append(f"no deal relation in the export: neither {d_contacts!r} on deals nor {c_deal!r} on contacts")
    if any(not r["_id"] for r in contacts) or any(not r["_id"] for r in deals):
        checks.append("some export rows have no page id or URL")

    status_actual = {cfg["notion"]["status_map"][s]: s for s in cfg["notion"]["status_map"]}
    customer = actual_options(cfg, "pipeline", "stage", fn.get("customer_stages") or [], notes, "funnel.customer_stages")
    pilot = actual_options(cfg, "pipeline", "stage", fn.get("pilot_stages") or [], notes, "funnel.pilot_stages") | customer
    warm_src = actual_options(cfg, "contacts", "lead_source", fn.get("warm_lead_sources") or [], notes,
                              "funnel.warm_lead_sources")
    inbound_src = actual_options(cfg, "contacts", "lead_source", fn.get("inbound_lead_sources") or [], notes,
                                 "funnel.inbound_lead_sources")

    # Best deal level per contact, from both sides of the relation: 1 pilot, 2 customer.
    level = {}

    def note_deal(cid, stage):
        lv = 2 if stage in customer else 1 if stage in pilot else 0
        if lv > level.get(cid, 0):
            level[cid] = lv

    deal_stage, seen_stages = {}, collections.Counter()
    for d in deals:
        st = get_text(d, d_stage)
        deal_stage[d["_id"]] = st
        seen_stages[st] += 1
        for cid in get_relation(d, d_contacts):
            note_deal(cid, st)
    for c in contacts:
        for did in get_relation(c, c_deal):
            note_deal(c["_id"], deal_stage.get(did))
    if deals and not any(s in pilot for s in seen_stages):
        notes.append("no deal is at a Pilot / Trial or Customer stage; check funnel.pilot_stages and "
                     "funnel.customer_stages if that is wrong (stages seen: "
                     + ", ".join(f"{s or 'blank'} {n}" for s, n in sorted(seen_stages.items(), key=lambda x: str(x[0])))
                     + ")")

    unknown_status = collections.Counter()
    counted, blanks = [], []
    for c in contacts:
        actual = get_text(c, c_status)
        logical = status_actual.get(actual)
        if actual and logical is None:
            unknown_status[actual] += 1
        if logical not in COUNTED:
            continue
        source = get_text(c, c_source)
        first = get_date(c, c_first)
        if not first:
            blanks.append(f"{get_text(c, c_name) or '(no name)'} | {logical} | {source or '(no lead source)'} | {c['_id']}")
            continue
        counted.append((c, logical, source, first))
    if unknown_status:
        notes.append("Status values not in notion.status_map, left out: "
                     + ", ".join(f"{k} ({v})" for k, v in sorted(unknown_status.items())))

    this_month = today.strftime("%Y-%m")
    start = fn.get("start_month") or (min(f[:7] for _, _, _, f in counted) if counted else this_month)
    if start > this_month:
        start = this_month
    months = months_range(start, this_month)

    tables = {"cold": {m: collections.Counter() for m in months},
              "warm": {m: collections.Counter() for m in months}}
    before_start, after_today, inbound_contacts = 0, 0, 0
    for c, logical, source, first in counted:
        m = first[:7]
        if source in inbound_src:
            inbound_contacts += 1
            continue
        if m < start:
            before_start += 1
            continue
        if m > this_month:
            after_today += 1
            continue
        lv = level.get(c["_id"], 0)
        row = tables["warm" if source in warm_src else "cold"][m]
        row["contacted"] += 1
        row["responded"] += logical in RESPONDED or lv > 0
        row["discovery"] += logical in DISCOVERY or lv > 0
        row["pilot"] += lv > 0
        row["customer"] += lv == 2
    if after_today:
        notes.append(f"{after_today} contacts have a First Contacted date after today; left out")

    counted_n = len(counted) + len(blanks)
    max_blank_pct = fn.get("max_blank_pct", 10)
    if blanks and len(blanks) >= BLANK_MIN_COUNT and 100.0 * len(blanks) / max(counted_n, 1) > max_blank_pct:
        checks.append(f"{len(blanks)} of {counted_n} counted contacts have a blank "
                      f"{c_first!r} (more than {max_blank_pct}%); see funnel_blanks.txt")

    inbound_table = None
    if inbound is not None:
        inbound_table = build_inbound(inbound, months, checks)

    return {"as_of": today.isoformat(), "this_month": this_month, "months": months,
            "tables": {k: {m: dict(v) for m, v in t.items()} for k, t in tables.items()},
            "inbound": inbound_table, "checks": checks, "notes": notes, "blanks": blanks,
            "counts": {"contacts": len(contacts), "deals": len(deals), "counted": counted_n,
                       "contacts_with_pilot_or_customer_deal": sum(1 for v in level.values() if v),
                       "blank_first_contacted": len(blanks), "before_start_month": before_start,
                       "inbound_sourced_contacts": inbound_contacts}}


def build_inbound(inbound: dict, months: list, checks: list):
    if not isinstance(inbound, dict) or not isinstance(inbound.get("metrics"), list) \
            or not isinstance(inbound.get("months"), dict) or not inbound["metrics"]:
        raise InputError("the inbound file needs 'metrics' (a list) and 'months' (an object)")
    metrics = [str(m) for m in inbound["metrics"]]
    missing = [m for m in months if m not in inbound["months"]]
    if missing:
        checks.append(f"inbound source {inbound.get('source') or 'unknown'} has no data for: " + ", ".join(missing))
    rows = {}
    for m in months:
        src = inbound["months"].get(m) or {}
        rows[m] = {k: src.get(k, 0) if isinstance(src.get(k, 0), (int, float)) else 0 for k in metrics}
    return {"source": inbound.get("source") or "", "metrics": metrics, "rows": rows}


# ---------------------------------------------------------------- rendering

def _total(rows: dict) -> collections.Counter:
    t = collections.Counter()
    for r in rows.values():
        t.update(r)
    return t


def _table(header, rows, months, this_month, cells) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for m in reversed(months):
        lines.append("| " + " | ".join([month_label(m, this_month)] + cells(rows[m])) + " |")
    lines.append("| " + " | ".join(["Total"] + cells(_total(rows))) + " |")
    return "\n".join(lines)


def _stage_cells(stages):
    def cells(r):
        out = []
        for i, s in enumerate(stages):
            out.append(num(r.get(s, 0)))
            if i + 1 < len(stages):
                out.append(pct(r.get(stages[i + 1], 0), r.get(s, 0)))
        return out
    return cells


def render(result: dict) -> str:
    months, tm = result["months"], result["this_month"]
    t = result["tables"]
    parts = [f"As of {result['as_of']}. {month_label(tm, tm).replace(' (to date)', '')} is a partial month.",
             "## Cold outbound", _table(COLD_HEADER, t["cold"], months, tm, _stage_cells(COLD_STAGES)),
             "## Warm outbound", _table(WARM_HEADER, t["warm"], months, tm, _stage_cells(WARM_STAGES))]
    inbound = result.get("inbound")
    if inbound:
        metrics = inbound["metrics"]
        header = ["Month"]
        for i, m in enumerate(metrics):
            header.append(m.replace("_", " ").capitalize())
            if i + 1 < len(metrics):
                header.append(f"{metrics[i].replace('_', ' ').capitalize()} to "
                              f"{metrics[i + 1].replace('_', ' ').capitalize()}")
        parts += ["## Inbound", _table(header, inbound["rows"], months, tm, _stage_cells(metrics))]
    return "\n\n".join(parts) + "\n"


def totals(result: dict) -> dict:
    out = {k: dict(_total(v)) for k, v in result["tables"].items()}
    if result.get("inbound"):
        out["inbound"] = dict(_total(result["inbound"]["rows"]))
    return out


# ---------------------------------------------------------------- baseline

def compare(result: dict, baseline, fn: dict):
    """Return (delta lines, baseline check lines)."""
    if not baseline or not isinstance(baseline.get("tables"), dict):
        return ["no baseline yet (first run)"], []
    drop_tol = float(fn.get("drop_tolerance_pct", 0) or 0)
    rise_tol = fn.get("rise_tolerance_pct", 25)
    delta, checks = [], []
    for table in CHECKED_TABLES:
        old_t = baseline["tables"].get(table) or {}
        for m in result["months"]:
            if m not in old_t:
                continue
            new_r, old_r = result["tables"][table].get(m, {}), old_t.get(m) or {}
            for k in sorted(set(new_r) | set(old_r)):
                new, old = new_r.get(k, 0), old_r.get(k, 0)
                if new == old:
                    continue
                delta.append(f"{table} {m} {k}: {old} -> {new}")
                if m == result["this_month"]:
                    continue
                if new < old and (old - new) * 100.0 / old > drop_tol:
                    checks.append(f"{table} {m} {k} went down: {old} -> {new}")
                elif new > old and rise_tol is not None and old and (new - old) * 100.0 / old > float(rise_tol):
                    checks.append(f"{table} {m} {k} rose more than {rise_tol}%: {old} -> {new}")
    old_inb = (baseline.get("inbound") or {}).get("rows") or {}
    new_inb = (result.get("inbound") or {}).get("rows") or {}
    for m in result["months"]:
        if m not in old_inb or m not in new_inb:
            continue
        for k in sorted(set(new_inb[m]) | set(old_inb[m])):
            new, old = new_inb[m].get(k, 0), old_inb[m].get(k, 0)
            if new != old:
                delta.append(f"inbound {m} {k}: {old} -> {new}")
    return delta or ["no changes since last run"], checks


# ---------------------------------------------------------------- commands

def cmd_run(args) -> int:
    cfg = gtm_config.load()
    fn = cfg.get("funnel") or {}
    if args.today:
        try:
            today = datetime.date.fromisoformat(args.today)
        except ValueError:
            raise InputError("--today must be YYYY-MM-DD") from None
    else:
        today = today_in((cfg.get("owner") or {}).get("timezone") or "UTC")
    contacts, deals = load_all(args.contacts), load_all(args.deals)
    inbound = None
    if args.inbound:
        try:
            with open(args.inbound, encoding="utf-8") as handle:
                inbound = json.load(handle)
        except (OSError, json.JSONDecodeError):
            raise InputError(f"cannot read the inbound file {args.inbound}") from None
    result = compute(cfg, contacts, deals, today, inbound)

    state = gtm_config.load_state()
    baseline = (state.get("adapters") or {}).get(STATE_KEY)
    delta, base_checks = compare(result, baseline, fn)
    checks = list(result["checks"])
    accepted = []
    if args.accept_baseline:
        accepted = base_checks
    else:
        checks += base_checks

    out = Path(args.out).expanduser() if args.out else gtm_config.config_dir() / "funnel"
    out.mkdir(parents=True, exist_ok=True)
    md = render(result)
    (out / "funnel_tables.md").write_text(md, encoding="utf-8")
    (out / "funnel_checks.txt").write_text(("\n".join(checks) or "ok") + "\n", encoding="utf-8")
    (out / "funnel_delta.txt").write_text("\n".join(delta) + "\n", encoding="utf-8")
    (out / "funnel_blanks.txt").write_text(("\n".join(result["blanks"]) or "none") + "\n", encoding="utf-8")

    saved = False
    if not checks and not args.no_save_baseline:
        gtm_config.set_state(STATE_KEY, {"as_of": result["as_of"], "months": result["months"],
                                         "tables": result["tables"], "inbound": result["inbound"]})
        saved = True
    summary = {"as_of": result["as_of"], "partial_month": result["this_month"], "months": result["months"],
               "totals": totals(result), "counts": result["counts"], "checks": checks or ["ok"],
               "accepted_baseline_checks": accepted, "notes": result["notes"], "baseline_saved": saved,
               "out_dir": str(out)}
    (out / "funnel_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(md)
    print("counts: " + ", ".join(f"{k}={v}" for k, v in result["counts"].items()))
    for n in result["notes"]:
        print("note: " + n)
    if accepted:
        print("accepted baseline changes: " + "; ".join(accepted))
    print("CHECKS: " + ("; ".join(checks) or "ok"))
    print(f"baseline saved: {'yes' if saved else 'no'}")
    print(f"files: {out}")
    return 0


def cmd_export(args) -> int:
    import notion_rest  # noqa: E402  (same folder; imported only for export)
    cfg = gtm_config.load()
    if not gtm_config.get_secret("notion_token"):
        print("error: no notion_token saved; export through Notion MCP instead "
              "(see skills/funnel/references/export.md)", file=sys.stderr)
        return 1
    ds = cfg["notion"].get("data_sources") or {}
    out = Path(args.out).expanduser() if args.out else gtm_config.config_dir() / "funnel"
    out.mkdir(parents=True, exist_ok=True)
    for db, filename in (("contacts", "contacts.json"), ("pipeline", "deals.json")):
        if not ds.get(db):
            print(f"error: notion.data_sources.{db} is empty; run /gtm:setup", file=sys.stderr)
            return 1
        try:
            pages = notion_rest.query_data_source(ds[db])
        except notion_rest.NotionAPIError as exc:
            print(f"error: Notion refused the {db} query: status {getattr(exc, 'status', '?')}", file=sys.stderr)
            return 2
        except Exception:  # never print the exception text of an authenticated call
            print(f"error: could not read the {db} data source from Notion", file=sys.stderr)
            return 2
        rows = [notion_rest.simplify_properties(p) for p in pages]
        (out / filename).write_text(json.dumps(rows) + "\n", encoding="utf-8")
        print(f"{db}: {len(rows)} rows -> {out / filename}")
    return 0


# ---------------------------------------------------------------- self-test

def _self_test_data():
    """Synthetic CRM with renamed properties, mixed row shapes and every edge case."""
    def cid(n):
        return f"{n:08x}" + "0" * 24
    contacts = [
        # REST --simple rows (warm and cold), dates in Feb and Mar 2030
        {"_id": cid(1), "Person": "A", "Stage of contact": "Reached", "Source": "Outbound",
         "First touch": "2030-02-03", "Deals": []},
        {"_id": cid(2), "Person": "B", "Stage of contact": "Replied", "Source": None,
         "First touch": "2030-02-10", "Deals": []},
        {"_id": cid(3), "Person": "C", "Stage of contact": "Meeting", "Source": "Outbound",
         "First touch": "2030-02-11T10:00:00.000+00:00", "Deals": []},
        # pilot through the contact-side relation, status only Contacted: still counts as responded
        {"_id": cid(4), "Person": "D", "Stage of contact": "Reached", "Source": "Outbound",
         "First touch": "2030-02-12", "Deals": ["d" + "1" * 31]},
        # MCP row shape: url id, split date key, relation as a JSON string of URLs
        {"url": f"https://www.notion.so/E-{cid(5)}", "Person": "E", "Stage of contact": "Handed over",
         "Source": "Referral", "date:First touch:start": "2030-03-01",
         "Deals": json.dumps([f"https://www.notion.so/Deal-{'d' + '2' * 31}"])},
        {"url": f"https://www.notion.so/F-{cid(6)}", "Person": "F", "Stage of contact": "Reached",
         "Source": "Referral", "date:First touch:start": "2030-03-02", "Deals": "[]"},
        # raw REST page, cold, March (current month)
        {"id": cid(7), "properties": {
            "Person": {"type": "title", "title": [{"plain_text": "G"}]},
            "Stage of contact": {"type": "select", "select": {"name": "Replied"}},
            "Source": {"type": "select", "select": {"name": "Outbound"}},
            "First touch": {"type": "date", "date": {"start": "2030-03-04"}},
            "Deals": {"type": "relation", "relation": []}}},
        # left out: New, terminal, inbound-sourced, blank first contacted, unknown status
        {"_id": cid(8), "Person": "H", "Stage of contact": "Fresh", "Source": "Outbound",
         "First touch": None, "Deals": []},
        {"_id": cid(9), "Person": "I", "Stage of contact": "Not a fit", "Source": "Outbound",
         "First touch": "2030-02-01", "Deals": []},
        {"_id": cid(10), "Person": "J", "Stage of contact": "Replied", "Source": "Website",
         "First touch": "2030-02-01", "Deals": []},
        {"_id": cid(11), "Person": "K", "Stage of contact": "Replied", "Source": "Outbound",
         "First touch": None, "Deals": []},
        {"_id": cid(12), "Person": "L", "Stage of contact": "Mystery", "Source": "Outbound",
         "First touch": "2030-02-01", "Deals": []},
    ]
    deals = [
        {"_id": "d" + "1" * 31, "Deal": "Deal 1", "Phase": "Trial", "People": []},
        # customer via the deal-side relation, for contact E (MCP-style dashed id)
        {"_id": "d" + "2" * 31, "Deal": "Deal 2", "Phase": "Closed Won",
         "People": [f"{cid(5)[:8]}-{cid(5)[8:12]}-{cid(5)[12:16]}-{cid(5)[16:20]}-{cid(5)[20:]}"]},
        {"_id": "d" + "3" * 31, "Deal": "Deal 3", "Phase": "Lost", "People": [cid(1)]},
    ]
    return contacts, deals


def _self_test_config():
    cfg = {
        "owner": {"timezone": "UTC", "emails": ["me@example.com"]},
        "notion": {
            "field_map": {
                "contacts": {"name": "Person", "status": "Stage of contact", "lead_source": "Source",
                             "first_contacted": "First touch", "deal": "Deals"},
                "pipeline": {"name": "Deal", "stage": "Phase", "contacts": "People"},
            },
            "status_map": {"New": "Fresh", "Contacted": "Reached", "Responded": "Replied",
                           "Discovery": "Meeting", "Lead": "Handed over", "Archived": "Old",
                           "Do Not Contact": "Stop", "Disqualified": "Not a fit"},
            "option_map": {"pipeline": {"stage": {"Pilot": "Trial", "Won": "Closed Won", "Lost": "Lost"}},
                           "contacts": {"lead_source": {"Warm Intro": "Referral", "Inbound": "Website"}}},
        },
        "funnel": {"start_month": None, "pilot_stages": ["Pilot"], "customer_stages": ["Won"],
                   "warm_lead_sources": ["Warm Intro"], "inbound_lead_sources": ["Inbound"],
                   "drop_tolerance_pct": 0, "rise_tolerance_pct": 25, "max_blank_pct": 10, "inbound": []},
    }
    return cfg


def cmd_self_test(_args) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gtm-funnel-test-"))
    old_env = os.environ.get("GTM_CONFIG_DIR")
    os.environ["GTM_CONFIG_DIR"] = str(tmp / "cfg")
    failures = []

    def expect(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    try:
        (tmp / "cfg").mkdir()
        (tmp / "cfg" / "config.json").write_text(json.dumps(_self_test_config()), encoding="utf-8")
        contacts, deals = _self_test_data()
        cpath, dpath, out = tmp / "contacts.json", tmp / "deals.json", tmp / "out"
        cpath.write_text(json.dumps(contacts), encoding="utf-8")
        dpath.write_text(json.dumps({"results": deals}), encoding="utf-8")
        inb = tmp / "inbound.json"
        inb.write_text(json.dumps({"source": "test", "metrics": ["impressions", "clicks"],
                                   "months": {"2030-02": {"impressions": 100, "clicks": 5},
                                              "2030-03": {"impressions": 50, "clicks": 1}}}), encoding="utf-8")
        base = ["run", "--contacts", str(cpath), "--deals", str(dpath), "--out", str(out),
                "--today", "2030-03-15"]

        def run(extra=()):
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(base + list(extra))
            return code, (out / "funnel_checks.txt").read_text().strip()

        # 1. First run: counts, render, baseline saved.
        code, checks = run(["--inbound", str(inb)])
        expect("exit code", code, 0)
        expect("first run checks", checks, "ok")
        s = json.loads((out / "funnel_summary.json").read_text())
        cold, warm = s["totals"]["cold"], s["totals"]["warm"]
        expect("months", s["months"], ["2030-02", "2030-03"])
        expect("cold contacted", cold.get("contacted"), 5)    # A B C D G
        expect("cold responded", cold.get("responded"), 4)    # B C D(deal) G
        expect("cold discovery", cold.get("discovery"), 2)    # C D(deal)
        expect("cold pilot", cold.get("pilot"), 1)            # D
        expect("cold customer", cold.get("customer", 0), 0)
        expect("warm contacted", warm.get("contacted"), 2)    # E F
        expect("warm discovery", warm.get("discovery"), 1)    # E
        expect("warm pilot", warm.get("pilot"), 1)
        expect("warm customer", warm.get("customer"), 1)      # E via deal-side relation
        expect("inbound clicks", s["totals"]["inbound"].get("clicks"), 6)
        expect("blanks", s["counts"]["blank_first_contacted"], 1)   # K
        expect("inbound-sourced", s["counts"]["inbound_sourced_contacts"], 1)  # J
        expect("baseline saved", s["baseline_saved"], True)
        md = (out / "funnel_tables.md").read_text()
        for text in ("As of 2030-03-15. Mar 2030 is a partial month.", "| Mar 2030 (to date) |",
                     "| Total | 5 | 80.0% | 4 | 50.0% | 2 | 50.0% | 1 | 0.0% | 0 |",
                     "| Total | 2 | 50.0% | 1 | 100.0% | 1 | 100.0% | 1 |", "## Inbound",
                     "| Total | 150 | 4.0% | 6 |"):
            if text not in md:
                failures.append(f"funnel_tables.md lacks {text!r}")
        if md.index("Mar 2030") > md.index("Feb 2030"):
            failures.append("latest month is not first")
        if "Mystery" not in " ".join(s["notes"]):
            failures.append("unknown status value not reported")
        expect("blanks file", (out / "funnel_blanks.txt").read_text().startswith("K | Responded"), True)

        # 2. Same data again, split over two overlapping files: no changes.
        part2 = tmp / "contacts2.json"
        part2.write_text(json.dumps({"data": contacts[5:]}), encoding="utf-8")
        cpath.write_text(json.dumps(contacts[:7]), encoding="utf-8")
        code, checks = run(["--contacts", str(part2)])
        cpath.write_text(json.dumps(contacts), encoding="utf-8")
        expect("second run checks", checks, "ok")
        expect("delta", (out / "funnel_delta.txt").read_text().strip(), "no changes since last run")

        # 3. A past-month drop fails the check and keeps the old baseline.
        dropped = [c for c in contacts if c.get("_id") != f"{2:08x}" + "0" * 24]
        cpath.write_text(json.dumps(dropped), encoding="utf-8")
        code, checks = run()
        if "cold 2030-02 contacted went down: 4 -> 3" not in checks:
            failures.append(f"drop not caught: {checks!r}")
        expect("baseline kept", json.loads((out / "funnel_summary.json").read_text())["baseline_saved"], False)

        # 4. --accept-baseline accepts the drop; next run is clean.
        code, checks = run(["--accept-baseline"])
        expect("accepted run checks", checks, "ok")
        code, checks = run()
        expect("after accept checks", checks, "ok")

        # 5. A wrong field map fails loudly instead of counting zero.
        bad = _self_test_config()
        bad["notion"]["field_map"]["contacts"]["first_contacted"] = "First Contacted"
        (tmp / "cfg" / "config.json").write_text(json.dumps(bad), encoding="utf-8")
        code, checks = run()
        if "not in the contacts export" not in checks:
            failures.append(f"missing property not caught: {checks!r}")

        # 6. Many blank dates fail the blanks check.
        (tmp / "cfg" / "config.json").write_text(json.dumps(_self_test_config()), encoding="utf-8")
        many = contacts + [{"_id": f"{100 + i:08x}" + "0" * 24, "Person": f"Z{i}", "Stage of contact": "Reached",
                            "Source": "Outbound", "First touch": None, "Deals": []} for i in range(3)]
        cpath.write_text(json.dumps(many), encoding="utf-8")
        code, checks = run()
        if "have a blank 'First touch'" not in checks:
            failures.append(f"blanks check not caught: {checks!r}")
    finally:
        if old_env is None:
            os.environ.pop("GTM_CONFIG_DIR", None)
        else:
            os.environ["GTM_CONFIG_DIR"] = old_env
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("self-test FAILED:")
        for f in failures:
            print("  - " + f)
        return 1
    print("self-test ok")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Count the gtm funnel tables from a JSON export of the Notion CRM. Never writes to Notion.",
        epilog="Export format, definitions and the inbound hook are in the module docstring "
               "and in skills/funnel/references/.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="REST export of Contacts and Pipeline (needs the notion_token secret)")
    p.add_argument("--out", help="folder for contacts.json and deals.json (default ~/.config/gtm/funnel)")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("run", help="count the tables and write the funnel_* files")
    p.add_argument("--contacts", required=True, action="append",
                   help="contacts export JSON; repeat for several query pages (rows are deduplicated by page id)")
    p.add_argument("--deals", required=True, action="append",
                   help="pipeline (deals) export JSON; repeat for several query pages")
    p.add_argument("--out", help="output folder (default ~/.config/gtm/funnel)")
    p.add_argument("--inbound", help="optional inbound metrics JSON from an inbound adapter")
    p.add_argument("--today", help="YYYY-MM-DD; default today in owner.timezone")
    p.add_argument("--accept-baseline", action="store_true",
                   help="accept baseline drops and rises and save this run as the baseline; only when the user asks")
    p.add_argument("--no-save-baseline", action="store_true",
                   help="do not save the baseline (for a dry run that will not publish)")
    p.set_defaults(func=cmd_run)
    sub.add_parser("self-test", help="run on synthetic data and check the counts").set_defaults(func=cmd_self_test)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (InputError, gtm_config.ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
