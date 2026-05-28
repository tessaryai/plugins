#!/usr/bin/env python3
"""Resolve crew's effective configuration for the target repo.

Resolution order (later wins):
  1. built-in defaults (below)
  2. crew.config.yaml at the repo root, if present
  3. light auto-detection (package manager / test commands / docs index) used
     only to fill values the user did not set

Usage:
  python3 load_config.py                 # print resolved config as JSON
  python3 load_config.py get labels.bug  # print one value (dotted path)
  python3 load_config.py --root /path     # override the repo root

The script has no third-party dependencies. It uses PyYAML if it happens to be
installed, otherwise a tolerant parser covering the documented config subset.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULTS = {
    # How crew sources work and persists results:
    #   auto   — github when given an issue/PR number (or in an authed repo with
    #            no explicit task), otherwise local
    #   github — issues/PRs via gh
    #   local  — freeform tasks tracked in the local ledger, no gh required
    "mode": "auto",
    "project": {"name": None, "docs_index": None},
    "ledger": {"dir": ".crew"},
    "local": {"isolation": "auto"},  # auto | kosho | git-worktree | none
    "labels": {
        "bug": "bug",
        "task": "task",
        "triaged": "triaged",
        "docs": "docs",
        "agent_pr": "agent-generated",
        "needs_human": "needs-human",
        "cleanup": "cleanup",
    },
    "guardrails": {
        "protected_paths": [
            "**/migrations/**",
            "**/*.tf",
            "Dockerfile*",
            ".env*",
            ".github/**",
        ],
        "max_files_per_pr": 5,
        "max_review_iterations": 3,
    },
    "commands": {"install": None, "lint": None, "typecheck": None, "test": None},
    "review_standards": {"source": "AGENTS.md"},
    "team": {
        "personas": [
            "architect",
            "pragmatist",
            "perf-analyst",
            "visionary",
            "product-advocate",
        ]
    },
    "knowledge": {"dir": "docs/knowledge"},
    "orchestrator": {"max_items": 5, "concurrency": 2, "auto_merge": False},
}


def find_root(override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip()).resolve()
    except Exception:
        return Path.cwd().resolve()


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


# --- YAML loading: PyYAML if available, else a small tolerant subset parser ---

def _coerce(s: str):
    t = s.strip()
    if t == "" or t in ("null", "~", "None"):
        return None
    if t.lower() in ("true", "yes"):
        return True
    if t.lower() in ("false", "no"):
        return False
    if (t[0], t[-1]) in (('"', '"'), ("'", "'")):
        return t[1:-1]
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _parse_flow(t: str):
    t = t.strip()
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [_coerce(x) for x in _split_top(inner)] if inner else []
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        d = {}
        for part in _split_top(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                d[k.strip()] = _coerce(v)
        return d
    return _coerce(t)


def _split_top(s: str):
    """Split on commas not nested in brackets/quotes."""
    out, buf, depth, quote = [], [], 0, None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf))
    return [x.strip() for x in out]


def _mini_yaml(text: str) -> dict:
    """Parse the documented config subset: nested maps, block/flow lists, scalars."""
    root: dict = {}
    # stack of (indent, container)
    stack = [(-1, root)]
    lines = [ln.rstrip() for ln in text.splitlines()]
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item = _parse_flow(line[2:])
            if not isinstance(parent, list):
                continue
            parent.append(item)
            continue
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            # could be a nested map or a block list; peek ahead
            nxt = None
            for j in range(i, len(lines)):
                if lines[j].strip() and not lines[j].lstrip().startswith("#"):
                    nxt = lines[j]
                    break
            if nxt is not None and nxt.strip().startswith("- ") and (
                len(nxt) - len(nxt.lstrip())
            ) > indent:
                container: list = []
            else:
                container = {}
            if isinstance(parent, dict):
                parent[key] = container
            stack.append((indent, container))
        else:
            if isinstance(parent, dict):
                parent[key] = _parse_flow(rest)
    return root


def load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ModuleNotFoundError:
        return _mini_yaml(text)


# --- auto-detection -----------------------------------------------------------

def detect_commands(root: Path) -> dict:
    cmds = {"install": None, "lint": None, "typecheck": None, "test": None}
    if (root / "package.json").exists():
        cmds.update(install="npm ci", lint="npm run lint", test="npm test")
        try:
            pkg = json.loads((root / "package.json").read_text())
            scripts = pkg.get("scripts", {})
            if "typecheck" in scripts:
                cmds["typecheck"] = "npm run typecheck"
            if "lint" not in scripts:
                cmds["lint"] = None
            if "test" not in scripts:
                cmds["test"] = None
        except Exception:
            pass
    elif (root / "pyproject.toml").exists():
        cmds.update(
            install="pip install -e .",
            lint="ruff check .",
            typecheck="mypy .",
            test="pytest",
        )
    elif (root / "go.mod").exists():
        cmds.update(install="go mod download", lint="go vet ./...", test="go test ./...")
    elif (root / "Cargo.toml").exists():
        cmds.update(install="cargo fetch", lint="cargo clippy", test="cargo test")
    return cmds


def detect_docs_index(root: Path) -> str | None:
    for cand in ("docs/INDEX.md", "docs/README.md", "docs/index.md", "AGENTS.md"):
        if (root / cand).exists():
            return cand
    return None


def resolve(root: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    cfg_path = root / "crew.config.yaml"
    if cfg_path.exists():
        user = load_yaml(cfg_path)
        cfg = deep_merge(cfg, user)
    # fill unset commands via detection
    detected = detect_commands(root)
    for k, v in cfg["commands"].items():
        if v is None and detected.get(k):
            cfg["commands"][k] = detected[k]
    if not cfg["project"].get("docs_index"):
        cfg["project"]["docs_index"] = detect_docs_index(root)
    cfg["_meta"] = {
        "root": str(root),
        "config_file": str(cfg_path) if cfg_path.exists() else None,
    }
    return cfg


def dig(cfg: dict, dotted: str):
    cur = cfg
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def main(argv: list[str]) -> int:
    root_override = None
    args = []
    it = iter(argv)
    for a in it:
        if a == "--root":
            root_override = next(it, None)
        else:
            args.append(a)
    cfg = resolve(find_root(root_override))
    if args and args[0] == "get" and len(args) > 1:
        val = dig(cfg, args[1])
        if isinstance(val, (dict, list)):
            print(json.dumps(val))
        else:
            print("" if val is None else val)
    else:
        print(json.dumps(cfg, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
