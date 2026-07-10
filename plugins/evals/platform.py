#!/usr/bin/env python3
"""platform.py — the evals *assistant's* thin client to evals.tessary.ai.

Distinct from `publish.py` (which pushes a full synthesized `.tessary/` bundle).
This is the **integration front door** driven by the `connect` skill: link a repo
to a project, report project status, and wire the platform's authenticated MCP
server into the user's Claude Code so the coding agent gets native tools
(`list_call_sites`, `list_graders`, `query_*`, `run_triage`, `propose_grader_edit`,
…) instead of shelling out to Python for every read.

It deliberately reuses `publish.py`'s HTTP / TLS / credentials / device-link
plumbing (same directory) rather than duplicating ~150 lines.

It is also the read side that `synthesize-graders` grounds on: `envs` /
`preflight` / `coverage` / `fetch-traces` answer "is there real telemetry for
this call site in this environment, and give me its spans verbatim". Call-site
identity is the explicit `tessary.call_site.id` span tag and nothing else, so an
untagged span is invisible to all four (explicit-or-nothing).

Subcommands (all stdlib-only):

  link          Device-authorization handshake → stores a project-scoped ADMIN token
                under ~/.config/tessary-evals/credentials.json (keyed by repo path).
                A no-op if the repo is already linked with a still-valid token.
  status        Print the linked project's org/project slugs + call-site / grader /
                failure-mode counts (a quick "am I connected and what's here?").
  mcp-add       Print (default) or --run the `claude mcp add` command that registers
                the platform MCP server for THIS repo at `local` scope — the token is
                stored privately in ~/.claude.json, never in a committed file.
  unlink        Tear down the link for a repo: remove the local MCP registration AND
                delete the repo's stored credential (the one place both are undone).
  token         Print the stored bearer token — GATED behind --reveal (it is a live,
                high-privilege secret); used internally by mcp-add, rarely by hand.
  envs          One line per environment: tagged-span count + distinct call sites.
  preflight     Gate: does <env> carry usable tagged telemetry? Exit code is the answer.
  coverage      Per-call-site span counts in <env>, plus the untagged residue.
  fetch-traces  Full trace detail for one call site in <env>, one JSON object per
                line, content verbatim. Bounded by trace COUNT, never truncation.

Exit codes (the runbook branches on these, so they are contract):

  0  ok
  1  not linked (or the stored token was rejected) → run `link` / /evals:connect
  2  the platform did not answer: network/TLS failure (raised by publish._request),
     or it answered with 403/404/5xx. Also argparse's own usage-error code — both
     mean "this invocation produced no data", so the runbook treats them alike.
  3  linked, but <env> has no tagged telemetry → run /evals:instrument, then
     exercise the app. Deliberately distinct from 1: "nothing to ground on" is
     not "not connected".
  4  unknown environment slug

Credentials are keyed by repo root exactly as `publish.py` keys them (the parent
of `<repo>/.tessary`), so a repo linked here is also "linked" for a later
`publish.py upload`, and vice-versa — one link, one token, both paths.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, NamedTuple

# Reuse publish.py's plumbing (same dir). When run as a script, sys.path[0] is
# this file's directory, so a bare `import publish` resolves.
import publish  # noqa: E402


def _evals_dir(repo: str) -> Path:
    """The notional `.tessary` dir for a repo, whether or not it exists yet.

    publish.py keys credentials by `evals_dir.resolve().parent` (the repo root),
    so we pass `<repo>/.tessary` to share the exact same credential key — a repo
    connected here is recognized by `publish.py` and vice-versa."""
    return Path(repo).resolve() / ".tessary"


# --------------------------------------------------------------------- link

def cmd_link(args: argparse.Namespace) -> int:
    """Device-authorization handshake, delegated to publish.cmd_link so the
    stored-credential shape is identical across both entry points."""
    ns = argparse.Namespace(
        base_url=args.base_url,
        evals_dir=str(_evals_dir(args.repo)),
        label=args.label,
        force=args.force,
    )
    return publish.cmd_link(ns)


# ------------------------------------------------------------------- status

def _require_link(repo: str) -> dict[str, Any]:
    proj = publish.linked_project(_evals_dir(repo))
    if not proj or not proj.get("token"):
        print("not linked yet — run `platform.py link` (or /evals:connect) first", file=sys.stderr)
        raise SystemExit(1)
    return proj


def cmd_status(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    url = proj.get("base_url") or publish.base_url(args.base_url)
    org, project, token = proj["org_slug"], proj["project_slug"], proj["token"]
    api = f"{url}/api/orgs/{org}/projects/{project}"

    # Project summary — also the token liveness check.
    code, summary = publish.get_json(api, token=token)
    if code == 401:
        print("stored token was rejected (revoked or expired) — re-run `platform.py link --force`",
              file=sys.stderr)
        return 1
    if code != 200:
        print(f"could not read project (HTTP {code})", file=sys.stderr)
        return 1

    # Pipeline envelope carries the call-site / grader / failure-mode inventory.
    pcode, penv = publish.get_json(f"{api}/pipeline", token=token)
    if pcode == 401:
        # A 401 here is a token problem, not an empty project — don't mislead toward "bootstrap".
        print("stored token was rejected on the pipeline read (revoked or expired) — re-run "
              "`platform.py link --force`", file=sys.stderr)
        return 1
    pipeline = (penv.get("data") or {}).get("pipeline") or {} if pcode == 200 else {}

    def _count(key: str) -> int | str:
        v = pipeline.get(key)
        return len(v) if isinstance(v, list) else ("?" if pcode != 200 else 0)

    print(f"Linked to {org}/{project}  ({url})")
    proj_data = summary.get("data") or {}
    name = proj_data.get("name") or project
    print(f"  project:        {name}")
    counts = {k: _count(k) for k in ("callSites", "graders", "failureModes", "qualityDimensions")}
    print(f"  call sites:     {counts['callSites']}")
    print(f"  graders:        {counts['graders']}")
    print(f"  failure modes:  {counts['failureModes']}")
    print(f"  quality dims:   {counts['qualityDimensions']}")
    numeric = [v for v in counts.values() if isinstance(v, int)]
    if pcode != 200 or (numeric and sum(numeric) == 0):
        # An empty/absent pipeline is a normal new-project state, not an error — say so on stdout so a
        # relayed status doesn't read as a broken wall of zeros.
        print("  → this project has no synthesized pipeline yet; nothing to assess until graders exist "
              "(tag your call sites with /evals:instrument if they aren't yet, then bootstrap with "
              "/evals:synthesize-graders).")
    return 0


# ------------------------------------------------------------------ mcp-add

MCP_SERVER_NAME = "tessary-evals"


def _mcp_add_command(url: str, token: str) -> list[str]:
    """`claude mcp add` argv that registers the platform's streamable-HTTP MCP
    server at `local` scope (private to this repo, stored in ~/.claude.json — the
    token never lands in a committed file)."""
    return [
        "claude", "mcp", "add",
        "--transport", "http",
        "--scope", "local",
        MCP_SERVER_NAME,
        f"{url}/mcp",
        "--header", f"Authorization: Bearer {token}",
    ]


def _claude_available() -> bool:
    """True iff the `claude` CLI is invocable on PATH (a `claude --version` succeeds)."""
    try:
        return subprocess.run(["claude", "--version"], capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def cmd_mcp_add(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    url = proj.get("base_url") or publish.base_url(args.base_url)
    token = proj["token"]
    cmd = _mcp_add_command(url, token)

    if not args.run:
        # Informational only: print the command with the token MASKED. This masked line is not
        # runnable — registration must go through `--run` (which reads the real token from stored
        # credentials). Do NOT hand-assemble this with a real token (that leaks it into shell history).
        masked = token[:4] + "…" + token[-4:] if len(token) > 8 else "…"
        shown = [c.replace(token, masked) if token in c else c for c in cmd]
        print(" ".join(shlex.quote(c) for c in shown))
        print("\n(preview only — the token is masked. Run `platform.py mcp-add --run`, which reads the "
              "real token internally. Never paste a token by hand.)", file=sys.stderr)
        return 0

    # Precondition FIRST: the `claude` CLI must be on PATH. Check BEFORE removing anything, so a PATH
    # problem (mise/asdf shim, devcontainer) can never leave the repo with zero MCP tools.
    if not _claude_available():
        print("the `claude` CLI isn't on PATH, so I can't register the MCP server — your existing "
              "registration (if any) is untouched. Fix PATH (e.g. your version-manager shim or "
              "devcontainer) and re-run `/evals:connect`.", file=sys.stderr)
        return 127

    # Refresh = remove-then-add (claude has no in-place update). The pre-check above makes the `add`
    # overwhelmingly likely to succeed; if it still fails, say plainly that the old registration is gone.
    subprocess.run(["claude", "mcp", "remove", "--scope", "local", MCP_SERVER_NAME],
                   capture_output=True, text=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr or res.stdout)
        print(f"\n`claude mcp add` failed (exit {res.returncode}). Any previous '{MCP_SERVER_NAME}' "
              "registration was removed during this refresh — re-run `/evals:connect` to restore it.",
              file=sys.stderr)
        return res.returncode
    print(f"Registered MCP server '{MCP_SERVER_NAME}' → {url}/mcp (local scope).")
    print("Reconnect / restart this session so the platform tools load, then ask e.g. "
          "\"list my call sites\" or \"what's failing this week?\".")
    return 0


# -------------------------------------------------------------------- unlink

def _forget_credentials(evals_dir: Path) -> bool:
    """Delete this repo's entry from credentials.json. Returns True if one was removed."""
    cfg = publish.load_config()
    key = publish.repo_key(evals_dir)
    if key not in cfg.get("projects", {}):
        return False
    del cfg["projects"][key]
    p = publish.config_path()
    p.write_text(json.dumps(cfg, indent=2))
    os.chmod(p, 0o600)
    return True


def cmd_unlink(args: argparse.Namespace) -> int:
    """The single place both credential copies are torn down together: the local MCP registration
    (~/.claude.json) and the stored credential (credentials.json)."""
    evals_dir = _evals_dir(args.repo)
    proj = publish.linked_project(evals_dir)

    # (a) Remove the repo-local MCP registration (best-effort; fine if `claude` is absent or none exists).
    mcp_removed = False
    if _claude_available():
        r = subprocess.run(["claude", "mcp", "remove", "--scope", "local", MCP_SERVER_NAME],
                           capture_output=True, text=True)
        mcp_removed = r.returncode == 0

    # (b) Delete the stored credential entry.
    cred_removed = _forget_credentials(evals_dir)

    if not proj and not cred_removed and not mcp_removed:
        print("nothing to unlink — this repo isn't linked.", file=sys.stderr)
        return 0
    print(f"Unlinked this repo. Removed: "
          f"{'MCP registration' if mcp_removed else 'no MCP registration'}, "
          f"{'stored credential' if cred_removed else 'no stored credential'}.")
    # The server-side token still exists — the plugin holds only the plaintext value, not the key id
    # needed to revoke it, so a real revoke is a platform-UI action.
    print("The project-scoped token still exists server-side — if it may be exposed, revoke it in the "
          "platform UI (Settings → API keys).", file=sys.stderr)
    return 0


# -------------------------------------------------------------------- token

def cmd_token(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    if not args.reveal:
        # Guard the raw secret behind an explicit flag: without it, an agent (or a prompt-injection in
        # a linked repo) can't cause the live, high-privilege token to be printed into the transcript.
        print("refusing to print the token without --reveal — it is a live, high-privilege bearer "
              "secret. `mcp-add` uses it internally; you rarely need it by hand. Re-run with --reveal "
              "only if you truly need it and understand it will be written to stdout.", file=sys.stderr)
        return 2
    print("WARNING: printing a live bearer token to stdout — do not share it or let it land in logs.",
          file=sys.stderr)
    sys.stdout.write(proj["token"])
    return 0


# ------------------------------------------------------- telemetry grounding

# The platform caps a facet at 100 buckets (QueryRepository.MAX_FACET_TOP_N). A project with more
# than that many call sites in one env would silently lose the tail, so we say so rather than lie.
FACET_TOP_N = 100

EXIT_NO_TELEMETRY = 3
EXIT_UNKNOWN_ENV = 4


def _api_base(proj: dict[str, Any], base_url_arg: str | None) -> str:
    return proj.get("base_url") or publish.base_url(base_url_arg)


def _project_api(proj: dict[str, Any], base_url_arg: str | None) -> str:
    """`{base}/api/orgs/{org}/projects/{project}` — the RBAC-scoped read surface."""
    url = _api_base(proj, base_url_arg)
    return f"{url}/api/orgs/{proj['org_slug']}/projects/{proj['project_slug']}"


def _unwrap(code: int, body: dict[str, Any], what: str) -> Any:
    """Pull `data` out of the ApiResponse envelope, mapping HTTP status to the exit contract.

    Only a 401 means "your link is broken" (exit 1). A 403/404/5xx is a *platform* problem — a
    revoked scope, a version-skewed endpoint, an outage — and routing those to "re-run link" sends
    the user to fix something that isn't wrong. They share exit 2 with a transport failure, which is
    what `publish._request` already raises: from the caller's side both mean "the platform did not
    answer me", and the stderr line says which."""
    if code == 401:
        print("stored token was rejected (revoked or expired) — re-run `platform.py link --force`",
              file=sys.stderr)
        raise SystemExit(1)
    if code == 403:
        print(f"the stored token is not permitted to read {what} (HTTP 403). It needs an ADMIN- or "
              "QUERY-scoped key; re-link with `platform.py link --force`, or check the key's scope in "
              "the platform UI.", file=sys.stderr)
        raise SystemExit(2)
    if code == 404:
        print(f"could not read {what} (HTTP 404). The project may have been deleted, or this platform "
              "predates the endpoint — check that the server is new enough to serve it.", file=sys.stderr)
        raise SystemExit(2)
    if code != 200:
        print(f"could not read {what} (HTTP {code})", file=sys.stderr)
        raise SystemExit(2)
    return body.get("data")


def _environments(proj: dict[str, Any], base_url_arg: str | None) -> list[dict[str, Any]]:
    code, body = publish.get_json(f"{_project_api(proj, base_url_arg)}/environments", token=proj["token"])
    return _unwrap(code, body, "environments") or []


def _resolve_env(proj: dict[str, Any], base_url_arg: str | None, slug: str) -> dict[str, Any]:
    """The environment row for `slug`, or exit 4. Never guesses a default — the caller must choose."""
    envs = _environments(proj, base_url_arg)
    for e in envs:
        if e.get("slug") == slug:
            return e
    known = ", ".join(e.get("slug", "?") for e in envs) or "(none)"
    print(f"unknown environment '{slug}' — this project has: {known}", file=sys.stderr)
    raise SystemExit(EXIT_UNKNOWN_ENV)


class Coverage(NamedTuple):
    """What one environment's telemetry says about call-site coverage."""

    tagged: list[tuple[str, int]]  # (call_site_id, span_count), busiest first
    untagged: int  # spans carrying no tessary.call_site.id
    truncated: bool  # the platform's facet cap hid some call sites


def _call_site_facets(proj: dict[str, Any], base_url_arg: str | None, env_id: str) -> Coverage:
    """Per-call-site span counts in one environment, plus the untagged span count.

    One request: facet `observations` by `call_site_id`, filtered to the environment. Untagged spans
    have a null `call_site_id`, so Postgres groups them into a **null bucket** that is ranked by count
    like any other — early on it is usually the largest. That bucket is the residue, never a call site.

    It also consumes one of the platform's `top_n` slots, which is why truncation is detected from the
    number of buckets the server *returned* rather than from how many call sites we kept: a response of
    99 call sites + 1 null bucket is already truncated, and counting only the call sites would call it
    complete. Truncation must be loud — `coverage` is the universe of what may be graded, so a call site
    silently missing from it is a call site silently left ungraded.
    """
    url = f"{_api_base(proj, base_url_arg)}/v1/query/facets"
    payload = {
        "dataset": "observations",
        "field": "call_site_id",
        "filters": {"environment_id": env_id},
        "top_n": FACET_TOP_N,
    }
    code, body = publish.post_json(url, payload, token=proj["token"])
    data = _unwrap(code, body, "call-site coverage") or {}
    buckets = data.get("facets") or []
    tagged: list[tuple[str, int]] = []
    untagged = 0
    for bucket in buckets:
        value, count = bucket.get("value"), int(bucket.get("count") or 0)
        if value is None or value == "":
            untagged += count
        else:
            tagged.append((value, count))
    tagged.sort(key=lambda kv: (-kv[1], kv[0]))
    return Coverage(tagged, untagged, len(buckets) >= FACET_TOP_N)


def cmd_envs(args: argparse.Namespace) -> int:
    """One line per environment so the skill can prompt with real numbers instead of a guess."""
    proj = _require_link(args.repo)
    envs = _environments(proj, args.base_url)
    print(f"ENVIRONMENTS\t{proj['org_slug']}/{proj['project_slug']}\t{_api_base(proj, args.base_url)}")
    for e in envs:
        cov = _call_site_facets(proj, args.base_url, e["id"])
        spans = sum(c for _, c in cov.tagged)
        sites = f"{len(cov.tagged)}+" if cov.truncated else str(len(cov.tagged))
        print(f"env\t{e['slug']}\t{spans}\t{sites}\t{str(bool(e.get('is_default'))).lower()}")
    print("\n(spans = observations carrying a tessary.call_site.id tag. A span with no tag is invisible "
          "to grader generation. The default env is where untagged-environment traffic lands.)",
          file=sys.stderr)
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    """The gate synthesize-graders calls before it authors anything."""
    proj = _require_link(args.repo)
    env = _resolve_env(proj, args.base_url, args.env)
    cov = _call_site_facets(proj, args.base_url, env["id"])
    spans = sum(c for _, c in cov.tagged)
    if len(cov.tagged) < args.min:
        print(f"PREFLIGHT\t{args.env}\tcall_sites={len(cov.tagged)}\tspans={spans}"
              f"\tuntagged={cov.untagged}\tempty")
        print(f"\n'{args.env}' has no tagged telemetry (min={args.min}). Grader generation would be "
              "ungrounded, so it stops here.\n"
              "  - No call sites instrumented yet? Run /evals:instrument, then exercise the app.\n"
              f"  - Instrumented but {cov.untagged} untagged spans arriving? The tag is "
              "`tessary.call_site.id`; check it reaches the exporter.\n"
              "  - Traffic in a different environment? Re-run with --env <slug> (see `platform.py envs`).",
              file=sys.stderr)
        return EXIT_NO_TELEMETRY
    print(f"PREFLIGHT\t{args.env}\tcall_sites={len(cov.tagged)}\tspans={spans}"
          f"\tuntagged={cov.untagged}\tok")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """The set synthesize-graders intersects against static discovery."""
    proj = _require_link(args.repo)
    env = _resolve_env(proj, args.base_url, args.env)
    cov = _call_site_facets(proj, args.base_url, env["id"])
    for call_site, count in cov.tagged:
        print(f"call_site\t{call_site}\t{count}")
    print(f"untagged\t{cov.untagged}")
    if cov.truncated:
        # On STDOUT: the caller parses stdout, and a truncation notice that only reaches stderr is a
        # notice the runbook can act as though it never saw. Coverage is the universe of what gets
        # graded, so an incomplete list must be self-describing.
        print("truncated\ttrue")
        print(f"\nNOTE: the platform returned its maximum of {FACET_TOP_N} facet buckets, so this list "
              "is incomplete — call sites below the top ones by span count are NOT shown, and would be "
              "silently left ungraded. Narrow the environment, or raise the platform's facet cap.",
              file=sys.stderr)
    return 0 if cov.tagged else EXIT_NO_TELEMETRY


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _cache_path(repo: str, env: str, call_site: str) -> Path:
    safe = _SAFE_NAME.sub("_", call_site).strip("_") or "unnamed"
    return _evals_dir(repo) / ".cache" / "traces" / _SAFE_NAME.sub("_", env) / f"{safe}.jsonl"


def cmd_fetch_traces(args: argparse.Namespace) -> int:
    """Full trace detail for one call site, written verbatim, one JSON object per line.

    Bounded by the COUNT of traces (`--limit`) and never by clipping content: a judge or grader author
    that reads a truncated span is being lied to about what production did.
    """
    if args.limit < 1:
        print("--limit must be at least 1 (it bounds the number of traces to fetch)", file=sys.stderr)
        raise SystemExit(2)
    proj = _require_link(args.repo)
    env = _resolve_env(proj, args.base_url, args.env)
    api = _project_api(proj, args.base_url)
    token = proj["token"]

    # Page the trace list (server-side filtered to this env + call site) until we have `--limit` ids.
    # Dedupe across pages and refuse to reuse a cursor: a server that repeats a cursor, or returns rows
    # without advancing, would otherwise spin here or write the same trace twice.
    ids: list[str] = []
    seen: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    while len(ids) < args.limit:
        params = {"environment": args.env, "callSite": args.call_site, "limit": min(args.limit - len(ids), 100)}
        if cursor:
            params["cursor"] = cursor
        code, body = publish.get_json(f"{api}/traces?{urllib.parse.urlencode(params)}", token=token)
        page = _unwrap(code, body, "traces") or {}
        rows = page.get("traces") or []
        for row in rows:
            trace_id = row.get("id")
            if trace_id and trace_id not in seen:
                seen.add(trace_id)
                ids.append(trace_id)
        cursor = page.get("next_cursor")
        if not cursor or not rows or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    ids = ids[: args.limit]

    if not ids:
        print(f"no traces for call site '{args.call_site}' in env '{args.env}'", file=sys.stderr)
        return EXIT_NO_TELEMETRY

    out = Path(args.out) if args.out else _cache_path(args.repo, args.env, args.call_site)
    out.parent.mkdir(parents=True, exist_ok=True)
    spans = 0
    with out.open("w") as fh:
        for trace_id in ids:
            code, body = publish.get_json(f"{api}/traces/{urllib.parse.quote(trace_id)}", token=token)
            detail = _unwrap(code, body, f"trace {trace_id}")
            if not detail:
                continue
            spans += len(detail.get("observations") or [])
            fh.write(json.dumps(detail, separators=(",", ":")) + "\n")

    print(f"FETCHED\t{args.env}\t{args.call_site}\ttraces={len(ids)}\tobservations={spans}\tout={out}")
    return 0


# ----------------------------------------------------------------------- cli

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="platform.py",
        description="Connect a repo to evals.tessary.ai and wire its MCP server into Claude Code.")
    p.add_argument("--base-url", default=None,
                   help="platform origin (default: env EVALS_PLATFORM_URL or evals.tessary.ai)")
    p.add_argument("--repo", default=".", help="repo root to link (default: cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("link", help="device-code link to a project")
    pl.add_argument("--label", default=None)
    pl.add_argument("--force", action="store_true", help="re-link even if a valid token exists")
    pl.set_defaults(func=cmd_link)

    ps = sub.add_parser("status", help="print the linked project's summary + counts")
    ps.set_defaults(func=cmd_status)

    pm = sub.add_parser("mcp-add", help="register the platform MCP server into Claude Code")
    pm.add_argument("--run", action="store_true", help="execute the command instead of printing it")
    pm.set_defaults(func=cmd_mcp_add)

    pun = sub.add_parser("unlink", help="remove the MCP registration + stored credential for a repo")
    pun.set_defaults(func=cmd_unlink)

    pt = sub.add_parser("token", help="print the stored bearer token (requires --reveal; it is a secret)")
    pt.add_argument("--reveal", action="store_true",
                    help="actually print the live token to stdout (it is a high-privilege secret)")
    pt.set_defaults(func=cmd_token)

    pe = sub.add_parser("envs", help="list environments with their tagged-span + call-site counts")
    pe.set_defaults(func=cmd_envs)

    pp = sub.add_parser("preflight", help="does <env> carry usable tagged telemetry? (exit 3 if not)")
    pp.add_argument("--env", required=True, help="environment slug (there is no default — choose one)")
    pp.add_argument("--min", type=int, default=1, help="minimum tagged call sites required (default: 1)")
    pp.set_defaults(func=cmd_preflight)

    pc = sub.add_parser("coverage", help="per-call-site span counts in <env>, plus the untagged residue")
    pc.add_argument("--env", required=True, help="environment slug")
    pc.set_defaults(func=cmd_coverage)

    pf = sub.add_parser("fetch-traces", help="write one call site's full traces to a local cache file")
    pf.add_argument("--env", required=True, help="environment slug")
    pf.add_argument("--call-site", required=True, help="call-site id (the tessary.call_site.id tag value)")
    pf.add_argument("--limit", type=int, default=25,
                    help="max TRACES to fetch (default: 25). Content is never truncated — only the count "
                         "of traces is bounded.")
    pf.add_argument("--out", default=None, help="output path (default: .tessary/.cache/traces/<env>/<id>.jsonl)")
    pf.set_defaults(func=cmd_fetch_traces)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
