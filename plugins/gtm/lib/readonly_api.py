#!/usr/bin/env python3
"""Read-only HTTP client for the gtm plugin's adapters (Python 3 stdlib only).

Many vendor API keys cannot be scoped to read-only: the same key can send
messages, change campaigns or delete records. This file is the limit on our
side. Adapters and the import skill call vendor APIs only through it.

- It sends GET requests only, to a fixed list of base URLs and path patterns
  per tool (ALLOWLIST below). A path must match a pattern in full.
- The one exception is a read-only GraphQL endpoint (Fireflies), reached only
  through the 'graphql' command, which refuses any query text that contains
  'mutation' or 'subscription'.
- Query values come only from --param. The path may not hold '?', '#', '@',
  '..', '%', whitespace or a backslash.
- It never follows a redirect and never puts a key in a URL.
- It never prints a key, the request headers or the text of an HTTP or
  connection exception. Errors carry only the status and a short body excerpt.
- Never edit ALLOWLIST during a run. A path that is not listed is refused; a
  skill that needs it reports the gap to the user instead.

Keys come from ~/.config/gtm/credentials.json (or env GTM_<NAME>); save them
with `config.py set-secret <name>`.

Usage (always python3 -I):

  readonly_api.py tools                                   # list tools, bases, paths, key names
  readonly_api.py <tool> get <path> [--param k=v ...] [--out FILE]
  readonly_api.py fireflies graphql --query-file F [--variables-file F] [--out FILE]
  readonly_api.py <tool> check                            # exit 0 when the key works

Examples:

  readonly_api.py hubspot get /crm/v3/objects/contacts --param limit=100 --param after=123 --out c.json
  readonly_api.py gojiberry get /v1/campaign/42/logs --param page=1 --out logs.json

Exit codes: 0 done, 1 refused (tool, verb, path) or usage, 2 the tool cannot
be read (no key, auth error, other HTTP error, network). Exit 2 means the
adapter is blocked.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as gtm_config  # noqa: E402

TIMEOUT = 40
MAX_RETRIES = 5

# auth: ("bearer", None) | ("header", "<Header-Name>") | ("basic_password", None)
# Fixed at write time. Do not change at run time.
ALLOWLIST = {
    "gojiberry": {
        "base": "https://ext.gojiberry.ai",
        "secret": "gojiberry_api_key",
        "auth": ("bearer", None),
        "paths": [
            r"/v1/user/me",
            r"/v1/campaign",
            r"/v1/campaign/\d+",
            r"/v1/campaign/\d+/logs",
            r"/v1/contact",
            r"/v1/contact/\d+",
            r"/v1/unibox/contact/\d+",
            r"/v1/unibox/threads/\d+/messages",
        ],
        "check": "/v1/user/me",
    },
    "lemlist": {
        "base": "https://api.lemlist.com",
        "secret": "lemlist_api_key",
        "auth": ("basic_password", None),
        "paths": [
            r"/api/team",
            r"/api/campaigns",
            r"/api/campaigns/[A-Za-z0-9_-]+",
            r"/api/campaigns/[A-Za-z0-9_-]+/export",
            r"/api/activities",
            r"/api/unsubscribes",
        ],
        "check": "/api/team",
    },
    "instantly": {
        "base": "https://api.instantly.ai",
        "secret": "instantly_api_key",
        "auth": ("bearer", None),
        "paths": [
            r"/api/v2/campaigns",
            r"/api/v2/campaigns/analytics",
            r"/api/v2/campaigns/analytics/overview",
            r"/api/v2/campaigns/[A-Za-z0-9-]+",
            r"/api/v2/emails",
            r"/api/v2/emails/[A-Za-z0-9-]+",
            r"/api/v2/accounts",
        ],
        "check": "/api/v2/campaigns",
    },
    "apollo": {
        "base": "https://api.apollo.io",
        "secret": "apollo_api_key",
        "auth": ("header", "x-api-key"),
        "paths": [
            r"/api/v1/auth/health",
            r"/api/v1/contacts/[A-Za-z0-9]+",
            r"/api/v1/accounts/[A-Za-z0-9]+",
            r"/api/v1/emailer_campaigns/[A-Za-z0-9]+",
        ],
        "check": "/api/v1/auth/health",
    },
    "hubspot": {
        "base": "https://api.hubapi.com",
        "secret": "hubspot_token",
        "auth": ("bearer", None),
        "paths": [
            r"/crm/v3/objects/(contacts|companies|deals|meetings|notes|emails|calls)",
            r"/crm/v3/objects/(contacts|companies|deals|meetings|notes|emails|calls)/\d+",
            r"/crm/v3/properties/(contacts|companies|deals)",
            r"/crm/v3/pipelines/deals",
            r"/crm/v3/pipelines/deals/[A-Za-z0-9_-]+",
            r"/crm/v3/owners",
            r"/crm/v3/owners/\d+",
            r"/crm/v4/objects/(contacts|companies|deals)/\d+/associations/(contacts|companies|deals)",
            r"/account-info/v3/details",
        ],
        "check": "/account-info/v3/details",
    },
    "pipedrive": {
        "base": "https://api.pipedrive.com",
        "secret": "pipedrive_api_token",
        "auth": ("header", "x-api-token"),
        "paths": [
            r"/v1/(persons|organizations|deals|stages|pipelines|activities|notes|users)",
            r"/v1/(persons|organizations|deals|stages|pipelines|activities|notes|users)/\d+",
            r"/v1/(personFields|organizationFields|dealFields)",
            r"/v1/users/me",
            r"/api/v2/(persons|organizations|deals|stages|pipelines|activities)",
            r"/api/v2/(persons|organizations|deals|stages|pipelines|activities)/\d+",
        ],
        "check": "/v1/users/me",
    },
    "attio": {
        "base": "https://api.attio.com",
        "secret": "attio_api_key",
        "auth": ("bearer", None),
        "paths": [
            r"/v2/self",
            r"/v2/objects",
            r"/v2/objects/[A-Za-z0-9_-]+",
            r"/v2/objects/[A-Za-z0-9_-]+/attributes",
            r"/v2/objects/[A-Za-z0-9_-]+/records/[A-Za-z0-9-]+",
            r"/v2/lists",
            r"/v2/lists/[A-Za-z0-9_-]+",
            r"/v2/workspace_members",
        ],
        "check": "/v2/self",
    },
    "fathom": {
        "base": "https://api.fathom.ai",
        "secret": "fathom_api_key",
        "auth": ("header", "X-Api-Key"),
        "paths": [
            r"/external/v1/meetings",
            r"/external/v1/recordings/\d+/summary",
            r"/external/v1/recordings/\d+/transcript",
            r"/external/v1/teams",
            r"/external/v1/team_members",
        ],
        "check": "/external/v1/meetings",
    },
    "hunter": {
        "base": "https://api.hunter.io",
        "secret": "hunter_api_key",
        "auth": ("header", "X-API-KEY"),
        "paths": [
            r"/v2/account",
            r"/v2/domain-search",
            r"/v2/email-finder",
            r"/v2/email-verifier",
            r"/v2/email-count",
        ],
        "check": "/v2/account",
    },
    "fireflies": {
        "base": "https://api.fireflies.ai",
        "secret": "fireflies_api_key",
        "auth": ("bearer", None),
        "paths": [],
        "graphql": "/graphql",
        "check_query": "query { user { user_id } }",
    },
}

_BAD_PATH_RE = re.compile(r"[?#@%\\\s]|\.\.")
_WRITE_GRAPHQL_RE = re.compile(r"\b(mutation|subscription)\b", re.I)


class ReadError(Exception):
    """A failed read. Holds only the status and a short body excerpt."""

    def __init__(self, status, excerpt=""):
        self.status = status
        self.excerpt = (excerpt or "")[:200]
        super().__init__(f"read failed: status={status} body={self.excerpt!r}")


class Refused(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReadError(code, "redirect refused")


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(request, timeout):
    """Single network call. Tests replace this function."""
    return _OPENER.open(request, timeout=timeout)


def path_is_allowed(tool: str, path: str) -> bool:
    spec = ALLOWLIST.get(tool)
    if not spec or not path.startswith("/") or _BAD_PATH_RE.search(path):
        return False
    return any(re.fullmatch(pattern, path) for pattern in spec["paths"])


def _auth_header(tool: str):
    spec = ALLOWLIST[tool]
    key = gtm_config.get_secret(spec["secret"])
    if not key:
        raise ReadError("no-key", f"no {spec['secret']} saved; run config.py set-secret {spec['secret']}")
    kind, name = spec["auth"]
    if kind == "bearer":
        return "Authorization", "Bearer " + key
    if kind == "basic_password":
        return "Authorization", "Basic " + base64.b64encode((":" + key).encode()).decode()
    return name, key


def _send(tool: str, method: str, url: str, data=None):
    attempt = 0
    while True:
        attempt += 1
        req = urllib.request.Request(url, data=data, method=method)
        header, value = _auth_header(tool)
        req.add_header(header, value)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with _open(req, TIMEOUT) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
        except urllib.error.HTTPError as exc:
            try:
                excerpt = exc.read(400).decode("utf-8", "replace")
            except Exception:
                excerpt = ""
            retry_after = None
            try:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
            except Exception:
                pass
            if exc.code == 429 and attempt < MAX_RETRIES:
                try:
                    wait = float(retry_after or 5)
                except ValueError:
                    wait = 5
                time.sleep(min(wait, 65))
                continue
            if exc.code in (502, 503, 504) and attempt < 3:
                time.sleep(2 * attempt)
                continue
            raise ReadError(exc.code, excerpt) from None
        except ReadError:
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
            raise ReadError("connection-error", "request failed before a response was received") from None
        text = raw.decode("utf-8", "replace")
        if "json" in ctype or text[:1] in "{[":
            try:
                return json.loads(text)
            except ValueError:
                pass
        return {"_raw_text": text, "_content_type": ctype}


def read(tool: str, path: str, params=None):
    """GET one allowed path. There is no other verb here."""
    if tool not in ALLOWLIST:
        raise Refused(f"unknown tool {tool!r}")
    if not path_is_allowed(tool, path):
        raise Refused(f"path is not on the read-only list for {tool}: {path}")
    url = ALLOWLIST[tool]["base"] + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    return _send(tool, "GET", url)


def graphql(tool: str, query: str, variables=None):
    """Read-only GraphQL query. Refuses mutations and subscriptions."""
    spec = ALLOWLIST.get(tool) or {}
    if not spec.get("graphql"):
        raise Refused(f"{tool} has no read-only GraphQL endpoint")
    if _WRITE_GRAPHQL_RE.search(query or ""):
        raise Refused("query text contains 'mutation' or 'subscription'; only read queries are allowed")
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    result = _send(tool, "POST", spec["base"] + spec["graphql"], body)
    if isinstance(result, dict) and result.get("errors") and not result.get("data"):
        raise ReadError("graphql-error", json.dumps(result["errors"])[:200])
    return result


def check(tool: str):
    spec = ALLOWLIST.get(tool)
    if not spec:
        raise Refused(f"unknown tool {tool!r}")
    if spec.get("graphql"):
        return graphql(tool, spec["check_query"])
    return read(tool, spec["check"])


def _emit(data, out):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)


def _parse_params(pairs):
    params = []
    for pair in pairs or []:
        if "=" not in pair:
            raise Refused(f"--param needs k=v, got {pair!r}")
        key, value = pair.split("=", 1)
        params.append((key, value))
    return params


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "tools":
        _emit({t: {"base": s["base"], "key_name": s["secret"],
                   "get_paths": s["paths"], "graphql": s.get("graphql")}
               for t, s in ALLOWLIST.items()}, None)
        return 0
    parser = argparse.ArgumentParser(prog="readonly_api.py", description="Read-only vendor API client.")
    parser.add_argument("tool", choices=sorted(ALLOWLIST))
    parser.add_argument("verb", help="get, graphql or check; nothing else is accepted")
    parser.add_argument("path", nargs="?")
    parser.add_argument("--param", action="append", default=[], help="query parameter k=v (repeatable)")
    parser.add_argument("--query-file")
    parser.add_argument("--variables-file")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        if args.verb == "get":
            if not args.path:
                raise Refused("get needs a path")
            _emit(read(args.tool, args.path, _parse_params(args.param)), args.out)
        elif args.verb == "graphql":
            if not args.query_file:
                raise Refused("graphql needs --query-file")
            query = Path(args.query_file).read_text(encoding="utf-8")
            variables = json.loads(Path(args.variables_file).read_text(encoding="utf-8")) if args.variables_file else None
            _emit(graphql(args.tool, query, variables), args.out)
        elif args.verb == "check":
            check(args.tool)
            print(f"{args.tool}: ok")
        else:
            raise Refused(f"verb {args.verb!r} is not allowed; this client only reads")
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except ReadError as exc:
        print(f"error: {args.tool} {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: bad input ({exc.__class__.__name__})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
