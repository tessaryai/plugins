#!/usr/bin/env python3
"""Notion REST client for bulk work in the gtm plugin (Python 3 stdlib only).

Use it only when the user saved a Notion integration token in setup. The
Notion MCP connector is the default path; see reference/notion-access.md for
which operation uses which path.

Token: environment variable GTM_NOTION_TOKEN, else key notion_token in
~/.config/gtm/credentials.json. This module never prints the token, the
request headers, or the text of an HTTP or connection exception. Errors carry
only the HTTP status and a short excerpt of the response body.

Usage (always python3 -I; JSON goes in through a file or '-' for stdin and
comes out on stdout or --out FILE):

  notion_rest.py query <data_source_id> [--filter F] [--sorts F] [--limit N] [--simple] [--out F]
  notion_rest.py schema <data_source_id> [--out F]
  notion_rest.py get-page <page_id> [--simple] [--out F]
  notion_rest.py blocks <block_id> [--recursive] [--out F]
  notion_rest.py append <page_id> --in F        # F: JSON array of strings, one paragraph each
  notion_rest.py update <page_id> --in F        # F: {"properties": {...}} in Notion API shape
  notion_rest.py create <data_source_id> --in F # F: {"properties": {...}, "children_lines": [..]}

Exit codes: 0 done, 1 usage or bad input, 2 Notion could not be reached or
refused the request (auth, 4xx, 5xx).

blocks output: {"blocks": [{"id", "type", "plain_text", "has_children",
"language"?, "children"?}], "text": "<all plain_text joined with newlines>"}.
plain_text keeps the exact characters and line breaks of each block, so a
copy block read this way can be compared word for word.
"""
from __future__ import annotations

import argparse
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

NOTION_VERSION = "2025-09-03"
BASE_URL = "https://api.notion.com/v1"
TIMEOUT = 40
MAX_RETRIES = 5
MAX_CHILDREN_PER_CALL = 100
MAX_TEXT_CHARS = 2000
_ID_RE = re.compile(r"([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12})")


class NotionAPIError(Exception):
    """A failed Notion call. Holds only the status and a body excerpt."""

    def __init__(self, status, body_excerpt=""):
        self.status = status
        self.body_excerpt = (body_excerpt or "")[:300]
        super().__init__(f"Notion API error ({status}): {self.body_excerpt}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise NotionAPIError(code, "redirect refused")


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(request, timeout):
    """Single network call. Tests replace this function."""
    return _OPENER.open(request, timeout=timeout)


def normalize_id(value: str) -> str:
    """Accept a Notion id with or without dashes, or a Notion URL; return the dashed id."""
    match = _ID_RE.search(value or "")
    if not match:
        raise ValueError(f"not a Notion id: {value!r}")
    raw = match.group(1).replace("-", "").lower()
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def _token() -> str:
    token = gtm_config.get_secret("notion_token")
    if not token:
        raise NotionAPIError("no-token", "no notion_token saved; run config.py set-secret notion_token or use the MCP path")
    return token


def request(method: str, path: str, body=None, params=None):
    """One Notion call with retry on 429 and 5xx. Returns parsed JSON."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # Creating pages and appending blocks is not idempotent: a retry after a
    # 5xx or a dropped connection can write a duplicate page or marker. Retry
    # those only on 429 (the request was rejected before it ran).
    idempotent = method in ("GET",) or path.endswith("/query") or method == "PATCH" and "/children" not in path
    attempt = 0
    while True:
        attempt += 1
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + _token())
        req.add_header("Notion-Version", NOTION_VERSION)
        req.add_header("Content-Type", "application/json")
        try:
            with _open(req, TIMEOUT) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                excerpt = exc.read(2000).decode("utf-8", "replace")
            except Exception:
                excerpt = ""
            retry_after = None
            try:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
            except Exception:
                retry_after = None
            if status == 429 and attempt < MAX_RETRIES:
                time.sleep(min(float(retry_after or 2), 30))
                continue
            if status in (500, 502, 503, 504) and idempotent and attempt < 3:
                time.sleep(2 * attempt)
                continue
            raise NotionAPIError(status, excerpt) from None
        except NotionAPIError:
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
            if idempotent and attempt < 3:
                time.sleep(2 * attempt)
                continue
            raise NotionAPIError("connection_error", "request failed before a response was received") from None
        except ValueError:
            raise NotionAPIError("bad_response", "response was not JSON") from None


# ---------------------------------------------------------------- reads

def query_data_source(data_source_id, filter=None, sorts=None, limit=None):
    """All pages matching the filter, following next_cursor."""
    ds = normalize_id(data_source_id)
    results, payload = [], {"page_size": 100}
    if filter:
        payload["filter"] = filter
    if sorts:
        payload["sorts"] = sorts
    while True:
        body = request("POST", f"data_sources/{ds}/query", payload)
        results.extend(body.get("results", []))
        if limit and len(results) >= limit:
            return results[:limit]
        if not body.get("has_more"):
            return results
        payload["start_cursor"] = body["next_cursor"]


def get_data_source(data_source_id):
    return request("GET", f"data_sources/{normalize_id(data_source_id)}")


def get_page(page_id):
    return request("GET", f"pages/{normalize_id(page_id)}")


def _rich_plain(rich_text) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text or [])


def _block_summary(block) -> dict:
    kind = block.get("type", "")
    content = block.get(kind) or {}
    if "rich_text" in content:
        text = _rich_plain(content.get("rich_text"))
    elif kind == "child_page":
        text = content.get("title", "")
    elif kind == "child_database":
        text = content.get("title", "")
    else:
        text = ""
    out = {"id": block.get("id"), "type": kind, "plain_text": text,
           "has_children": bool(block.get("has_children"))}
    if kind == "code":
        out["language"] = content.get("language")
    if kind == "to_do":
        out["checked"] = bool(content.get("checked"))
    return out


def get_block_children(block_id, recursive=False):
    """Every child block (all pages) as summaries with exact plain_text."""
    bid = normalize_id(block_id)
    blocks, params = [], {"page_size": 100}
    while True:
        body = request("GET", f"blocks/{bid}/children", params=params)
        for block in body.get("results", []):
            summary = _block_summary(block)
            if recursive and summary["has_children"] and summary["type"] not in ("child_page", "child_database"):
                summary["children"] = get_block_children(summary["id"], recursive=True)
            blocks.append(summary)
        if not body.get("has_more"):
            return blocks
        params = {"page_size": 100, "start_cursor": body["next_cursor"]}


def blocks_text(blocks, depth=0) -> str:
    lines = []
    for block in blocks:
        lines.append(block["plain_text"])
        if block.get("children"):
            lines.append(blocks_text(block["children"], depth + 1))
    return "\n".join(lines)


def simplify_properties(page) -> dict:
    """Flatten a page's properties to {name: plain value} for reading."""
    out = {"_id": page.get("id"), "_url": page.get("url"), "_created_time": page.get("created_time")}
    for name, prop in (page.get("properties") or {}).items():
        kind = prop.get("type")
        value = prop.get(kind)
        if kind in ("title", "rich_text"):
            out[name] = _rich_plain(value)
        elif kind in ("select", "status"):
            out[name] = value.get("name") if value else None
        elif kind == "multi_select":
            out[name] = [v.get("name") for v in value or []]
        elif kind == "date":
            out[name] = value.get("start") if value else None
        elif kind == "relation":
            out[name] = [v.get("id") for v in value or []]
        elif kind == "people":
            out[name] = [v.get("id") for v in value or []]
        elif kind in ("formula", "rollup"):
            out[name] = value
        else:
            out[name] = value
    return out


# ---------------------------------------------------------------- writes

def _paragraph(text: str) -> dict:
    chunks = [text[i:i + MAX_TEXT_CHARS] for i in range(0, len(text), MAX_TEXT_CHARS)] or [""]
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": c}} for c in chunks]}}


def append_paragraphs(page_id, lines):
    """Append one paragraph per line, in order. Uses PATCH, 100 blocks per call."""
    pid = normalize_id(page_id)
    blocks = [_paragraph(str(line)) for line in lines]
    added = []
    for i in range(0, len(blocks), MAX_CHILDREN_PER_CALL):
        body = request("PATCH", f"blocks/{pid}/children", {"children": blocks[i:i + MAX_CHILDREN_PER_CALL]})
        added.extend(b.get("id") for b in body.get("results", []))
    return added


def update_page(page_id, properties):
    return request("PATCH", f"pages/{normalize_id(page_id)}", {"properties": properties})


def create_page(data_source_id, properties, children_lines=None):
    body = {"parent": {"type": "data_source_id", "data_source_id": normalize_id(data_source_id)},
            "properties": properties}
    lines = list(children_lines or [])
    if lines:
        body["children"] = [_paragraph(str(l)) for l in lines[:MAX_CHILDREN_PER_CALL]]
    page = request("POST", "pages", body)
    if len(lines) > MAX_CHILDREN_PER_CALL:
        append_paragraphs(page["id"], lines[MAX_CHILDREN_PER_CALL:])
    return page


# ---------------------------------------------------------------- CLI

def _read_json(path):
    if path is None:
        return None
    try:
        if path == "-":
            return json.load(sys.stdin)
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON from {path}: {exc.__class__.__name__}") from None


def _emit(data, out):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Notion REST client for the gtm plugin. Never prints the token.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("query", help="query a data source, all pages")
    p.add_argument("data_source_id")
    p.add_argument("--filter", help="JSON file with a Notion filter object, or -")
    p.add_argument("--sorts", help="JSON file with a Notion sorts array")
    p.add_argument("--limit", type=int)
    p.add_argument("--simple", action="store_true", help="flatten properties to plain values")
    p.add_argument("--out")

    p = sub.add_parser("schema", help="data source properties and select options")
    p.add_argument("data_source_id")
    p.add_argument("--out")

    p = sub.add_parser("get-page", help="one page's properties")
    p.add_argument("page_id")
    p.add_argument("--simple", action="store_true")
    p.add_argument("--out")

    p = sub.add_parser("blocks", help="a page's body blocks with exact plain_text")
    p.add_argument("block_id")
    p.add_argument("--recursive", action="store_true", help="also read nested blocks (toggles, lists)")
    p.add_argument("--out")

    p = sub.add_parser("append", help="append paragraphs to a page body")
    p.add_argument("page_id")
    p.add_argument("--in", dest="infile", required=True, help="JSON array of strings, or -")

    p = sub.add_parser("update", help="update page properties")
    p.add_argument("page_id")
    p.add_argument("--in", dest="infile", required=True, help='JSON {"properties": {...}}, or -')
    p.add_argument("--out")

    p = sub.add_parser("create", help="create a page in a data source")
    p.add_argument("data_source_id")
    p.add_argument("--in", dest="infile", required=True,
                   help='JSON {"properties": {...}, "children_lines": [...]}, or -')
    p.add_argument("--out")

    args = parser.parse_args(argv)
    try:
        if args.command == "query":
            pages = query_data_source(args.data_source_id, _read_json(args.filter), _read_json(args.sorts), args.limit)
            _emit([simplify_properties(pg) for pg in pages] if args.simple else pages, args.out)
        elif args.command == "schema":
            ds = get_data_source(args.data_source_id)
            props = {}
            for name, prop in (ds.get("properties") or {}).items():
                entry = {"type": prop.get("type")}
                inner = prop.get(prop.get("type")) or {}
                if isinstance(inner, dict) and "options" in inner:
                    entry["options"] = [o.get("name") for o in inner["options"]]
                if prop.get("type") == "relation":
                    entry["data_source_id"] = inner.get("data_source_id")
                props[name] = entry
            _emit({"id": ds.get("id"), "title": _rich_plain(ds.get("title")), "properties": props}, args.out)
        elif args.command == "get-page":
            page = get_page(args.page_id)
            _emit(simplify_properties(page) if args.simple else page, args.out)
        elif args.command == "blocks":
            blocks = get_block_children(args.block_id, recursive=args.recursive)
            _emit({"blocks": blocks, "text": blocks_text(blocks)}, args.out)
        elif args.command == "append":
            lines = _read_json(args.infile)
            if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
                raise ValueError("append input must be a JSON array of strings")
            ids = append_paragraphs(args.page_id, lines)
            print(json.dumps({"appended": len(ids)}))
        elif args.command == "update":
            data = _read_json(args.infile) or {}
            props = data.get("properties", data)
            _emit(simplify_properties(update_page(args.page_id, props)), getattr(args, "out", None))
        elif args.command == "create":
            data = _read_json(args.infile) or {}
            page = create_page(args.data_source_id, data.get("properties") or {}, data.get("children_lines"))
            _emit(simplify_properties(page), getattr(args, "out", None))
    except NotionAPIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, gtm_config.ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
