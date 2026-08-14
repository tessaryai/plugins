#!/usr/bin/env python3
"""platform.py — the evals plugin's client to evals.tessary.ai.

The **integration front door** driven by the `connect` skill: link a repo to a
project, report project status, and wire the platform's authenticated MCP server
into the user's Claude Code so the coding agent gets native tools
(`list_call_sites`, `list_graders`, `query_*`, `run_triage`, `propose_grader_edit`,
…) instead of shelling out to Python for every read.

Everything downstream of the link lives on the platform: the observer reads the
repo on the org's schedule, authors and refreshes the `.tessary/` bundle through
draft PRs, and imports it on merge. This client carries no synthesis, no upload,
and no bundle tooling — its job ends when the repo is linked, instrumented
(`/evals:instrument`) and emitting OTLP.

Subcommands (all stdlib-only, single-file):

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
  coverage      Per-call-site span counts in <env>, plus the untagged residue.

Exit codes (the skills branch on these, so they are contract):

  0  ok
  1  not linked (or the stored token was rejected) → run `link` / /evals:connect
  2  the platform did not answer: network/TLS failure, or it answered with
     403/404/5xx. Also argparse's own usage-error code — both mean "this
     invocation produced no data", so callers treat them alike.
  3  linked, but <env> has no tagged telemetry → run /evals:instrument, then
     exercise the app. Deliberately distinct from 1: "nothing to ground on" is
     not "not connected".
  4  unknown environment slug

Credentials are keyed by repo root (the parent of `<repo>/.tessary`) — one link,
one token, every subcommand.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, NamedTuple

DEFAULT_BASE_URL = "https://evals.tessary.ai"


def _client_version() -> str:
    """Plugin version, read from .claude-plugin/plugin.json next to this script.
    Surfaced in the User-Agent so the platform — and the zone's Cloudflare WAF —
    can recognise the official CLI instead of a bare `Python-urllib/X.Y` agent,
    which Cloudflare's bot rules block."""
    try:
        manifest = Path(__file__).resolve().parent / ".claude-plugin" / "plugin.json"
        return str(json.loads(manifest.read_text()).get("version", "0"))
    except Exception:
        return "0"


# Default headers on every request. USER_AGENT replaces urllib's `Python-urllib/X.Y`
# (the string Cloudflare blocks); X-Tessary-Client is the stable marker the zone's
# WAF skip rule matches on to bypass Super Bot Fight Mode for this client. Neither
# is a secret — they *identify* the client, they do not *authenticate* it. The
# project-scoped bearer token remains the only authorization boundary, so a spoofed
# header buys an attacker nothing beyond skipping bot heuristics on these paths.
USER_AGENT = f"tessary-evals/{_client_version()} (+https://evals.tessary.ai)"
CLIENT_HEADER_NAME = "X-Tessary-Client"
CLIENT_HEADER_VALUE = "evals-cli"


# --------------------------------------------------------------------- config

def base_url(arg: str | None) -> str:
    url = arg or os.environ.get("EVALS_PLATFORM_URL") or DEFAULT_BASE_URL
    return url.rstrip("/")


def config_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(root) / "tessary-evals" / "credentials.json"


def repo_key(evals_dir: Path) -> str:
    # Key by the repo (parent of .tessary/) so one machine can link many repos.
    return str(evals_dir.resolve().parent)


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


def save_credentials(evals_dir: Path, url: str, token: str, org_slug: str, project_slug: str) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg["base_url"] = url
    cfg["projects"][repo_key(evals_dir)] = {
        "token": token,
        "org_slug": org_slug,
        "project_slug": project_slug,
        "base_url": url,
        "linked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    p.write_text(json.dumps(cfg, indent=2))
    os.chmod(p, 0o600)


def linked_project(evals_dir: Path) -> dict[str, Any] | None:
    return load_config().get("projects", {}).get(repo_key(evals_dir))


def _evals_dir(repo: str) -> Path:
    """The notional `.tessary` dir for a repo, whether or not it exists yet —
    credentials are keyed by its parent (the repo root)."""
    return Path(repo).resolve() / ".tessary"


# ----------------------------------------------------------------------- http

_SSL_CONTEXT: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """TLS context that actually finds a CA bundle, cached for the process.

    urllib's default context trusts only OpenSSL's compiled-in CA paths. On the
    python.org macOS build those paths are empty until you run
    'Install Certificates.command', so every HTTPS request to evals.tessary.ai
    dies with CERTIFICATE_VERIFY_FAILED / 'unable to get local issuer
    certificate' — exactly the consuming-machine failure this guards against.
    We layer fallbacks, most-specific first:

      1. An explicit bundle from SSL_CERT_FILE / REQUESTS_CA_BUNDLE. Covers a
         corporate TLS-intercepting proxy whose injected root the system trusts
         but Python doesn't — the only fix there is to point at its bundle.
      2. The stdlib default store if it already trusts CAs (Linux, Homebrew
         Python), detected via cert_store_stats — leave it untouched.
      3. The certifi bundle if importable. pip ships certifi, so it is present
         in most environments even when ssl was never wired up to it; this is
         what rescues the bare python.org macOS build.

    Verification is never disabled — an unverifiable host fails loudly rather
    than silently sending the link token over plaintext-trust.
    """
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
            pass  # bad/empty bundle — fall through to the other sources
    try:
        has_cas = ctx.cert_store_stats().get("x509_ca", 0) > 0
    except Exception:
        has_cas = False
    if not has_cas:
        try:
            import certifi  # type: ignore
            ctx.load_verify_locations(certifi.where())
        except Exception:
            pass  # nothing more we can add; the request will surface the error
    _SSL_CONTEXT = ctx
    return ctx


def _tls_help(url: str) -> str:
    return (
        f"TLS trust error talking to {url}: the certificate could not be verified "
        "because this machine's Python has no CA bundle it can use.\n"
        "  • macOS python.org build: run the bundled "
        "'/Applications/Python 3.x/Install Certificates.command', or "
        "`pip install --upgrade certifi`.\n"
        "  • Behind a TLS-intercepting corporate proxy: point Python at its root "
        "bundle, e.g. `export SSL_CERT_FILE=/path/to/corp-ca.pem` (or "
        "REQUESTS_CA_BUNDLE), then re-run.\n"
        "Verification was not disabled — nothing was sent over an untrusted connection."
    )


def _request(method: str, url: str, *, body: bytes | None = None,
             headers: dict[str, str] | None = None, fatal: bool = True) -> tuple[int, bytes]:
    merged = {"User-Agent": USER_AGENT, CLIENT_HEADER_NAME: CLIENT_HEADER_VALUE}
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, data=body, method=method, headers=merged)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        # A one-shot call (status/link-start) treats a transport error as fatal. A long-running
        # caller that polls for minutes (the device-link loop) passes fatal=False so a single
        # transient blip doesn't kill the whole flow — it gets a (0, b"") sentinel and retries on
        # the next tick.
        if not fatal:
            return 0, b""
        reason = e.reason
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
            print(_tls_help(url), file=sys.stderr)
        else:
            print(f"network error talking to {url}: {reason}", file=sys.stderr)
        raise SystemExit(2)


def post_json(url: str, payload: dict[str, Any], token: str | None = None,
              *, fatal: bool = True) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    code, raw = _request("POST", url, body=json.dumps(payload).encode(), headers=headers, fatal=fatal)
    try:
        return code, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return code, {}


def get_json(url: str, token: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    code, raw = _request("GET", url, headers=headers)
    try:
        return code, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return code, {}


# --------------------------------------------------------------------- link

def is_headless() -> bool:
    if os.environ.get("SSH_CONNECTION") or os.environ.get("CI"):
        return True
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False


def cmd_link(args: argparse.Namespace) -> int:
    """Device-authorization handshake. Prints a short code + URL, opens the
    browser, polls until the user confirms in a signed-in browser, then stores a
    project-scoped token under ~/.config/tessary-evals/."""
    url = base_url(args.base_url)
    evals_dir = _evals_dir(args.repo)

    if not args.force:
        existing = linked_project(evals_dir)
        if existing and existing.get("token"):
            # Confirm the stored token still works before reusing it.
            code, _ = get_json(
                f"{url}/api/orgs/{existing['org_slug']}/projects/{existing['project_slug']}/pipeline",
                token=existing["token"])
            if code != 401:
                print(f"Already linked to {existing['org_slug']}/{existing['project_slug']}.")
                return 0

    label = args.label or f"Claude Code on {socket.gethostname()}"
    code, data = post_json(f"{url}/auth/link/start", {"client_label": label})
    if code != 200 or "data" not in data:
        print(f"could not start link (HTTP {code})", file=sys.stderr)
        return 1
    d = data["data"]
    device_code = d["device_code"]
    verify = d["verification_uri_complete"]
    interval = max(1, int(d.get("interval", 3)))

    print(f"\nConnect this session to {urllib.parse.urlsplit(url).netloc or url}:")
    print(f"  → {verify}")
    print(f"  code: {d['user_code']}")
    if not is_headless():
        try:
            webbrowser.open(verify)
        except Exception:
            pass
    print("Waiting for you to confirm in the browser…", flush=True)

    deadline = time.time() + int(d.get("expires_in", 600))
    while time.time() < deadline:
        time.sleep(interval)
        pc, pdata = post_json(f"{url}/auth/link/poll", {"device_code": device_code}, fatal=False)
        if pc == 0:
            continue  # transient network blip this tick — keep polling until the deadline
        status = (pdata.get("data") or {}).get("status")
        if status == "ready":
            pd = pdata["data"]
            save_credentials(evals_dir, url, pd["token"], pd["org_slug"], pd["project_slug"])
            print(f"\nLinked to {pd['org_slug']}/{pd['project_slug']}.")
            return 0
        if status in ("denied",):
            print("\nLink was declined in the browser.", file=sys.stderr)
            return 1
        if pc == 410 or status == "expired":
            print("\nLink expired before it was confirmed. Re-run to try again.", file=sys.stderr)
            return 1
        # authorization_pending / slow_down → keep polling
        if status == "slow_down":
            interval += 1
    print("\nTimed out waiting for confirmation.", file=sys.stderr)
    return 1


# ------------------------------------------------------------------- status

def _require_link(repo: str) -> dict[str, Any]:
    proj = linked_project(_evals_dir(repo))
    if not proj or not proj.get("token"):
        print("not linked yet — run `platform.py link` (or /evals:connect) first", file=sys.stderr)
        raise SystemExit(1)
    return proj


def cmd_status(args: argparse.Namespace) -> int:
    proj = _require_link(args.repo)
    url = proj.get("base_url") or base_url(args.base_url)
    org, project, token = proj["org_slug"], proj["project_slug"], proj["token"]
    api = f"{url}/api/orgs/{org}/projects/{project}"

    # Project summary — also the token liveness check.
    code, summary = get_json(api, token=token)
    if code == 401:
        print("stored token was rejected (revoked or expired) — re-run `platform.py link --force`",
              file=sys.stderr)
        return 1
    if code != 200:
        print(f"could not read project (HTTP {code})", file=sys.stderr)
        return 1

    # Pipeline envelope carries the call-site / grader / failure-mode inventory.
    pcode, penv = get_json(f"{api}/pipeline", token=token)
    if pcode == 401:
        # A 401 here is a token problem, not an empty project — don't mislead toward "empty".
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
        print("  → this project has no eval pipeline yet. Tag your call sites with /evals:instrument "
              "and exercise the app; once tagged traffic is flowing and the repo is connected on the "
              "platform (Settings → Git integration), the platform's observer authors the starter bundle as a "
              "draft PR for you to review.")
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
    url = proj.get("base_url") or base_url(args.base_url)
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
    cfg = load_config()
    key = repo_key(evals_dir)
    if key not in cfg.get("projects", {}):
        return False
    del cfg["projects"][key]
    p = config_path()
    p.write_text(json.dumps(cfg, indent=2))
    os.chmod(p, 0o600)
    return True


def cmd_unlink(args: argparse.Namespace) -> int:
    """The single place both credential copies are torn down together: the local MCP registration
    (~/.claude.json) and the stored credential (credentials.json)."""
    evals_dir = _evals_dir(args.repo)
    proj = linked_project(evals_dir)

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


# ------------------------------------------------------- telemetry coverage

# The platform caps a facet at 100 buckets (QueryRepository.MAX_FACET_TOP_N). A project with more
# than that many call sites in one env would silently lose the tail, so we say so rather than lie.
FACET_TOP_N = 100

EXIT_NO_TELEMETRY = 3
EXIT_UNKNOWN_ENV = 4


def _api_base(proj: dict[str, Any], base_url_arg: str | None) -> str:
    return proj.get("base_url") or base_url(base_url_arg)


def _project_api(proj: dict[str, Any], base_url_arg: str | None) -> str:
    """`{base}/api/orgs/{org}/projects/{project}` — the RBAC-scoped read surface."""
    url = _api_base(proj, base_url_arg)
    return f"{url}/api/orgs/{proj['org_slug']}/projects/{proj['project_slug']}"


def _unwrap(code: int, body: dict[str, Any], what: str) -> Any:
    """Pull `data` out of the ApiResponse envelope, mapping HTTP status to the exit contract.

    Only a 401 means "your link is broken" (exit 1). A 403/404/5xx is a *platform* problem — a
    revoked scope, a version-skewed endpoint, an outage — and routing those to "re-run link" sends
    the user to fix something that isn't wrong. They share exit 2 with a transport failure: from
    the caller's side both mean "the platform did not answer me", and the stderr line says which."""
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
    code, body = get_json(f"{_project_api(proj, base_url_arg)}/environments", token=proj["token"])
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

    One request: facet `spans` by `call_site_id`, filtered to the environment. Untagged spans
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
        "dataset": "spans",
        "field": "call_site_id",
        "filters": {"environment_id": env_id},
        "top_n": FACET_TOP_N,
    }
    code, body = post_json(url, payload, token=proj["token"])
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
    """One line per environment so the skills can report with real numbers instead of a guess."""
    proj = _require_link(args.repo)
    envs = _environments(proj, args.base_url)
    print(f"ENVIRONMENTS\t{proj['org_slug']}/{proj['project_slug']}\t{_api_base(proj, args.base_url)}")
    for e in envs:
        cov = _call_site_facets(proj, args.base_url, e["id"])
        spans = sum(c for _, c in cov.tagged)
        sites = f"{len(cov.tagged)}+" if cov.truncated else str(len(cov.tagged))
        print(f"env\t{e['slug']}\t{spans}\t{sites}\t{str(bool(e.get('is_default'))).lower()}")
    print("\n(the spans column counts only spans carrying a tessary.call_site.id tag. An untagged span "
          "is invisible to every call-site-scoped feature. The default env is where "
          "untagged-environment traffic lands.)",
          file=sys.stderr)
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """Per-call-site span counts — how instrument verifies its tags became telemetry."""
    proj = _require_link(args.repo)
    env = _resolve_env(proj, args.base_url, args.env)
    cov = _call_site_facets(proj, args.base_url, env["id"])
    for call_site, count in cov.tagged:
        print(f"call_site\t{call_site}\t{count}")
    print(f"untagged\t{cov.untagged}")
    if cov.truncated:
        # On STDOUT: the caller parses stdout, and a truncation notice that only reaches stderr is a
        # notice the caller can act as though it never saw. Coverage is the universe of what gets
        # graded, so an incomplete list must be self-describing.
        print("truncated\ttrue")
        print(f"\nNOTE: the platform returned its maximum of {FACET_TOP_N} facet buckets, so this list "
              "is incomplete — call sites below the top ones by span count are NOT shown, and would be "
              "silently left ungraded. Narrow the environment, or raise the platform's facet cap.",
              file=sys.stderr)
    return 0 if cov.tagged else EXIT_NO_TELEMETRY


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

    pc = sub.add_parser("coverage", help="per-call-site span counts in <env>, plus the untagged residue")
    pc.add_argument("--env", required=True, help="environment slug")
    pc.set_defaults(func=cmd_coverage)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
