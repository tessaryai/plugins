#!/usr/bin/env python3
"""Plan a CRM import from a CSV file (Python 3 stdlib only).

Works for any CRM that can export CSV (Google Sheets, Salesforce, Airtable,
HubSpot, Pipedrive, Attio exports, plain spreadsheets) and for the JSON rows
an API import writes out after it flattens them to CSV. This script never
writes to Notion. It reads the file, normalizes it, finds duplicates and
writes a plan. The /gtm:import skill shows the plan to the user and then
applies it through the Notion path in reference/notion-access.md.

Usage (always python3 -I):

  csv_import.py suggest <file.csv> [--out mapping.json]
      Print the columns, three sample rows and a suggested mapping
      {column: logical_field or null}. Edit the mapping, then run plan.

  csv_import.py plan <file.csv> --mapping mapping.json [--existing keys.json]
                [--allow-keyless] [--out plan.json]
      Normalize every row, detect duplicates inside the file and against the
      existing CRM keys, and write {creates, updates, skips, conflicts,
      companies, warnings, summary}. Prints a short summary.

  csv_import.py fields
      Print the logical fields a column can map to.

mapping.json: {"<CSV column>": "<logical field>" | null, ...}. Columns mapped
to null are ignored. Columns mapped to "extra" are kept as "Column: value"
lines for the contact's Notes.

keys.json (existing CRM keys, built by the skill from a Contacts and
Companies query):
  {"contacts": [{"id": "<page id>", "email": "a@b.com", "linkedin": "https://..."}],
   "companies": [{"id": "<page id>", "name": "Acme", "domain": "acme.com"}]}

Status values from the source CRM are mapped to logical statuses (New,
Contacted, Responded, Discovery, Lead, Archived, Do Not Contact,
Disqualified). For updates the plan carries the source status as
"status_suggested"; the skill applies it only when it moves the contact
forward, and never out of a terminal status (reference/crm-rules.md).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

FIELDS = {
    "name": "full name",
    "first_name": "first name (joined with last_name when name is empty)",
    "last_name": "last name",
    "email": "email address",
    "linkedin": "LinkedIn profile URL",
    "phone": "phone number",
    "location": "city, region or country",
    "title": "job title (also used to guess Designation)",
    "designation": "seniority bucket (Founder, CEO, CXO, VP, Manager, Individual Contributor)",
    "company": "company name",
    "company_website": "company website or domain",
    "company_linkedin": "company LinkedIn URL",
    "employees": "company employee count",
    "headquarters": "company headquarters",
    "status": "lifecycle or lead status in the source CRM",
    "lead_source": "where the lead came from",
    "first_contacted": "date of first outreach",
    "do_not_contact": "opt-out / unsubscribed / do not contact flag",
    "notes": "free text notes",
    "extra": "keep as a 'Column: value' line in Notes",
}

HEADER_SYNONYMS = {
    "name": ["name", "full name", "fullname", "contact name", "person", "contact"],
    "first_name": ["first name", "firstname", "first", "given name"],
    "last_name": ["last name", "lastname", "last", "surname", "family name"],
    "email": ["email", "e-mail", "email address", "work email", "primary email", "emails"],
    "linkedin": ["linkedin", "linkedin url", "linkedin profile", "person linkedin url", "linkedin_url", "profile url"],
    "phone": ["phone", "phone number", "mobile", "mobile phone", "work phone", "phones"],
    "location": ["location", "city", "country", "region", "state"],
    "title": ["title", "job title", "position", "role", "headline"],
    "designation": ["designation", "seniority"],
    "company": ["company", "company name", "organization", "organisation", "account", "account name", "org"],
    "company_website": ["website", "company website", "domain", "company domain", "url"],
    "company_linkedin": ["company linkedin", "company linkedin url"],
    "employees": ["employees", "employee count", "# employees", "company size", "headcount"],
    "headquarters": ["headquarters", "hq", "company location"],
    "status": ["status", "lead status", "lifecycle stage", "stage", "contact status"],
    "lead_source": ["lead source", "source", "original source"],
    "first_contacted": ["first contacted", "first contact", "first outreach", "last contacted"],
    "do_not_contact": ["do not contact", "dnc", "unsubscribed", "opted out", "email opt out", "opt out"],
    "notes": ["notes", "note", "description", "comments"],
}

STATUS_SYNONYMS = [
    ("Do Not Contact", ["do not contact", "dnc", "unsubscribed", "opted out", "bounced", "opt out"]),
    ("Disqualified", ["disqualified", "unqualified", "not a fit", "bad fit", "junk"]),
    ("Archived", ["archived", "inactive"]),
    ("Lead", ["sql", "opportunity", "customer", "closed won", "won", "evangelist"]),
    ("Discovery", ["discovery", "meeting", "demo", "call booked", "meeting booked", "qualified", "mql"]),
    ("Responded", ["responded", "replied", "engaged", "interested", "in conversation"]),
    ("Contacted", ["contacted", "attempted", "attempted to contact", "in progress", "emailed", "sequenced", "outreach"]),
    ("New", ["new", "open", "subscriber", "prospect", "lead", "new lead", "open - not contacted", "not contacted", ""]),
]

FREE_MAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "ymail.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me",
    "protonmail.com", "gmx.com", "gmx.de", "mail.com", "zoho.com", "yandex.com", "hey.com",
    "fastmail.com", "qq.com", "163.com", "rediffmail.com",
}

TRUTHY = {"true", "yes", "y", "1", "x", "checked", "unsubscribed", "opted out"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
COMPANY_SUFFIX_RE = re.compile(r"[,\s]+(inc|inc\.|llc|ltd|ltd\.|limited|gmbh|corp|corp\.|co|co\.|plc|pvt|private limited|s\.a\.|b\.v\.)$", re.I)
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M")


# ---------------------------------------------------------------- normalize

def norm_email(value):
    value = (value or "").strip().strip("<>").lower()
    if value.startswith("mailto:"):
        value = value[7:]
    if ";" in value or "," in value:
        value = re.split(r"[;,]", value)[0].strip()
    return value if EMAIL_RE.match(value) else None


def norm_linkedin(value):
    """Canonical https://www.linkedin.com/in/<slug>/ or None for non-profile URLs."""
    value = (value or "").strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    match = re.match(r"^/in/([^/?#]+)", parsed.path)
    if not match:
        return None
    slug = match.group(1).strip().lower()
    return f"https://www.linkedin.com/in/{slug}/" if slug else None


def norm_space(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def norm_name(name, first="", last=""):
    name = norm_space(name)
    if not name:
        name = norm_space(f"{first} {last}")
    if name and (name.isupper() or name.islower()):
        name = " ".join(part[:1].upper() + part[1:].lower() for part in name.split(" "))
    return name or None


def norm_domain(value):
    value = (value or "").strip().lower()
    if not value:
        return None
    if "@" in value:
        value = value.split("@", 1)[1]
    if not re.match(r"^https?://", value):
        value = "http://" + value
    host = urlparse(value).netloc.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host if "." in host else None


def company_key(name, domain):
    if domain:
        return "domain:" + domain
    if name:
        base = COMPANY_SUFFIX_RE.sub("", name.strip()).strip().lower()
        return "name:" + re.sub(r"\s+", " ", base) if base else None
    return None


def norm_date(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else None


def map_status(value):
    raw = (value or "").strip().lower()
    raw = re.sub(r"\s+", " ", raw.replace("_", " "))
    for logical, words in STATUS_SYNONYMS:
        if raw in words:
            return logical, True
    return "New", False


def guess_designation(title):
    t = (title or "").lower()
    if not t:
        return None
    if "founder" in t:
        return "Founder"
    if re.search(r"\bceo\b|chief executive", t):
        return "CEO"
    if re.search(r"\bc[a-z]o\b|chief ", t):
        return "CXO"
    if re.search(r"\bvp\b|vice president|head of|director", t):
        return "VP"
    if "manager" in t or "lead" in t:
        return "Manager"
    return "Individual Contributor"


def split_title_company(title):
    """'VP Sales at Acme' -> ('VP Sales', 'Acme')."""
    match = re.match(r"^(.*?)\s+(?:at|@)\s+(.+)$", title or "", re.I)
    return (match.group(1).strip(), match.group(2).strip()) if match else (title, None)


# ---------------------------------------------------------------- read

def read_csv(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    rows = [{(k or "").strip(): (v or "") for k, v in row.items() if k is not None} for row in reader]
    return [h.strip() for h in (reader.fieldnames or [])], rows


def suggest_mapping(headers):
    mapping, used = {}, set()
    for header in headers:
        key = re.sub(r"[_\-]+", " ", header.strip().lower())
        choice = None
        for logical, words in HEADER_SYNONYMS.items():
            if key in words and logical not in used:
                choice = logical
                break
        if choice is None:
            for logical, words in HEADER_SYNONYMS.items():
                if logical not in used and any(len(w) > 3 and w in key for w in words):
                    choice = logical
                    break
        if choice:
            used.add(choice)
        mapping[header] = choice
    return mapping


# ---------------------------------------------------------------- plan

def normalize_row(row, mapping):
    values, extras = {}, []
    for column, logical in mapping.items():
        if not logical or column not in row:
            continue
        cell = norm_space(row[column])
        if not cell:
            continue
        if logical == "extra":
            extras.append(f"{column}: {cell}")
        elif logical in values and logical == "notes":
            values["notes"] += "\n" + cell
        elif logical not in values:
            values[logical] = cell
    warnings = []
    contact = {}
    contact["name"] = norm_name(values.get("name"), values.get("first_name", ""), values.get("last_name", ""))
    if values.get("email"):
        contact["email"] = norm_email(values["email"])
        if not contact["email"]:
            warnings.append(f"invalid email {values['email']!r} dropped")
    if values.get("linkedin"):
        contact["linkedin"] = norm_linkedin(values["linkedin"])
        if not contact["linkedin"]:
            warnings.append(f"not a LinkedIn profile URL {values['linkedin']!r} dropped")
    for key in ("phone", "location", "lead_source"):
        if values.get(key):
            contact[key] = values[key]
    title, company_from_title = split_title_company(values.get("title"))
    if title:
        contact["title"] = title
    contact["designation"] = values.get("designation") or guess_designation(title)
    company_name = values.get("company") or company_from_title
    domain = norm_domain(values.get("company_website"))
    if not domain and contact.get("email"):
        email_domain = contact["email"].split("@", 1)[1]
        if email_domain not in FREE_MAIL:
            domain = email_domain
    if values.get("status"):
        logical, known = map_status(values["status"])
        contact["status_suggested"] = logical
        contact["status_source"] = values["status"]
        if not known:
            warnings.append(f"unknown status {values['status']!r}; suggested New")
    if values.get("first_contacted"):
        contact["first_contacted"] = norm_date(values["first_contacted"])
        if not contact["first_contacted"]:
            warnings.append(f"unreadable date {values['first_contacted']!r} dropped")
    if values.get("do_not_contact") and values["do_not_contact"].strip().lower() in TRUTHY:
        contact["do_not_contact"] = True
        contact["status_suggested"] = "Do Not Contact"
    notes = [values["notes"]] if values.get("notes") else []
    notes.extend(extras)
    if notes:
        contact["notes"] = "\n".join(notes)
    company = None
    ckey = company_key(company_name, domain)
    if ckey:
        company = {"key": ckey, "name": company_name or domain, "domain": domain}
        for key in ("company_linkedin", "headquarters"):
            if values.get(key):
                company[key] = values[key]
        if values.get("employees"):
            digits = re.sub(r"[^\d]", "", values["employees"].split("-")[0])
            if digits:
                company["employees"] = int(digits)
    contact = {k: v for k, v in contact.items() if v not in (None, "")}
    return contact, company, warnings


def build_plan(rows, mapping, existing=None, allow_keyless=False):
    existing = existing or {}
    by_email, by_linkedin = {}, {}
    for item in existing.get("contacts", []):
        email = norm_email(item.get("email"))
        linkedin = norm_linkedin(item.get("linkedin"))
        if email:
            by_email.setdefault(email, []).append(item["id"])
        if linkedin:
            by_linkedin.setdefault(linkedin, []).append(item["id"])
    existing_companies = {}
    for item in existing.get("companies", []):
        key = company_key(item.get("name"), norm_domain(item.get("domain")))
        if key:
            existing_companies.setdefault(key, item["id"])
        name_key = company_key(item.get("name"), None)
        if name_key:
            existing_companies.setdefault(name_key, item["id"])

    plan = {"creates": [], "updates": [], "skips": [], "conflicts": [],
            "companies": {"create": [], "existing": {}}, "warnings": []}
    seen_email, seen_linkedin = {}, {}
    new_companies = {}

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        contact, company, warnings = normalize_row(row, mapping)
        for w in warnings:
            plan["warnings"].append({"row": index, "warning": w})
        email, linkedin = contact.get("email"), contact.get("linkedin")
        if not contact.get("name") and not email and not linkedin:
            plan["skips"].append({"row": index, "reason": "empty row"})
            continue
        if not email and not linkedin and not allow_keyless:
            plan["skips"].append({"row": index, "reason": "no email or LinkedIn URL (no stable key)",
                                  "name": contact.get("name")})
            continue
        dup_rows = {seen_email.get(email) if email else None, seen_linkedin.get(linkedin) if linkedin else None} - {None}
        if len(dup_rows) > 1:
            plan["conflicts"].append({"row": index, "reason": "email and LinkedIn match different earlier rows",
                                      "rows": sorted(dup_rows), "contact": contact})
            continue
        if dup_rows:
            plan["skips"].append({"row": index, "reason": f"duplicate of row {dup_rows.pop()} in this file"})
            continue
        if email:
            seen_email[email] = index
        if linkedin:
            seen_linkedin[linkedin] = index

        ckey = None
        if company:
            ckey = company["key"]
            name_key = company_key(company["name"], None)
            page = existing_companies.get(ckey) or (existing_companies.get(name_key) if name_key else None)
            if page:
                plan["companies"]["existing"][ckey] = page
            elif ckey not in new_companies:
                new_companies[ckey] = company
            contact["company_key"] = ckey

        li_ids = by_linkedin.get(linkedin, []) if linkedin else []
        em_ids = by_email.get(email, []) if email else []
        candidates = sorted(set(li_ids) | set(em_ids))
        if len(li_ids) > 1 or len(em_ids) > 1 or (li_ids and em_ids and set(li_ids) != set(em_ids)):
            plan["conflicts"].append({"row": index, "reason": "matches more than one existing contact",
                                      "candidates": candidates, "contact": contact})
        elif candidates:
            plan["updates"].append({"row": index, "page_id": candidates[0],
                                    "match_on": "linkedin" if li_ids else "email", "contact": contact})
        else:
            plan["creates"].append({"row": index, "contact": contact})

    plan["companies"]["create"] = list(new_companies.values())
    plan["summary"] = {
        "rows": len(rows),
        "creates": len(plan["creates"]),
        "updates": len(plan["updates"]),
        "skips": len(plan["skips"]),
        "conflicts": len(plan["conflicts"]),
        "companies_to_create": len(plan["companies"]["create"]),
        "companies_existing": len(plan["companies"]["existing"]),
        "warnings": len(plan["warnings"]),
    }
    return plan


# ---------------------------------------------------------------- CLI

def _emit(data, out):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Plan a CRM import from CSV. Never writes to Notion.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("suggest", help="show columns and a suggested mapping")
    p.add_argument("csv")
    p.add_argument("--out")
    p = sub.add_parser("plan", help="normalize, dedupe and write an import plan")
    p.add_argument("csv")
    p.add_argument("--mapping", required=True)
    p.add_argument("--existing", help="JSON with existing contact and company keys")
    p.add_argument("--allow-keyless", action="store_true", help="create contacts that have no email and no LinkedIn URL")
    p.add_argument("--out")
    sub.add_parser("fields", help="list logical fields")
    args = parser.parse_args(argv)

    try:
        if args.command == "fields":
            _emit(FIELDS, None)
            return 0
        headers, rows = read_csv(args.csv)
        if args.command == "suggest":
            mapping = suggest_mapping(headers)
            if args.out:
                _emit(mapping, args.out)
            _emit({"columns": headers, "rows": len(rows), "sample": rows[:3],
                   "suggested_mapping": mapping, "fields": sorted(FIELDS)}, None)
            return 0
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
        bad = [v for v in mapping.values() if v and v not in FIELDS]
        if bad:
            print(f"error: unknown logical fields in mapping: {', '.join(sorted(set(bad)))}", file=sys.stderr)
            return 1
        missing = [c for c in mapping if c not in headers]
        if missing:
            print(f"error: mapping names columns not in the file: {', '.join(missing)}", file=sys.stderr)
            return 1
        existing = json.loads(Path(args.existing).read_text(encoding="utf-8")) if args.existing else None
        plan = build_plan(rows, mapping, existing, args.allow_keyless)
        if args.out:
            _emit(plan, args.out)
        s = plan["summary"]
        print(f"rows {s['rows']}: create {s['creates']}, update {s['updates']}, skip {s['skips']}, "
              f"conflict {s['conflicts']}; companies new {s['companies_to_create']}, "
              f"existing {s['companies_existing']}; warnings {s['warnings']}"
              + (f"; plan written to {args.out}" if args.out else ""))
        if not args.out:
            _emit(plan, None)
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
