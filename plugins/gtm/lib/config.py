#!/usr/bin/env python3
"""Load, validate and edit the gtm plugin configuration.

Runtime files live outside the plugin folder, because a plugin update
replaces that folder. The default folder is ~/.config/gtm; set
GTM_CONFIG_DIR to use another folder (tests, a second workspace). Run
"config.py paths" to print the real locations:

  config.json       settings (no secrets)
  credentials.json  Notion token and API keys, mode 600
  state.json        per-adapter cursors
  logs.md           run log
  imports/          import work folders
  voice.md, icp.md  default voice and ICP files (paths.voice, paths.icp)

Usage (run as python3 -I -B so no local file can shadow a module):

  python3 -I -B config.py show                 # config with defaults, secrets masked
  python3 -I -B config.py check                # validate; exit 0 ok, 1 errors
  python3 -I -B config.py get notion.field_map.contacts.status
  python3 -I -B config.py set sending.mode dry-run      # value parsed as JSON, else string
  python3 -I -B config.py init                 # write config.json from the template if absent
  python3 -I -B config.py paths                # print the runtime file locations
  python3 -I -B config.py set-secret notion_token       # hidden prompt, needs a terminal
  python3 -I -B config.py has-secret notion_token       # exit 0 set, 1 not set; prints nothing secret
  python3 -I -B config.py state-get [adapter]  # print state.json or one adapter's cursor
  python3 -I -B config.py state-set <adapter> '<json>'  # replace one adapter's cursor

Library use from another lib script:

  import sys, pathlib
  sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
  import config as gtm_config
  cfg = gtm_config.load()
  prop = gtm_config.field(cfg, "contacts", "status")      # -> "Status"
  opt = gtm_config.status(cfg, "Responded")               # -> "Responded"
  key = gtm_config.get_secret("notion_token")              # never print it

Secrets: a value comes from the environment variable GTM_<NAME> (for example
GTM_NOTION_TOKEN) first, then from credentials.json. No command prints a
secret value.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = LIB_DIR.parent
SCHEMA_PATH = PLUGIN_ROOT / "templates" / "schema.json"
EXAMPLE_PATH = PLUGIN_ROOT / "templates" / "config.example.json"

DATABASES = ("contacts", "companies", "pipeline", "campaigns", "meetings")
CONTACT_STATUSES = (
    "New", "Contacted", "Responded", "Discovery", "Lead",
    "Archived", "Do Not Contact", "Disqualified",
)
LADDER = ("New", "Contacted", "Responded", "Discovery", "Lead")
TERMINAL = ("Archived", "Do Not Contact", "Disqualified")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

KNOWN_ADAPTERS = {
    "email": ("gmail", "outlook"),
    "calendar": ("google", "outlook"),
    "linkedin": ("chrome",),
    "meetings": ("fathom", "granola", "fireflies", "otter"),
    "outreach": ("gojiberry", "lemlist", "instantly", "apollo"),
    "enrichment": ("exa", "apollo", "hunter", "mcp"),
    "notify": ("push", "slack", "none"),
}

# Names a secret may have. Anything else is refused by set-secret.
SECRET_NAMES = (
    "notion_token",
    "gojiberry_api_key", "lemlist_api_key", "instantly_api_key", "apollo_api_key",
    "hubspot_token", "pipedrive_api_token", "attio_api_key",
    "fathom_api_key", "hunter_api_key", "fireflies_api_key",
)
_SECRET_KEY_RE = re.compile(r"(token|secret|password|api_key|apikey)", re.I)
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_PLACEHOLDER_RE = re.compile(r"^[0-]*[0-9]?$")


# ---------------------------------------------------------------- locations

def config_dir() -> Path:
    override = os.environ.get("GTM_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".config" / "gtm"


def config_path() -> Path:
    return config_dir() / "config.json"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def state_path() -> Path:
    return config_dir() / "state.json"


def log_path() -> Path:
    return config_dir() / "logs.md"


def expand(path_value: str) -> Path:
    return Path(os.path.expanduser(path_value))


def imports_dir() -> Path:
    return config_dir() / "imports"


def resolve_path(cfg: dict, key: str) -> Path:
    """paths.voice / paths.icp; empty means <config dir>/<key>.md (follows GTM_CONFIG_DIR)."""
    value = ((cfg or {}).get("paths") or {}).get(key) or ""
    return expand(value) if value else config_dir() / f"{key}.md"


# ---------------------------------------------------------------- defaults

def load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def schema_defaults() -> tuple:
    """Return (field_map, option_map) defaults derived from schema.json."""
    schema = load_schema()
    field_map, option_map = {}, {}
    for database in schema["databases"]:
        db = database["logical_name"]
        field_map[db] = {}
        for prop in database["properties"]:
            field_map[db][prop["logical_name"]] = prop["name"]
            if prop["type"] == "select" and not (db == "contacts" and prop["logical_name"] == "status"):
                option_map.setdefault(db, {})[prop["logical_name"]] = {o: o for o in prop.get("options", [])}
    return field_map, option_map


def defaults() -> dict:
    field_map, option_map = schema_defaults()
    return {
        "version": 1,
        "owner": {
            "name": "",
            "emails": [],
            "own_domains": [],
            "timezone": "UTC",
            "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
            "send_window": {"start": "09:00", "end": "17:00"},
        },
        "notion": {
            "access": "mcp",
            "parent_page_id": "",
            "data_sources": {db: "" for db in DATABASES},
            "field_map": field_map,
            "status_map": {s: s for s in CONTACT_STATUSES},
            "option_map": option_map,
            "select_payload": {},
            "funnel_page_id": "",
            "views": {db: "" for db in DATABASES},
        },
        "adapters": {
            "email": "gmail",
            "calendar": "google",
            "linkedin": "chrome",
            "meetings": [],
            "outreach": [],
            "enrichment": [],
            "notify": {"kind": "push", "slack_channel": ""},
        },
        "sending": {
            "mode": "live",
            "sender_email": "",
            "linkedin_daily_invite_cap": 10,
            "email_daily_cap": 40,
            "reply_lookback_days": 30,
            "event_window_days": 14,
        },
        "sweep": {"first_run_lookback_days": 7, "calendar_lookahead_days": 7, "max_meeting_attendees": 15},
        "funnel": {
            "start_month": None,
            "pilot_stages": ["Pilot"],
            "customer_stages": ["Won"],
            "warm_lead_sources": ["Warm Intro"],
            "inbound_lead_sources": ["Inbound"],
            "drop_tolerance_pct": 0,
            "rise_tolerance_pct": 25,
            "max_blank_pct": 10,
            "inbound": [],
        },
        "paths": {"voice": "", "icp": ""},
    }


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# ---------------------------------------------------------------- load

class ConfigError(Exception):
    pass


def read_user_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno})") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    return data


def load() -> dict:
    """Config with defaults filled in. Raises ConfigError on unreadable JSON."""
    return _deep_merge(defaults(), read_user_config())


def get_dotted(cfg: dict, dotted: str):
    node = cfg
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(dotted)
    return node


# ---------------------------------------------------------------- maps

def field(cfg: dict, database: str, logical: str) -> str:
    """Actual Notion property name for a logical field."""
    try:
        return cfg["notion"]["field_map"][database][logical]
    except KeyError:
        raise ConfigError(f"no field_map entry for {database}.{logical}") from None


def status(cfg: dict, logical: str) -> str:
    """Actual option name for a logical contact Status."""
    try:
        return cfg["notion"]["status_map"][logical]
    except KeyError:
        raise ConfigError(f"no status_map entry for {logical!r}") from None


def logical_status(cfg: dict, actual: str):
    """Logical contact Status for an actual option name, or None if unmapped."""
    for logical, value in cfg["notion"]["status_map"].items():
        if value == actual:
            return logical
    return None


def option(cfg: dict, database: str, logical_field: str, logical_option: str) -> str:
    """Actual option name for a select field other than contact Status."""
    if database == "contacts" and logical_field == "status":
        return status(cfg, logical_option)
    try:
        return cfg["notion"]["option_map"][database][logical_field][logical_option]
    except KeyError:
        raise ConfigError(f"no option_map entry for {database}.{logical_field}.{logical_option}") from None


def payload_kind(cfg: dict, database: str, logical_field: str) -> str:
    """'select' (default) or 'status' for a choice field, from notion.select_payload."""
    return (cfg["notion"].get("select_payload") or {}).get(f"{database}.{logical_field}", "select")


def ladder_rank(cfg: dict, actual: str):
    """0..4 for ladder statuses, None for terminal or unknown ones."""
    logical = logical_status(cfg, actual)
    return LADDER.index(logical) if logical in LADDER else None


# ---------------------------------------------------------------- secrets

def _check_mode(path: Path) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode & 0o077:
        print(f"warning: {path} has mode {oct(mode)}; run chmod 600 on it", file=sys.stderr)


def load_credentials() -> dict:
    path = credentials_path()
    if not path.exists():
        return {}
    _check_mode(path)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        raise ConfigError(f"{path} cannot be read as JSON") from None
    return data if isinstance(data, dict) else {}


def get_secret(name: str):
    """Secret value or None. Callers must never print or log the value."""
    env_value = os.environ.get("GTM_" + name.upper())
    if env_value:
        return env_value
    value = load_credentials().get(name)
    return value or None


def _write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def set_secret(name: str) -> None:
    if name not in SECRET_NAMES:
        raise ConfigError(f"unknown secret name {name!r}; allowed: {', '.join(SECRET_NAMES)}")
    if not sys.stdin.isatty():
        raise ConfigError(
            "set-secret needs a terminal so the value is typed at a hidden prompt. "
            "Run this command yourself in a terminal; do not paste the value into a chat."
        )
    value = getpass.getpass(f"Paste {name} (input is hidden): ").strip()
    if not value:
        raise ConfigError("empty value; nothing saved")
    creds = load_credentials()
    creds[name] = value
    _write_private_json(credentials_path(), creds)


# ---------------------------------------------------------------- write

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def set_value(dotted: str, raw: str) -> None:
    if _SECRET_KEY_RE.search(dotted):
        raise ConfigError("secrets do not go in config.json; use set-secret")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    data = read_user_config()
    node = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
    _write_json(config_path(), data)


def init_config() -> bool:
    """Copy the template to config.json when none exists. True if written."""
    path = config_path()
    if path.exists():
        return False
    with open(EXAMPLE_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    _write_json(path, data)
    return True


# ---------------------------------------------------------------- state

def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return {"version": 1, "adapters": {}}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("adapters", {})
    return data


def set_state(adapter: str, cursor) -> None:
    data = load_state()
    data["adapters"][adapter] = cursor
    _write_json(state_path(), data)


# ---------------------------------------------------------------- validate

def _is_placeholder(value: str) -> bool:
    return not value or bool(_PLACEHOLDER_RE.match(value.replace("-", "")))


_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32})")


def _notion_id_ok(value: str) -> bool:
    """True when value holds a 32-hex Notion id (dashes optional, URL allowed) that is not a template placeholder."""
    match = _NOTION_ID_RE.search(str(value).replace("-", ""))
    return bool(match) and not _is_placeholder(match.group(1))


_TEMPLATE_DOMAINS = ("example.com", "example.org", "example.net")


def validate(cfg: dict) -> list:
    """Return a list of (level, message); level is 'error' or 'warning'."""
    issues = []

    def err(msg):
        issues.append(("error", msg))

    def warn(msg):
        issues.append(("warning", msg))

    owner = cfg.get("owner", {})
    if not owner.get("name"):
        warn("owner.name is empty")
    elif owner.get("name") == "Your Name":
        err("owner.name still holds the template value 'Your Name'")
    if not owner.get("emails"):
        err("owner.emails is empty; the sweep cannot tell your own mail from a contact's")
    for addr in owner.get("emails") or []:
        if str(addr).lower().split("@")[-1] in _TEMPLATE_DOMAINS:
            err(f"owner.emails holds the template address {addr!r}")
    if not owner.get("own_domains"):
        warn("owner.own_domains is empty; calendar attendees on your domain will look external")
    for dom in owner.get("own_domains") or []:
        if str(dom).lower() in _TEMPLATE_DOMAINS:
            err(f"owner.own_domains holds the template domain {dom!r}")
    sender = str((cfg.get("sending") or {}).get("sender_email") or "")
    if sender and sender.lower().split("@")[-1] in _TEMPLATE_DOMAINS:
        err(f"sending.sender_email holds the template address {sender!r}")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(owner.get("timezone") or "")
    except Exception:
        err(f"owner.timezone {owner.get('timezone')!r} is not an IANA time zone (for example Europe/Berlin)")
    days = owner.get("working_days") or []
    bad_days = [d for d in days if d not in WEEKDAYS]
    if bad_days or not days:
        err(f"owner.working_days must be a non-empty list of {', '.join(WEEKDAYS)}")
    window = owner.get("send_window") or {}
    start, end = window.get("start", ""), window.get("end", "")
    if not (_TIME_RE.match(str(start)) and _TIME_RE.match(str(end)) and start < end):
        err("owner.send_window needs start and end as HH:MM with start before end")

    notion = cfg.get("notion", {})
    if notion.get("access") not in ("mcp", "rest"):
        err("notion.access must be 'mcp' or 'rest'")
    if notion.get("access") == "rest" and not get_secret("notion_token"):
        err("notion.access is 'rest' but no notion_token is saved; run set-secret notion_token or set access to 'mcp'")
    if not _notion_id_ok(notion.get("parent_page_id", "")):
        err("notion.parent_page_id is empty, a placeholder or not a Notion id (32 hex characters); run /gtm:setup")
    for db in DATABASES:
        value = (notion.get("data_sources") or {}).get(db, "")
        if _is_placeholder(str(value)):
            err(f"notion.data_sources.{db} is empty or a placeholder; run /gtm:setup")
        elif not _notion_id_ok(value):
            err(f"notion.data_sources.{db} {value!r} is not a Notion data source id (32 hex characters, dashes optional)")
    if notion.get("access") == "mcp":
        missing_views = [db for db in DATABASES if not (notion.get("views") or {}).get(db)]
        if missing_views:
            warn(f"notion.views has no view URL for {', '.join(missing_views)}; MCP index reads need a view URL (rows and SQL mode have a small workspace quota); run /gtm:setup databases to record them")
    try:
        field_defaults, option_defaults = schema_defaults()
    except (OSError, json.JSONDecodeError):
        err(f"cannot read {SCHEMA_PATH}")
        field_defaults, option_defaults = {}, {}
    field_map = notion.get("field_map") or {}
    for db, logicals in field_defaults.items():
        for logical in logicals:
            actual = (field_map.get(db) or {}).get(logical)
            if not isinstance(actual, str) or not actual.strip():
                err(f"notion.field_map.{db}.{logical} must be a property name")
    status_map = notion.get("status_map") or {}
    missing = [s for s in CONTACT_STATUSES if not status_map.get(s)]
    if missing:
        err(f"notion.status_map is missing {', '.join(missing)}")
    values = [v for v in status_map.values() if v]
    if len(values) != len(set(values)):
        err("notion.status_map maps two logical statuses to the same option")
    option_map = notion.get("option_map") or {}
    for db, fields in option_defaults.items():
        for logical_field, options in fields.items():
            actual = ((option_map.get(db) or {}).get(logical_field)) or {}
            gaps = [o for o in options if not actual.get(o)]
            if gaps:
                warn(f"notion.option_map.{db}.{logical_field} has no option for {', '.join(gaps)}")
    for prop_ref, kind in (notion.get("select_payload") or {}).items():
        if isinstance(kind, dict):
            err(f"notion.select_payload.{prop_ref} is nested; use a flat key, for example: "
                f"config.py set 'notion.select_payload' '{{\"{prop_ref}.<field>\": \"status\"}}'")
        elif kind not in ("select", "status"):
            err(f"notion.select_payload.{prop_ref} must be 'select' or 'status'")
    if _is_placeholder(str(notion.get("funnel_page_id", ""))):
        warn("notion.funnel_page_id is empty; setup normally creates the Funnel page, and /gtm:funnel creates it under notion.parent_page_id if it is still missing")

    adapters = cfg.get("adapters", {})
    for kind in ("email", "calendar", "linkedin"):
        value = adapters.get(kind)
        if value not in (None, "", "none") and value not in KNOWN_ADAPTERS[kind]:
            err(f"adapters.{kind} {value!r} is not one of {', '.join(KNOWN_ADAPTERS[kind])} or none")
    for kind in ("meetings", "outreach", "enrichment"):
        value = adapters.get(kind) or []
        if not isinstance(value, list):
            err(f"adapters.{kind} must be a list")
            continue
        unknown = [v for v in value if v not in KNOWN_ADAPTERS[kind]]
        if unknown:
            err(f"adapters.{kind} has unknown tools: {', '.join(unknown)}")
    notify = adapters.get("notify") or {}
    if notify.get("kind") not in KNOWN_ADAPTERS["notify"]:
        err("adapters.notify.kind must be push, slack or none")
    if notify.get("kind") == "slack" and not notify.get("slack_channel"):
        err("adapters.notify.kind is slack but adapters.notify.slack_channel is empty")

    sending = cfg.get("sending", {})
    if sending.get("mode") not in ("live", "dry-run"):
        err("sending.mode must be 'live' or 'dry-run'")
    for key in ("linkedin_daily_invite_cap", "email_daily_cap", "reply_lookback_days", "event_window_days"):
        value = sending.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            err(f"sending.{key} must be a whole number of 0 or more")
    cap = sending.get("linkedin_daily_invite_cap")
    if isinstance(cap, int) and cap > 20:
        warn(f"sending.linkedin_daily_invite_cap is {cap}; high invite volume raises the risk that LinkedIn restricts the account")
    sender = sending.get("sender_email") or ""
    if adapters.get("email") and not sender:
        warn("sending.sender_email is empty; campaign-run will not send email")
    elif sender and sender.lower() not in [e.lower() for e in owner.get("emails", [])]:
        warn("sending.sender_email is not in owner.emails")

    sweep = cfg.get("sweep", {})
    for key in ("first_run_lookback_days", "calendar_lookahead_days"):
        value = sweep.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            err(f"sweep.{key} must be a whole number of 0 or more")

    start_month = (cfg.get("funnel") or {}).get("start_month")
    if start_month is not None and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", str(start_month)):
        err("funnel.start_month must be YYYY-MM or null")
    funnel = cfg.get("funnel") or {}
    for key in ("pilot_stages", "customer_stages", "warm_lead_sources", "inbound_lead_sources", "inbound"):
        value = funnel.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            err(f"funnel.{key} must be a list of names")
    if not funnel.get("customer_stages"):
        err("funnel.customer_stages must name at least one pipeline stage")
    for key in ("drop_tolerance_pct", "rise_tolerance_pct", "max_blank_pct"):
        value = funnel.get(key)
        if value is None and key == "rise_tolerance_pct":
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            err(f"funnel.{key} must be a number of 0 or more")
    stage_options = ((cfg.get("notion") or {}).get("option_map") or {}).get("pipeline", {}).get("stage") or {}
    for key in ("pilot_stages", "customer_stages"):
        for name in funnel.get(key) or []:
            if isinstance(name, str) and name not in stage_options:
                warn(f"funnel.{key} names {name!r}, which has no notion.option_map.pipeline.stage entry")

    for key in ("voice", "icp"):
        path = resolve_path(cfg, key)
        if not path.exists():
            warn(f"paths.{key} file {path} does not exist yet")

    for dotted in _secret_like_keys(cfg):
        err(f"{dotted} looks like a secret; secrets belong in credentials.json (set-secret), not config.json")
    return issues


def _secret_like_keys(node, prefix=""):
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            dotted = f"{prefix}.{key}" if prefix else key
            if _SECRET_KEY_RE.search(key) and isinstance(value, str) and value:
                found.append(dotted)
            found.extend(_secret_like_keys(value, dotted))
    return found


def masked(cfg):
    if isinstance(cfg, dict):
        return {k: ("***" if _SECRET_KEY_RE.search(k) and isinstance(v, str) and v else masked(v))
                for k, v in cfg.items()}
    if isinstance(cfg, list):
        return [masked(v) for v in cfg]
    return cfg


# ---------------------------------------------------------------- CLI

def _cmd_show(_args) -> int:
    cfg = load()
    out = masked(cfg)
    creds = load_credentials()
    out["_secrets_saved"] = sorted(
        n for n in SECRET_NAMES if creds.get(n) or os.environ.get("GTM_" + n.upper())
    )
    out["_files"] = _paths_dict()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def _paths_dict() -> dict:
    return {
        "config": str(config_path()),
        "credentials": str(credentials_path()),
        "state": str(state_path()),
        "run_log": str(log_path()),
        "imports": str(imports_dir()),
        "voice": str(resolve_path(load() if config_path().exists() else {}, "voice")),
        "icp": str(resolve_path(load() if config_path().exists() else {}, "icp")),
        "config_exists": config_path().exists(),
    }


def _cmd_check(_args) -> int:
    if not config_path().exists():
        print(f"error: {config_path()} does not exist; run /gtm:setup")
        return 1
    issues = validate(load())
    for level, msg in issues:
        print(f"{level}: {msg}")
    errors = sum(1 for level, _ in issues if level == "error")
    print("ok" if errors == 0 else f"{errors} error(s)")
    return 0 if errors == 0 else 1


def _cmd_get(args) -> int:
    if _SECRET_KEY_RE.search(args.key):
        print("error: use has-secret for secrets", file=sys.stderr)
        return 1
    try:
        value = get_dotted(load(), args.key)
    except KeyError:
        print(f"error: no key {args.key}", file=sys.stderr)
        return 1
    print(value if isinstance(value, str) else json.dumps(masked(value), ensure_ascii=False))
    return 0


def _cmd_set(args) -> int:
    set_value(args.key, args.value)
    print(f"set {args.key}")
    return 0


def _cmd_init(_args) -> int:
    written = init_config()
    print(f"wrote {config_path()}" if written else f"{config_path()} already exists; not changed")
    return 0


def _cmd_paths(_args) -> int:
    print(json.dumps(_paths_dict(), indent=2))
    return 0


def _cmd_set_secret(args) -> int:
    set_secret(args.name)
    print(f"saved {args.name} to {credentials_path()} (mode 600)")
    return 0


def _cmd_has_secret(args) -> int:
    present = bool(get_secret(args.name))
    print("set" if present else "not set")
    return 0 if present else 1


def _cmd_state_get(args) -> int:
    data = load_state()
    if args.adapter:
        print(json.dumps(data["adapters"].get(args.adapter), ensure_ascii=False))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def _cmd_state_set(args) -> int:
    try:
        cursor = json.loads(args.cursor)
    except json.JSONDecodeError:
        print("error: cursor must be JSON", file=sys.stderr)
        return 1
    set_state(args.adapter, cursor)
    print(f"state {args.adapter} updated")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="gtm plugin configuration (default folder ~/.config/gtm, or GTM_CONFIG_DIR). Never prints secret values.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="print config with defaults; secrets masked").set_defaults(func=_cmd_show)
    sub.add_parser("check", help="validate config; exit 1 on errors").set_defaults(func=_cmd_check)
    p = sub.add_parser("get", help="print one value by dotted key")
    p.add_argument("key")
    p.set_defaults(func=_cmd_get)
    p = sub.add_parser("set", help="set one value (JSON or string) in config.json")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(func=_cmd_set)
    sub.add_parser("init", help="write config.json from the template if absent").set_defaults(func=_cmd_init)
    sub.add_parser("paths", help="print runtime file locations").set_defaults(func=_cmd_paths)
    p = sub.add_parser("set-secret", help="save a secret from a hidden prompt (needs a terminal)")
    p.add_argument("name", choices=SECRET_NAMES)
    p.set_defaults(func=_cmd_set_secret)
    p = sub.add_parser("has-secret", help="exit 0 if a secret is saved, 1 if not")
    p.add_argument("name", choices=SECRET_NAMES)
    p.set_defaults(func=_cmd_has_secret)
    p = sub.add_parser("state-get", help="print state.json or one adapter's cursor")
    p.add_argument("adapter", nargs="?")
    p.set_defaults(func=_cmd_state_get)
    p = sub.add_parser("state-set", help="replace one adapter's cursor with a JSON value")
    p.add_argument("adapter")
    p.add_argument("cursor")
    p.set_defaults(func=_cmd_state_set)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
