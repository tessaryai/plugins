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
  unlink    Tear down the link for a repo: remove the local MCP registration AND
            delete the repo's stored credential (the one place both are undone).
  token     Print the stored bearer token — GATED behind --reveal (it is a live,
            high-privilege secret); used internally by mcp-add, rarely by hand.

Credentials are keyed by repo root exactly as `publish.py` keys them (the parent
of `<repo>/.tessary`), so a repo linked here is also "linked" for a later
`publish.py upload`, and vice-versa — one link, one token, both paths.
"""
from __future__ import annotations

import argparse
import json
import os
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
              "(run /evals:synthesize-graders to bootstrap one).")
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
