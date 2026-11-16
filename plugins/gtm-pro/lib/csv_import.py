#!/usr/bin/env python3
"""Plan a CRM import from a CSV file (Python 3 stdlib only).

Works for any CRM that can export CSV (Google Sheets, Salesforce, Airtable,
HubSpot, Pipedrive, Attio exports, plain spreadsheets) and for the JSON rows
an API import writes out after it flattens them to CSV. This script never
writes to Notion and never reaches the network. It reads the file, normalizes
it, finds duplicates and writes a plan. The /gtm-pro:import skill shows the plan
to the user and then applies it through the Notion path in
reference/notion-access.md.

Usage (always python3 -I -B):

  csv_import.py suggest <file.csv> [--out mapping.json]
      Print the columns, three sample rows and a suggested mapping
      {column: logical_field or null}. Edit the mapping, then run plan.
      Last-activity columns ("Last Contacted", "Last Activity Date") are
      never suggested as first_contacted; they map to null.

  csv_import.py plan <file.csv> --mapping mapping.json [--existing keys.json]
                [--allow-keyless] [--owner-emails a@x.com,b@x.com]
                [--own-domains x.com,y.com] [--include-owner] [--out plan.json]
      Normalize every row, merge duplicates inside the file, match against
      the existing CRM keys, and write {creates, updates, skips, conflicts,
      companies, warnings, summary}. Prints a short summary.

  csv_import.py fields
      Print the logical fields a column can map to.

  csv_import.py self-test
      Build a temporary CSV and check the plan. Exit 0 when every check passes.

mapping.json: {"<CSV column>": "<logical field>" | null, ...}. Columns mapped
to null are ignored. Columns mapped to "extra" are kept as "Column: value"
lines for the contact's Notes. A column named "Source ID" that is mapped to
"extra" also sets source_id.

keys.json (existing CRM keys, built by the skill from a Contacts and
Companies query; source_id comes from a "Source ID: " line in Notes):
  {"contacts": [{"id": "<page id>", "email": "a@b.com",
                 "linkedin": "https://www.linkedin.com/in/x/",
                 "source_id": "hubspot:contact:51"}],
   "companies": [{"id": "<page id>", "name": "Acme", "domain": "acme.com"}]}
Every key except "id" is optional.

Matching against the CRM: a row whose source_id, LinkedIn URL or email
matches exactly one existing page is an update (match_on "source_id",
"linkedin" or "email", in that order). A row whose keys point at more than
one page is a conflict. Keyless rows (no email, no LinkedIn URL) are skipped
unless --allow-keyless; with it they still match on source_id.

Duplicates inside the file (same email, LinkedIn URL or source_id): the first
row is kept. Each later row fills the fields the first row has empty, adds
new Notes lines, and is listed in skips as a duplicate. A field where both
rows have different values keeps the first value and gets a warning. An
opt-out on any duplicate row wins.

Owner rows: a row whose email is in the owner emails is skipped with reason
"owner address" unless --include-owner. Owner emails and own domains come
from --owner-emails and --own-domains, else from the gtm config (owner.emails,
owner.own_domains) through the sibling config module. A company domain is
never taken from an own domain or a free-mail domain.

Status values from the source CRM are mapped to logical statuses (New,
Contacted, Responded, Discovery, Lead, Archived, Do Not Contact,
Disqualified) following skills/import/references/status-mapping.md, which is
the source of truth. For updates the plan carries the source status as
"status_suggested"; the skill applies it only when it moves the contact
forward, and never out of a terminal status (reference/crm-rules.md).

Each contact also carries "source_fields" ({first_name, company, title}) when
those columns are mapped, for the "Source fields:" body line. Values that
contain ";" are left out.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import sys
import tempfile
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
    "source_id": "stable record id in the source CRM, for example hubspot:contact:51",
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
    "first_contacted": ["first contacted", "first contact", "first outreach", "first outreach date",
                        "first contacted date", "date first contacted"],
    "source_id": ["source id", "source record id"],
    "do_not_contact": ["do not contact", "dnc", "unsubscribed", "opted out", "email opt out", "opt out"],
    "notes": ["notes", "note", "description", "comments"],
}

# Follows skills/import/references/status-mapping.md (the source of truth).
# Values are matched after normalization: lower case, "_" and punctuation
# become spaces, runs of spaces collapse. A value not listed here gets a
# warning and a suggested New, so the user decides (for example HubSpot
# "other", Pipedrive "hot lead", Attio "lost").
STATUS_SYNONYMS = [
    ("Do Not Contact", ["do not contact", "dnc", "unsubscribed", "opted out", "opt out", "bounced"]),
    ("Disqualified", ["disqualified", "unqualified", "not a fit", "bad fit", "junk", "bad timing",
                      "closed not converted"]),
    ("Archived", ["archived", "inactive", "dead"]),
    ("Lead", ["opportunity", "customer", "evangelist", "open deal", "closed won", "won",
              "closed converted", "proposal", "proposal made", "negotiation", "negotiations started"]),
    ("Discovery", ["salesqualifiedlead", "sales qualified lead", "sql", "qualified", "discovery",
                   "meeting", "meeting booked", "meeting scheduled", "demo", "demo scheduled",
                   "call booked", "needs defined"]),
    ("Responded", ["responded", "replied", "engaged", "interested", "in conversation", "connected"]),
    ("Contacted", ["contacted", "attempted", "attempted to contact", "in progress", "emailed",
                   "sequenced", "outreach", "working contacted", "contact made"]),
    ("New", ["new", "open", "subscriber", "subscribed", "lead", "new lead", "prospect", "to contact",
             "open not contacted", "not contacted", "marketingqualifiedlead", "marketing qualified lead",
             "mql", "lead in", "cold lead", ""]),
]

# Last-activity columns are not the first outreach date. suggest never maps
# them to a field.
LAST_ACTIVITY_RE = re.compile(
    r"^(last|latest|most recent)\b|"
    r"\b(last|latest|most recent|recent)\b.*\b(contact|contacted|activity|engagement|engaged|touch|touched|"
    r"outreach|email|emailed|call|meeting|reply|replied|seen|sent|open|opened|click|clicked|modified|updated)\b")

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


def _status_key(value):
    raw = (value or "").strip().lower().replace("_", " ")
    raw = re.sub(r"[^\w\s]", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


_STATUS_LOOKUP = {}
for _logical, _words in STATUS_SYNONYMS:
    for _word in _words:
        _STATUS_LOOKUP.setdefault(_status_key(_word), _logical)


def map_status(value):
    key = _status_key(value)
    if key in _STATUS_LOOKUP:
        return _STATUS_LOOKUP[key], True
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
        key = re.sub(r"\s+", " ", key).strip()
        choice = None
        if LAST_ACTIVITY_RE.search(key) and key not in HEADER_SYNONYMS["last_name"]:
            mapping[header] = None
            continue
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


# ---------------------------------------------------------------- owner

def split_list(value):
    """'a@x.com, b@x.com' -> ['a@x.com', 'b@x.com'] (lower case, no blanks)."""
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def owner_from_config():
    """Return (emails, own_domains, error) from the gtm config, or ([], [], reason)."""
    try:
        lib_dir = str(Path(__file__).resolve().parent)
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        import config as gtm_config  # sibling module in lib/
        owner = (gtm_config.load() or {}).get("owner") or {}
        emails = [str(e).strip().lower() for e in owner.get("emails") or [] if str(e).strip()]
        domains = [str(d).strip().lower() for d in owner.get("own_domains") or [] if str(d).strip()]
        return emails, domains, None
    except Exception as exc:  # the config is optional for planning
        return [], [], f"{exc.__class__.__name__}: {exc}"


def is_own_domain(domain, own_domains):
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in own_domains)


# ---------------------------------------------------------------- plan

def normalize_row(row, mapping, own_domains=()):
    values, extras = {}, []
    for column, logical in mapping.items():
        if not logical or column not in row:
            continue
        cell = norm_space(row[column])
        if not cell:
            continue
        if logical == "extra":
            extras.append(f"{column}: {cell}")
            if column.strip().lower() in ("source id", "source_id") and "source_id" not in values:
                values["source_id"] = cell
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
    if values.get("source_id"):
        contact["source_id"] = values["source_id"]
    for key in ("phone", "location", "lead_source"):
        if values.get(key):
            contact[key] = values[key]
    title, company_from_title = split_title_company(values.get("title"))
    if title:
        contact["title"] = title
    contact["designation"] = values.get("designation") or guess_designation(title)
    company_name = values.get("company") or company_from_title
    domain = norm_domain(values.get("company_website"))
    if domain and domain in FREE_MAIL:
        warnings.append(f"company website {domain!r} is a free-mail domain; not used as the company domain")
        domain = None
    if domain and is_own_domain(domain, own_domains):
        warnings.append(f"company website {domain!r} is one of your own domains; not used as the company domain")
        domain = None
    if not domain and contact.get("email"):
        email_domain = contact["email"].split("@", 1)[1]
        if email_domain not in FREE_MAIL and not is_own_domain(email_domain, own_domains):
            domain = email_domain
    if values.get("status"):
        logical, known = map_status(values["status"])
        contact["status_suggested"] = logical
        contact["status_source"] = values["status"]
        if not known:
            warnings.append(f"unknown status {values['status']!r}; suggested New, ask the user")
    if values.get("first_contacted"):
        contact["first_contacted"] = norm_date(values["first_contacted"])
        if not contact["first_contacted"]:
            warnings.append(f"unreadable date {values['first_contacted']!r} dropped")
    if values.get("do_not_contact") and values["do_not_contact"].strip().lower() in TRUTHY:
        contact["do_not_contact"] = True
        contact["status_suggested"] = "Do Not Contact"
    notes = [values["notes"]] if values.get("notes") else []
    notes.extend(extras)
    if contact.get("source_id") and not any(line.lower().startswith("source id:") for line in extras):
        notes.append(f"Source ID: {contact['source_id']}")
    if notes:
        contact["notes"] = "\n".join(notes)
    source_fields = {}
    for key, value in (("first_name", values.get("first_name")), ("company", values.get("company")),
                       ("title", title if values.get("title") else None)):
        if value and ";" not in value:
            source_fields[key] = value
    if source_fields:
        contact["source_fields"] = source_fields
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


def _merge_notes(first, extra):
    lines = (first or "").split("\n") if first else []
    for line in (extra or "").split("\n"):
        if line and line not in lines:
            lines.append(line)
    return "\n".join(lines)


def merge_duplicate(record, contact, company, row, warn):
    """Fill empty fields of the first row's record from a duplicate row.

    Returns the list of fields that were filled. Conflicting values stay as
    in the first row and are reported through warn().
    """
    first = record["contact"]
    filled = []
    for key, value in contact.items():
        if key in ("notes", "source_fields", "do_not_contact", "status_suggested", "status_source"):
            continue
        if key not in first:
            first[key] = value
            filled.append(key)
        elif first[key] != value:
            warn(f"duplicate of row {record['row']}: {key} {value!r} differs from {first[key]!r}; kept row {record['row']} value")
    if contact.get("notes"):
        merged = _merge_notes(first.get("notes"), contact["notes"])
        if merged != first.get("notes"):
            first["notes"] = merged
            filled.append("notes")
    sf_new = contact.get("source_fields") or {}
    if sf_new:
        sf = first.setdefault("source_fields", {})
        for key, value in sf_new.items():
            if key not in sf:
                sf[key] = value
                filled.append(f"source_fields.{key}")
            elif sf[key] != value:
                warn(f"duplicate of row {record['row']}: source field {key} {value!r} differs from {sf[key]!r}; kept row {record['row']} value")
    if contact.get("do_not_contact"):
        if not first.get("do_not_contact"):
            first["do_not_contact"] = True
            filled.append("do_not_contact")
        first["status_suggested"] = "Do Not Contact"
        first.setdefault("status_source", contact.get("status_source", "opt-out flag"))
    elif contact.get("status_suggested"):
        if "status_suggested" not in first:
            first["status_suggested"] = contact["status_suggested"]
            if contact.get("status_source"):
                first["status_source"] = contact["status_source"]
            filled.append("status_suggested")
        elif (first.get("status_source") != contact.get("status_source")
              and first["status_suggested"] != "Do Not Contact"):
            warn(f"duplicate of row {record['row']}: status {contact.get('status_source')!r} differs from "
                 f"{first.get('status_source')!r}; kept row {record['row']} value")
    if company:
        if record["company"] is None:
            record["company"] = company
            filled.append("company")
        elif record["company"]["key"] == company["key"]:
            for key, value in company.items():
                if key not in record["company"] or record["company"][key] in (None, ""):
                    record["company"][key] = value
        else:
            warn(f"duplicate of row {record['row']}: company {company['name']!r} differs from "
                 f"{record['company']['name']!r}; kept row {record['row']} value")
    return filled


def build_plan(rows, mapping, existing=None, allow_keyless=False,
               owner_emails=(), own_domains=(), include_owner=False):
    existing = existing or {}
    owner_emails = {e.lower() for e in owner_emails}
    own_domains = [d.lower() for d in own_domains]
    by_email, by_linkedin, by_source = {}, {}, {}
    for item in existing.get("contacts", []):
        email = norm_email(item.get("email"))
        linkedin = norm_linkedin(item.get("linkedin"))
        source_id = norm_space(item.get("source_id"))
        if email:
            by_email.setdefault(email, []).append(item["id"])
        if linkedin:
            by_linkedin.setdefault(linkedin, []).append(item["id"])
        if source_id:
            by_source.setdefault(source_id, []).append(item["id"])
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

    # Pass 1: normalize, skip, and merge duplicates inside the file.
    records = []  # in row order: {"row", "contact", "company"}
    seen = {"email": {}, "linkedin": {}, "source_id": {}}
    for index, row in enumerate(rows, start=2):  # row 1 is the header
        contact, company, warnings = normalize_row(row, mapping, own_domains)

        def warn(text, _row=index):
            plan["warnings"].append({"row": _row, "warning": text})

        for w in warnings:
            warn(w)
        email, linkedin, source_id = contact.get("email"), contact.get("linkedin"), contact.get("source_id")
        if not contact.get("name") and not email and not linkedin:
            plan["skips"].append({"row": index, "reason": "empty row"})
            continue
        if email and email in owner_emails and not include_owner:
            plan["skips"].append({"row": index, "reason": "owner address", "email": email})
            continue
        keys = {"email": email, "linkedin": linkedin, "source_id": source_id}
        matches = {seen[k][v]["row"]: seen[k][v] for k, v in keys.items() if v and v in seen[k]}
        if not matches and not email and not linkedin and not allow_keyless:
            plan["skips"].append({"row": index, "reason": "no email or LinkedIn URL (no stable key)",
                                  "name": contact.get("name")})
            continue
        if len(matches) > 1:
            plan["conflicts"].append({"row": index, "reason": "keys match different earlier rows in this file",
                                      "rows": sorted(matches), "contact": contact})
            continue
        if matches:
            record = next(iter(matches.values()))
            filled = merge_duplicate(record, contact, company, index, warn)
            plan["skips"].append({"row": index, "reason": f"duplicate of row {record['row']} in this file",
                                  "merged_into": record["row"], "merged_fields": filled})
            target = record
        else:
            target = {"row": index, "contact": contact, "company": company}
            records.append(target)
        for k in seen:
            value = target["contact"].get(k)
            if value and value not in seen[k]:
                seen[k][value] = target

    # Pass 2: companies and matching against the CRM.
    new_companies = {}
    for record in records:
        index, contact, company = record["row"], record["contact"], record["company"]
        if company:
            ckey = company["key"]
            name_key = company_key(company["name"], None)
            page = existing_companies.get(ckey) or (existing_companies.get(name_key) if name_key else None)
            if page:
                plan["companies"]["existing"][ckey] = page
            elif ckey not in new_companies:
                new_companies[ckey] = company
            contact["company_key"] = ckey

        sid_ids = by_source.get(contact.get("source_id"), []) if contact.get("source_id") else []
        li_ids = by_linkedin.get(contact.get("linkedin"), []) if contact.get("linkedin") else []
        em_ids = by_email.get(contact.get("email"), []) if contact.get("email") else []
        candidates = sorted(set(sid_ids) | set(li_ids) | set(em_ids))
        if len(candidates) > 1:
            plan["conflicts"].append({"row": index, "reason": "matches more than one existing contact",
                                      "candidates": candidates, "contact": contact})
        elif candidates:
            match_on = "source_id" if sid_ids else "linkedin" if li_ids else "email"
            plan["updates"].append({"row": index, "page_id": candidates[0], "match_on": match_on,
                                    "contact": contact})
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


# ---------------------------------------------------------------- self-test

SELF_TEST_CSV = [
    ["First Name", "Last Name", "Email", "LinkedIn URL", "Company", "Company Website", "Job Title",
     "Lifecycle Stage", "Last Contacted", "Source ID", "Unsubscribed", "Notes"],
    # row 2: the owner's own address
    ["Sam", "Owner", "sam@ownco.example", "", "OwnCo", "ownco.example", "Founder",
     "customer", "2026-03-01", "hubspot:contact:1", "", ""],
    # row 3: first copy of Ada
    ["Ada", "Lovelace", "ada@analytical.example", "", "Analytical Engines", "", "",
     "marketingqualifiedlead", "2026-01-05", "hubspot:contact:2", "", "met at a meetup"],
    # row 4: duplicate of Ada with more fields and a different status
    ["Ada", "Lovelace", "ADA@analytical.example", "linkedin.com/in/ada-lovelace", "", "", "CEO",
     "salesqualifiedlead", "", "hubspot:contact:2", "", "asked about pricing"],
    # row 5: keyless row that matches an existing page by source_id
    ["Grace", "Hopper", "", "", "Cobol Labs", "cobol.example", "CTO",
     "opportunity", "", "hubspot:contact:7", "", ""],
    # row 6: free-mail address, no website
    ["Bob", "Builder", "bob@gmail.com", "", "Bobco", "", "Owner",
     "evangelist", "", "hubspot:contact:8", "", ""],
    # row 7: a colleague at the owner's domain (not an owner address)
    ["Cy", "Colleague", "cy@ownco.example", "", "OwnCo", "", "Engineer",
     "subscriber", "", "hubspot:contact:9", "", ""],
    # row 8: existing contact by email, unknown status
    ["Dee", "Existing", "dee@delta.example", "", "Delta", "delta.example", "VP Sales",
     "other", "", "hubspot:contact:10", "", ""],
    # row 9: opted out
    ["Eve", "Optout", "eve@echo.example", "", "Echo", "", "",
     "lead", "", "hubspot:contact:11", "true", ""],
    # row 10: keyless with no source match
    ["Finn", "Nokey", "", "", "", "", "",
     "opportunity", "", "", "", ""],
]

SELF_TEST_EXISTING = {
    "contacts": [{"id": "page-grace", "source_id": "hubspot:contact:7"},
                 {"id": "page-dee", "email": "dee@delta.example"}],
    "companies": [{"id": "page-delta", "name": "Delta", "domain": "delta.example"}],
}


def self_test() -> int:
    failures = []

    def check(label, condition):
        print(("ok    " if condition else "FAIL  ") + label)
        if not condition:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["GTM_CONFIG_DIR"] = tmp  # never read the real config
        path = Path(tmp) / "contacts.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(SELF_TEST_CSV)
        headers, rows = read_csv(path)
        mapping = suggest_mapping(headers)
        check("suggest: Last Contacted maps to null", mapping.get("Last Contacted") is None)
        check("suggest: Source ID maps to source_id", mapping.get("Source ID") == "source_id")
        check("suggest: Lifecycle Stage maps to status", mapping.get("Lifecycle Stage") == "status")
        check("suggest: Unsubscribed maps to do_not_contact", mapping.get("Unsubscribed") == "do_not_contact")
        check("suggest: no column maps to first_contacted", "first_contacted" not in mapping.values())
        check("suggest: other last-activity headers map to null",
              suggest_mapping(["Last Activity Date", "notes_last_contacted", "Last Touched", "Last Outreach",
                               "Last Modified", "Most Recent Email"]) ==
              {"Last Activity Date": None, "notes_last_contacted": None, "Last Touched": None,
               "Last Outreach": None, "Last Modified": None, "Most Recent Email": None})
        check("suggest: Last Name still maps to last_name", suggest_mapping(["Last Name"]) == {"Last Name": "last_name"})

        expected_status = {
            "subscriber": "New", "lead": "New", "marketingqualifiedlead": "New",
            "salesqualifiedlead": "Discovery", "opportunity": "Lead", "customer": "Lead",
            "evangelist": "Lead", "MQL": "New", "SQL": "Discovery", "ATTEMPTED_TO_CONTACT": "Contacted",
            "OPEN_DEAL": "Lead", "BAD_TIMING": "Disqualified", "Open - Not Contacted": "New",
            "Closed - Not Converted": "Disqualified", "Contact Made": "Contacted", "Won 🎉": "Lead", "Lead In": "New",
        }
        for value, logical in expected_status.items():
            got, known = map_status(value)
            check(f"status: {ascii(value)} -> {logical}", known and got == logical)
        check("status: 'other' is unknown", map_status("other") == ("New", False))

        plan = build_plan(rows, mapping, SELF_TEST_EXISTING, allow_keyless=True,
                          owner_emails=["sam@ownco.example"], own_domains=["ownco.example"])
        by_row = {}
        for bucket in ("creates", "updates", "skips", "conflicts"):
            for item in plan[bucket]:
                by_row.setdefault(item["row"], []).append((bucket, item))
        check("every row is in exactly one bucket",
              sorted(by_row) == list(range(2, len(rows) + 2)) and all(len(v) == 1 for v in by_row.values()))
        s = plan["summary"]
        check("buckets sum to the row count", s["creates"] + s["updates"] + s["skips"] + s["conflicts"] == s["rows"])

        bucket, item = by_row[2][0]
        check("row 2: owner address skipped", bucket == "skips" and item["reason"] == "owner address")

        bucket, item = by_row[3][0]
        ada = item["contact"]
        check("row 3: Ada is a create", bucket == "creates")
        check("row 3: LinkedIn filled from duplicate row 4",
              ada.get("linkedin") == "https://www.linkedin.com/in/ada-lovelace/")
        check("row 3: title filled from duplicate row 4", ada.get("title") == "CEO")
        check("row 3: notes from both rows kept",
              "met at a meetup" in ada.get("notes", "") and "asked about pricing" in ada.get("notes", ""))
        check("row 3: status stays New (MQL), not Discovery", ada.get("status_suggested") == "New")
        check("row 3: no first_contacted from Last Contacted", "first_contacted" not in ada)
        check("row 3: Source ID line in notes", "Source ID: hubspot:contact:2" in ada.get("notes", ""))
        check("row 3: source_fields from columns",
              ada.get("source_fields", {}).get("first_name") == "Ada"
              and ada["source_fields"].get("company") == "Analytical Engines"
              and ada["source_fields"].get("title") == "CEO")
        bucket, item = by_row[4][0]
        check("row 4: duplicate listed in skips with merged fields",
              bucket == "skips" and item.get("merged_into") == 3 and "linkedin" in item.get("merged_fields", []))
        check("row 4: status conflict reported as a warning",
              any(w["row"] == 4 and "status" in w["warning"] for w in plan["warnings"]))

        bucket, item = by_row[5][0]
        check("row 5: keyless row updates by source_id",
              bucket == "updates" and item["page_id"] == "page-grace" and item["match_on"] == "source_id")
        check("row 5: opportunity -> Lead", item["contact"].get("status_suggested") == "Lead")

        bucket, item = by_row[6][0]
        check("row 6: free-mail domain not used as company domain",
              bucket == "creates" and item["contact"].get("company_key") == "name:bobco")

        bucket, item = by_row[7][0]
        check("row 7: colleague is created, company domain not from own domain",
              bucket == "creates" and item["contact"].get("company_key") == "name:ownco")

        bucket, item = by_row[8][0]
        check("row 8: existing contact updates by email",
              bucket == "updates" and item["page_id"] == "page-dee" and item["match_on"] == "email")
        check("row 8: unknown status 'other' warned",
              any(w["row"] == 8 and "unknown status" in w["warning"] for w in plan["warnings"]))
        check("row 8: existing company reused", plan["companies"]["existing"].get("domain:delta.example") == "page-delta")

        bucket, item = by_row[9][0]
        check("row 9: opt-out -> Do Not Contact",
              item["contact"].get("do_not_contact") is True and item["contact"].get("status_suggested") == "Do Not Contact")

        bucket, item = by_row[10][0]
        check("row 10: keyless row without a match is a create (allow-keyless)", bucket == "creates")

        check("no company keyed on the own domain",
              all(c["key"] != "domain:ownco.example" for c in plan["companies"]["create"]))

        plan2 = build_plan(rows, mapping, SELF_TEST_EXISTING, allow_keyless=False,
                           owner_emails=["sam@ownco.example"], own_domains=["ownco.example"], include_owner=True)
        rows2 = {i["row"]: b for b in ("creates", "updates", "skips", "conflicts") for i in plan2[b]}
        check("--include-owner: owner row is planned", rows2.get(2) == "creates")
        check("without --allow-keyless: keyless rows skipped", rows2.get(5) == "skips" and rows2.get(10) == "skips")
        check("--include-owner: company domain still not the own domain",
              all(c["key"] != "domain:ownco.example" for c in plan2["companies"]["create"]))

        # Through the CLI: suggest --out, then plan with no owner flags (owner from config).
        Path(tmp, "config.json").write_text(json.dumps(
            {"owner": {"emails": ["sam@ownco.example"], "own_domains": ["ownco.example"]}}), encoding="utf-8")
        existing_path = Path(tmp) / "keys.json"
        existing_path.write_text(json.dumps(SELF_TEST_EXISTING), encoding="utf-8")
        mapping_path, plan_path = Path(tmp) / "mapping.json", Path(tmp) / "plan.json"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code_s = main(["suggest", str(path), "--out", str(mapping_path)])
            code_p = main(["plan", str(path), "--mapping", str(mapping_path), "--existing", str(existing_path),
                           "--allow-keyless", "--out", str(plan_path)])
            code_f = main(["fields"])
        check("cli: suggest, plan and fields exit 0", (code_s, code_p, code_f) == (0, 0, 0))
        if plan_path.exists():
            cli_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            cli_rows = {i["row"]: (b, i) for b in ("creates", "updates", "skips", "conflicts") for i in cli_plan[b]}
            if cli_plan.get("owner", {}).get("emails") == 1:
                check("cli: owner row skipped with owner from config",
                      cli_rows.get(2, (None, {}))[1].get("reason") == "owner address")
            else:
                print(f"skip  cli owner from config: config module not usable here ({err.getvalue().strip()[:120]})")
            check("cli: keyless row updates by source_id",
                  cli_rows.get(5, (None, {}))[1].get("match_on") == "source_id")
        check("fields lists source_id", "source_id" in FIELDS)

        rows3 = rows + [{"First Name": "Grace", "Last Name": "Hopper", "Source ID": "hubspot:contact:7",
                         "Notes": "second row for Grace", "Email": "", "LinkedIn URL": ""}]
        plan3 = build_plan(rows3, mapping, SELF_TEST_EXISTING, allow_keyless=True,
                           owner_emails=["sam@ownco.example"], own_domains=["ownco.example"])
        grace = next(i for i in plan3["updates"] if i["row"] == 5)
        check("keyless duplicate merges into the first row by source_id",
              "second row for Grace" in grace["contact"].get("notes", ""))

        Path(tmp, "config.json").write_text(json.dumps(
            {"owner": {"emails": ["Sam@OwnCo.example"], "own_domains": ["ownco.example"]}}), encoding="utf-8")
        emails, domains, error = owner_from_config()
        if error:
            print(f"skip  owner from config: config module not usable here ({error})")
        else:
            check("owner from config", emails == ["sam@ownco.example"] and domains == ["ownco.example"])

    print(f"self-test: {'FAILED, ' + str(len(failures)) + ' check(s)' if failures else 'all checks passed'}")
    return 1 if failures else 0


# ---------------------------------------------------------------- CLI

def _emit(data, out):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan a CRM import from CSV. Never writes to Notion and never reaches the network.",
        epilog="Run as python3 -I -B. See the module docstring for the mapping and keys.json formats.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("suggest", help="show columns and a suggested mapping")
    p.add_argument("csv")
    p.add_argument("--out", help="write the suggested mapping to this file")
    p = sub.add_parser("plan", help="normalize, merge duplicates, match and write an import plan")
    p.add_argument("csv")
    p.add_argument("--mapping", required=True, help="mapping.json {column: logical field or null}")
    p.add_argument("--existing", help="keys.json with existing contact keys (id, email, linkedin, source_id) "
                                      "and company keys (id, name, domain)")
    p.add_argument("--allow-keyless", action="store_true",
                   help="plan contacts that have no email and no LinkedIn URL (they still match on source_id)")
    p.add_argument("--owner-emails", help="comma list of your own addresses; default owner.emails from config")
    p.add_argument("--own-domains", help="comma list of your own domains; default owner.own_domains from config")
    p.add_argument("--include-owner", action="store_true",
                   help="plan rows whose email is an owner address instead of skipping them")
    p.add_argument("--out", help="write the plan to this file")
    sub.add_parser("fields", help="list logical fields")
    sub.add_parser("self-test", help="check the planner against a built-in sample file")
    args = parser.parse_args(argv)

    try:
        if args.command == "fields":
            _emit(FIELDS, None)
            return 0
        if args.command == "self-test":
            return self_test()
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
        owner_emails = split_list(args.owner_emails) if args.owner_emails is not None else None
        own_domains = split_list(args.own_domains) if args.own_domains is not None else None
        owner_source = "flags"
        if owner_emails is None or own_domains is None:
            cfg_emails, cfg_domains, error = owner_from_config()
            if error:
                print(f"warning: could not read owner from config ({error}); pass --owner-emails "
                      f"and --own-domains", file=sys.stderr)
            owner_emails = cfg_emails if owner_emails is None else owner_emails
            own_domains = cfg_domains if own_domains is None else own_domains
            owner_source = "flags and config" if (args.owner_emails or args.own_domains) else "config"
        if not owner_emails:
            print("warning: no owner emails; your own address would be imported as a contact", file=sys.stderr)
        plan = build_plan(rows, mapping, existing, args.allow_keyless,
                          owner_emails, own_domains, args.include_owner)
        plan["owner"] = {"emails": len(owner_emails), "own_domains": len(own_domains), "from": owner_source,
                         "include_owner": args.include_owner}
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
