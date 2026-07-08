#!/usr/bin/env python3
"""platform.py — the evals *assistant's* thin client to evals.tessary.ai.

Distinct from `publish.py` (which pushes a full synthesized `.tessary/` bundle).
This is the **integration front door** driven by the `connect` skill: link a repo
to a project, report project status, and wire the platform's authenticated MCP
server into the user's Claude Code so the coding agent gets native tools
(`list_call_sites`, `list_graders`, `query_*`, `run_triage`, `propose_grader_edit`,
…) instead of shelling out to Python for every read.

It deliberately reuses `publish.py`'s HTTP / TLS / credentials / device-link
plumbing (same directory) rather than duplicating ~150 lines — and it never
touches the synthesis pipeline, so the demoted `synthesize-graders` path is
unaffected.

Subcommands (all stdlib-only):

  link      Device-authorization handshake → stores a project-scoped ADMIN token
            under ~/.config/tessary-evals/credentials.json (keyed by repo path).
            A no-op if the repo is already linked with a still-valid token.
  status    Print the linked project's org/project slugs + call-site / grader /
            failure-mode counts (a quick "am I connected and what's here?").
  mcp-add   Print (default) or --run the `claude mcp add` command that registers
            the platform MCP server for THIS repo at `local` scope — the token is
            stored privately in ~/.claude.json, never in a committed file.
  token     Print the stored bearer token for this repo (for scripting/debug).

Credentials are keyed by repo root exactly as `publish.py` keys them (the parent
of `<repo>/.tessary`), so a repo linked here is also "linked" for a later
`publish.py upload`, and vice-versa — one link, one token, both paths.
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

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
    pipeline = (penv.get("data") or {}).get("pipeline") or {} if pcode == 200 else {}

    def _count(key: str) -> int | str:
        v = pipeline.get(key)
        return len(v) if isinstance(v, list) else ("?" if pcode != 200 else 0)

    print(f"Linked to {org}/{project}  ({url})")
    proj_data = summary.get("data") or {}
    name = proj_data.get("name") or project
    print(f"  project:        {name}")
    print(f"  call sites:     {_count('callSites')}")
    print(f"  graders:        {_count('graders')}")
    print(f"  failure modes:  {_count('failureModes')}")
    print(f"  quality dims:   {_count('qualityDimensions')}")
    if pcode != 200:
        print(f"  (pipeline not yet available — HTTP {pcode}; the project may have no synthesized "
              "pipeline yet)", file=sys.stderr)
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


def cmd_mcp_add(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    url = proj.get("base_url") or publish.base_url(args.base_url)
    token = proj["token"]
    cmd = _mcp_add_command(url, token)

    if not args.run:
        # Print a copy-pasteable command WITHOUT echoing the secret to normal
        # stdout logs: mask all but the last 4 chars of the token.
        masked = token[:4] + "…" + token[-4:] if len(token) > 8 else "…"
        shown = [c.replace(token, masked) if token in c else c for c in cmd]
        print(" ".join(shlex.quote(c) for c in shown))
        print("\n(run with --run to execute; the real token is read from your stored "
              "credentials, not from this printed line)", file=sys.stderr)
        return 0

    # Idempotency: drop any prior registration so re-connect refreshes the token.
    subprocess.run(["claude", "mcp", "remove", "--scope", "local", MCP_SERVER_NAME],
                   capture_output=True, text=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr or res.stdout)
        print(f"\n`claude mcp add` failed (exit {res.returncode}). Is the Claude Code CLI on PATH?",
              file=sys.stderr)
        return res.returncode
    print(f"Registered MCP server '{MCP_SERVER_NAME}' → {url}/mcp (local scope).")
    print("Reconnect / restart this session so the platform tools load, then ask e.g. "
          "\"list my call sites\" or \"what's failing this week?\".")
    return 0


# -------------------------------------------------------------------- token

def cmd_token(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    sys.stdout.write(proj["token"])
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

    pt = sub.add_parser("token", help="print the stored bearer token for this repo")
    pt.set_defaults(func=cmd_token)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
