#!/usr/bin/env python3
"""publish.py — connect a synthesis run to evals.tessary.ai and push the bundle.

Two subcommands, both stdlib-only (urllib), no third-party deps:

  link    Device-authorization handshake. Prints a short code + URL, opens the
          browser, polls until the user confirms in a signed-in browser, then
          stores a project-scoped token under ~/.config/tessary-evals/.

  upload  Multipart-pushes the local .tessary/ bundle to the linked
          project's import endpoint, then uploads any captured datasets/*.jsonl
          to the trace-upload endpoint so the graders run on real rows.

The only network egress in the whole skill. Invoked from SKILL.md's Phase C.7
publish step (opt-in, asked once) and re-run with `upload` on later sites.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://evals.tessary.ai"


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


# ----------------------------------------------------------------------- http

def _request(method: str, url: str, *, body: bytes | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        print(f"network error talking to {url}: {e.reason}", file=sys.stderr)
        raise SystemExit(2)


def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    code, raw = _request("POST", url, body=json.dumps(payload).encode(), headers=headers)
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


def multipart_post(url: str, files: list[tuple[str, Path]], token: str) -> tuple[int, dict[str, Any]]:
    """POST files as multipart/form-data. Each tuple is (form-field-filename, path)."""
    boundary = "----evals" + uuid.uuid4().hex
    parts: list[bytes] = []
    for field_name, path in files:
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        parts.append(("--" + boundary + "\r\n").encode())
        parts.append(
            (f'Content-Disposition: form-data; name="files"; filename="{field_name}"\r\n').encode())
        parts.append((f"Content-Type: {ctype}\r\n\r\n").encode())
        parts.append(path.read_bytes())
        parts.append(b"\r\n")
    parts.append(("--" + boundary + "--\r\n").encode())
    body = b"".join(parts)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}",
    }
    code, raw = _request("POST", url, body=body, headers=headers)
    try:
        return code, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return code, {}


# ------------------------------------------------------------------ link flow

def is_headless() -> bool:
    if os.environ.get("SSH_CONNECTION") or os.environ.get("CI"):
        return True
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False


def cmd_link(args: argparse.Namespace) -> int:
    url = base_url(args.base_url)
    evals_dir = Path(args.evals_dir)

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

    print("\nConnect this session to evals.tessary.ai:")
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
        pc, pdata = post_json(f"{url}/auth/link/poll", {"device_code": device_code})
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


# ---------------------------------------------------------------- upload flow

def collect_bundle_files(evals_dir: Path) -> list[tuple[str, Path]]:
    """Every file under .tessary/, keyed by its path relative to the repo
    (so the name carries the leading .tessary/ that the backend classifier
    expects). datasets/*.jsonl and report/html are sent too but ignored by import."""
    parent = evals_dir.resolve().parent
    out: list[tuple[str, Path]] = []
    for path in sorted(evals_dir.rglob("*")):
        if path.is_file():
            rel = path.resolve().relative_to(parent).as_posix()
            out.append((rel, path))
    return out


def cmd_upload(args: argparse.Namespace) -> int:
    evals_dir = Path(args.evals_dir)
    if not (evals_dir / "pipeline" / "meta.yaml").exists():
        print(f"no bundle at {evals_dir}/pipeline/meta.yaml — run synthesis first", file=sys.stderr)
        return 1
    proj = linked_project(evals_dir)
    if not proj or not proj.get("token"):
        print("not linked yet — run `publish.py link` first", file=sys.stderr)
        return 1
    url = proj.get("base_url") or base_url(args.base_url)
    org, project, token = proj["org_slug"], proj["project_slug"], proj["token"]
    api = f"{url}/api/orgs/{org}/projects/{project}"

    # 1) Import the pipeline + graders.
    files = collect_bundle_files(evals_dir)
    code, data = multipart_post(f"{api}/import?mode={args.mode}", files, token)
    if code == 401:
        print("token rejected (revoked or expired) — re-run `publish.py link`", file=sys.stderr)
        return 1
    if code not in (200, 202):
        print(f"import failed (HTTP {code}): {json.dumps(data)[:300]}", file=sys.stderr)
        return 1
    print(f"Uploaded graders to {org}/{project}.")

    # 2) Upload captured datasets so the graders run on real rows. One request
    #    per file's call site is unnecessary — the backend derives the call site
    #    from each dataset filename (datasets/<call_site_id>.jsonl).
    datasets = sorted((evals_dir / "datasets").glob("*.jsonl")) if (evals_dir / "datasets").is_dir() else []
    if datasets:
        ds_files = [(p.name, p) for p in datasets]
        dc, ddata = multipart_post(f"{api}/traces/upload", ds_files, token)
        if dc in (200, 202):
            run_id = (ddata.get("data") or {}).get("runId")
            n = (ddata.get("data") or {}).get("totalEntries")
            print(f"Grading {n} captured trace rows → {url}/orgs/{org}/projects/{project}/runs/{run_id}")
        else:
            print(f"(datasets upload skipped: HTTP {dc})", file=sys.stderr)

    print(f"\nConnect more traces & see verdicts:\n  {url}/orgs/{org}/projects/{project}/setup?step=connect-traces")
    return 0


# ------------------------------------------------------------------------ cli

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="publish.py", description="Connect + push a synthesis bundle to evals.tessary.ai")
    p.add_argument("--base-url", default=None, help="platform origin (default: env EVALS_PLATFORM_URL or evals.tessary.ai)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("link", help="device-code link to a project")
    pl.add_argument("--evals-dir", default=".tessary")
    pl.add_argument("--label", default=None)
    pl.add_argument("--force", action="store_true", help="re-link even if a valid token exists")
    pl.set_defaults(func=cmd_link)

    pu = sub.add_parser("upload", help="push the bundle + datasets to the linked project")
    pu.add_argument("--evals-dir", default=".tessary")
    pu.add_argument("--mode", default="upsert", choices=["upsert", "replace"])
    pu.set_defaults(func=cmd_upload)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
