#!/usr/bin/env python3
"""platform.py — the tessary plugin's local helper.

There is no OAuth/device-link handshake for a self-hosted, open-edition Tessary
instance (verified against docs/reference/mcp-server.mdx and
docs/reference/api-keys.mdx in tessaryai/tessary): the credential is an
admin-scoped project API key (`tsy_a_...`) a human mints once, by hand, under
Settings -> MCP tokens in their own instance, and is shown only once in
plaintext. So this script never fetches or constructs a token itself — a human
runs `link` interactively (or exports TESSARY_ORIGIN / TESSARY_TOKEN for a
headless run of THIS script) and types the value directly into a hidden
prompt. The coding agent driving `/connect` never sees, prints, or
constructs a shell command carrying the raw token.

Subcommands (all stdlib-only, single-file):

  link      Prompt for the instance origin and a token (hidden input), or read
            TESSARY_ORIGIN / TESSARY_TOKEN from the environment. Stores both
            under ~/.config/tessary/credentials.json (keyed by repo path).
            A no-op if the repo already has a stored credential for this origin.
  status    Call the MCP endpoint's `initialize` with the stored token and
            report the server name/version and tool count, so the user knows
            the credential actually works before registering it in Claude Code.
  mcp-add   Print (default) or --run the `claude mcp add` command that
            registers the MCP server for THIS repo at `local` scope — the
            token is stored privately in ~/.claude.json, never in a committed
            file.
  unlink    Tear down the link for a repo: remove the local MCP registration
            AND delete the repo's stored credential.
  token     Print the stored bearer token — GATED behind --reveal (it is a
            live, high-privilege secret); used internally by mcp-add, rarely
            by hand.

Exit codes (the skill branches on these, so they are contract):

  0  ok
  1  not linked (or the stored token was rejected) -> run `link` / /connect
  2  the instance did not answer: network/TLS failure, or it answered with
     401/403/404/5xx. Also argparse's own usage-error code.
  127  the `claude` CLI isn't on PATH (mcp-add --run only)

Credentials are keyed by repo root — one link, one token, every subcommand.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ORIGIN = "http://localhost"
MCP_SERVER_NAME = "tessary"


def _client_version() -> str:
    """Plugin version, read from .claude-plugin/plugin.json next to this script."""
    try:
        manifest = Path(__file__).resolve().parent / ".claude-plugin" / "plugin.json"
        return str(json.loads(manifest.read_text()).get("version", "0"))
    except Exception:
        return "0"


USER_AGENT = f"tessary-plugin/{_client_version()} (+https://github.com/tessaryai/tessary)"


# --------------------------------------------------------------------- config

def config_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(root) / "tessary" / "credentials.json"


def repo_key(repo: str) -> str:
    return str(Path(repo).resolve())


def load_config() -> dict[str, Any]:
    p = config_path()
    if not p.exists():
        return {"projects": {}}
    try:
        data = json.loads(p.read_text())
        data.setdefault("projects", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"projects": {}}


def _write_config_private(p: Path, cfg: dict[str, Any]) -> None:
    """Write the credentials file with 0600 perms from the moment it's created —
    the mode is applied by the open() syscall itself, not a chmod afterward, so
    there's no window where a freshly-created file sits at the umask default
    (typically 0644, world-readable) before this function narrows it."""
    fd = os.open(p, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(cfg, indent=2))
    finally:
        os.chmod(p, 0o600)


def save_credentials(repo: str, origin: str, token: str) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg["projects"][repo_key(repo)] = {
        "origin": origin.rstrip("/"),
        "token": token,
        "linked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_config_private(p, cfg)


def linked_project(repo: str) -> dict[str, Any] | None:
    return load_config().get("projects", {}).get(repo_key(repo))


def _require_link(repo: str) -> dict[str, Any]:
    proj = linked_project(repo)
    if not proj:
        print("this repo isn't linked to a Tessary instance yet — run `platform.py link` "
              "(or /connect) first.", file=sys.stderr)
        raise SystemExit(1)
    return proj


# ----------------------------------------------------------------------- http

_SSL_CONTEXT: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """TLS context that actually finds a CA bundle, cached for the process.
    See the evals plugin's platform.py for the full rationale (same fallback
    chain: explicit SSL_CERT_FILE/REQUESTS_CA_BUNDLE, the stdlib default
    store, then certifi) — copied here rather than shared, since a self-hosted
    origin is at least as likely to be plain `http://localhost` with no TLS
    at all."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    ctx = ssl.create_default_context()
    explicit = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if explicit and os.path.isfile(explicit):
        try:
            ctx.load_verify_locations(explicit)
            _SSL_CONTEXT = ctx
            return ctx
        except ssl.SSLError:
            pass
    try:
        has_cas = ctx.cert_store_stats().get("x509_ca", 0) > 0
    except Exception:
        has_cas = False
    if not has_cas:
        try:
            import certifi  # type: ignore
            ctx.load_verify_locations(certifi.where())
        except Exception:
            pass
    _SSL_CONTEXT = ctx
    return ctx


def _mcp_initialize(origin: str, token: str) -> tuple[int, dict[str, Any] | None]:
    """POST a bare JSON-RPC `initialize` to <origin>/mcp with the stored token.
    Returns (http_status, parsed_body_or_None). Used only by `status` to prove
    the credential actually works — never used to fetch a token."""
    url = origin.rstrip("/") + "/mcp"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "tessary-plugin", "version": _client_version()},
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        ctx = ssl_context() if url.startswith("https://") else None
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return resp.getcode(), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None
    except urllib.error.URLError as e:
        print(f"network error talking to {url}: {e.reason}", file=sys.stderr)
        return 0, None


# ------------------------------------------------------------------------ link

def cmd_link(args: argparse.Namespace) -> int:
    repo = args.repo
    env_origin = os.environ.get("TESSARY_ORIGIN")
    env_token = os.environ.get("TESSARY_TOKEN")

    if env_origin and env_token:
        # Headless path: a CI run of THIS script, not a live indirection the agent
        # constructs. The registration this produces is baked into ~/.claude.json
        # at add-time either way.
        origin, token = env_origin, env_token
    else:
        existing = linked_project(repo)
        default_origin = (existing or {}).get("origin") or DEFAULT_ORIGIN
        print("Mint an admin-scoped MCP token in your Tessary instance under "
              "Settings -> MCP tokens, then paste it below. It is shown once in "
              "plaintext there and is never printed by this script.")
        origin = input(f"Tessary origin [{default_origin}]: ").strip() or default_origin
        token = getpass.getpass("MCP token (tsy_a_...): ").strip()

    if not token:
        print("no token given — aborting.", file=sys.stderr)
        return 1

    save_credentials(repo, origin, token)
    print(f"Stored credentials for {origin} (repo: {repo_key(repo)}).")
    print("Run `platform.py status` to verify the token works, then "
          "`platform.py mcp-add --run` to register it in Claude Code.")
    return 0


# ---------------------------------------------------------------------- status

def cmd_status(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    origin, token = proj["origin"], proj["token"]
    status, body = _mcp_initialize(origin, token)

    if status == 0:
        return 2
    if status == 401:
        print(f"{origin}/mcp rejected the stored token (401) — mint a fresh admin-scoped "
              "token and re-run `platform.py link`.", file=sys.stderr)
        return 1
    if status == 404:
        print(f"{origin}/mcp answered 404 — this instance may have authentication disabled "
              "(TESSARY_AUTH_DISABLED) or the origin is wrong.", file=sys.stderr)
        return 2
    if status != 200 or body is None:
        print(f"{origin}/mcp answered HTTP {status} — expected 200.", file=sys.stderr)
        return 2

    result = body.get("result") or {}
    server = result.get("serverInfo") or {}
    print(f"Linked to {origin}. Server: {server.get('name', '?')} {server.get('version', '?')}.")
    print("This surface is read-only: no tool writes a row, spends a token, or starts an agent run.")
    return 0


# ------------------------------------------------------------------- mcp-add

def _mcp_add_command(origin: str, token: str) -> list[str]:
    return [
        "claude", "mcp", "add",
        "--transport", "http",
        "--scope", "local",
        MCP_SERVER_NAME,
        f"{origin.rstrip('/')}/mcp",
        "--header", f"Authorization: Bearer {token}",
    ]


def _claude_available() -> bool:
    try:
        return subprocess.run(["claude", "--version"], capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def cmd_mcp_add(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    origin, token = proj["origin"], proj["token"]
    cmd = _mcp_add_command(origin, token)

    if not args.run:
        # Informational only: the token is MASKED and this line is not runnable.
        # Never hand-assemble this with the real token — it leaks into shell history.
        masked = token[:4] + "…" + token[-4:] if len(token) > 8 else "…"
        shown = [c.replace(token, masked) if token in c else c for c in cmd]
        print(" ".join(shlex.quote(c) for c in shown))
        print("\n(preview only — the token is masked. Run `platform.py mcp-add --run`, which reads "
              "the real token internally. Never paste a token by hand.)", file=sys.stderr)
        return 0

    if not _claude_available():
        print("the `claude` CLI isn't on PATH, so I can't register the MCP server — your existing "
              "registration (if any) is untouched. Fix PATH and re-run `/connect`.",
              file=sys.stderr)
        return 127

    subprocess.run(["claude", "mcp", "remove", "--scope", "local", MCP_SERVER_NAME],
                   capture_output=True, text=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr or res.stdout)
        print(f"\n`claude mcp add` failed (exit {res.returncode}). Any previous '{MCP_SERVER_NAME}' "
              "registration was removed during this refresh — re-run `/connect` to restore it.",
              file=sys.stderr)
        return res.returncode
    print(f"Registered MCP server '{MCP_SERVER_NAME}' -> {origin.rstrip('/')}/mcp (local scope).")
    print("Reconnect / restart this session so the tools load, then ask e.g. "
          "\"what cases are open?\" or \"show me the traces for <call site>\".")
    return 0


# -------------------------------------------------------------------- unlink

def _forget_credentials(repo: str) -> bool:
    cfg = load_config()
    key = repo_key(repo)
    if key not in cfg.get("projects", {}):
        return False
    del cfg["projects"][key]
    _write_config_private(config_path(), cfg)
    return True


def cmd_unlink(args: argparse.Namespace) -> int:
    repo = args.repo
    proj = linked_project(repo)

    mcp_removed = False
    if _claude_available():
        r = subprocess.run(["claude", "mcp", "remove", "--scope", "local", MCP_SERVER_NAME],
                           capture_output=True, text=True)
        mcp_removed = r.returncode == 0

    cred_removed = _forget_credentials(repo)

    if not proj and not cred_removed and not mcp_removed:
        print("nothing to unlink — this repo isn't linked.", file=sys.stderr)
        return 0
    print(f"Unlinked this repo. Removed: "
          f"{'MCP registration' if mcp_removed else 'no MCP registration'}, "
          f"{'stored credential' if cred_removed else 'no stored credential'}.")
    print("The token still exists in your Tessary instance — if it may be exposed, revoke it "
          "under Settings -> MCP tokens.", file=sys.stderr)
    return 0


# -------------------------------------------------------------------- token

def cmd_token(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    if not args.reveal:
        print("refusing to print the token without --reveal — it is a live, high-privilege bearer "
              "secret. `mcp-add` uses it internally; you rarely need it by hand.", file=sys.stderr)
        return 2
    print("WARNING: printing a live bearer token to stdout — do not share it or let it land in logs.",
          file=sys.stderr)
    sys.stdout.write(proj["token"])
    return 0


# --------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="tessary plugin local helper")
    p.add_argument("--repo", default=".", help="repo root to key credentials by (default: cwd)")
    sub = p.add_subparsers(required=True)

    sl = sub.add_parser("link", help="store the origin + token for this repo")
    sl.set_defaults(func=cmd_link)

    ss = sub.add_parser("status", help="verify the stored token against the MCP endpoint")
    ss.set_defaults(func=cmd_status)

    sm = sub.add_parser("mcp-add", help="print (or --run) the claude mcp add command")
    sm.add_argument("--run", action="store_true", help="actually register the MCP server")
    sm.set_defaults(func=cmd_mcp_add)

    su = sub.add_parser("unlink", help="remove the MCP registration and stored credential")
    su.set_defaults(func=cmd_unlink)

    st = sub.add_parser("token", help="print the stored token (gated behind --reveal)")
    st.add_argument("--reveal", action="store_true")
    st.set_defaults(func=cmd_token)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
