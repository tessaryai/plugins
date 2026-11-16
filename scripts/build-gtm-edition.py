#!/usr/bin/env python3
"""Generate the directory edition plugins/gtm from the full edition plugins/gtm-pro.

Usage:
    python3 scripts/build-gtm-edition.py           # regenerate plugins/gtm
    python3 scripts/build-gtm-edition.py --check   # fail if plugins/gtm is out of date

Steps, in order (all deterministic, standard library only):

1. Copy plugins/gtm-pro to a fresh folder, except lib/, __pycache__ and *.pyc.
2. Apply the text transforms in TRANSFORMS to every text file. They turn Pro
   strings into gtm strings ("/gtm-pro:" -> "/gtm:").
3. Write .claude-plugin/plugin.json from Pro's manifest with the gtm name,
   displayName and description. The version is inherited from gtm-pro.
4. Apply the overlay in scripts/gtm-edition-overlay/, verbatim (overlay text is
   never transformed):
     files/<path>       replaces <path>, or adds it when it is new
     prepend/<path>     inserted after the first line (the H1) of <path>
     append/<path>      appended to the end of <path>
     edits/<path>.edits exact edits on <path> (format below)
     edits/_all.edits   exact edits applied to every text file
5. Expand placeholders ({{UPGRADE}}, {{PRO_INSTALL}}, ...) in every text file.
6. Residue guard: fail if any file still tells Claude to run a script.

Edits file format. A line that starts with "@@ " starts a directive; the text
up to the next directive is its block (the block's final newline is dropped).

    @@ replace           find text (must occur exactly once in the file)
    @@ with              replacement text
    @@ replace-all       find text (must occur at least once)
    @@ with              replacement text
    @@ drop-line <text>  removes the one line that contains <text>
    @@ replace-section <heading line>
                         replaces that heading and its body, up to the next
                         heading of the same or a higher level, with the block
    @@ delete-section <heading line>

In _all.edits, "replace-all" must match at least once across the whole plugin.
Any edit that does not match fails the build, so a change in gtm-pro that
breaks an edit is caught at once.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRO = ROOT / "plugins" / "gtm-pro"
OUT = ROOT / "plugins" / "gtm"
OVERLAY = ROOT / "scripts" / "gtm-edition-overlay"

TEXT_SUFFIXES = {".md", ".json", ".txt", ".yaml", ".yml"}
TEXT_NAMES = {"LICENSE", "README", ".gitignore"}
SKIP_DIRS = {"lib", "__pycache__"}

# Pro -> gtm string transforms, applied in order to copied Pro text only.
TRANSFORMS = [
    ("/gtm-pro:", "/gtm:"),
]

MANIFEST = {
    "name": "gtm",
    "displayName": "Tessary GTM",
    "description": (
        "Host your CRM in Notion and run your go-to-market flow from Claude Code or Claude Cowork, "
        "with connectors only and no scripts: set up or map the databases, import a small CRM, sweep "
        "your inbox, calendar, LinkedIn and outreach tools into the CRM every day, build and write "
        "campaigns in your voice, send them with safety gates, and report the funnel. For large CRMs, "
        "big imports and API-key tools, install Tessary GTM Pro (gtm-pro@tessary)."
    ),
}

PRO_INSTALL = "gtm-pro@tessary"
PLACEHOLDERS = {
    "{{PRO_INSTALL}}": PRO_INSTALL,
    "{{UPGRADE}}": (
        "This needs Tessary GTM Pro. In Claude Code run `/plugin marketplace add tessaryai/plugins`, "
        f"then `/plugin install {PRO_INSTALL}`; your settings carry over. In Cowork, Tessary GTM Pro "
        "needs Claude Code: run this from Claude Code, pointed at the same project folder."
    ),
}

# Text that tells Claude to run a script. None of it may remain in plugins/gtm.
RESIDUE = re.compile(
    r"python3 -I|\$\{CLAUDE_PLUGIN_ROOT\}/lib|plugin root>/lib|\blib/[a-z_]+\.py|lib/\*\.py"
    r"|notion_rest|readonly_api|csv_import|funnel\.py|config\.py"
    r"|set-secret|has-secret|state-set|state-get"
    r"|access <mcp \| rest>|Export: <rest|Prefer REST|With a Notion token|Token present"
    r"|adding a Notion token|suggest a Notion token|token exists|REST `"
    r"|`RO /"
)


class BuildError(Exception):
    pass


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_pro(dest: Path) -> None:
    for src in sorted(PRO.rglob("*")):
        rel = src.relative_to(PRO)
        if any(part in SKIP_DIRS for part in rel.parts) or src.suffix == ".pyc":
            continue
        target = dest / rel
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)


def text_files(dest: Path):
    return [p for p in sorted(dest.rglob("*")) if p.is_file() and is_text(p)]


def apply_transforms(dest: Path) -> None:
    for path in text_files(dest):
        text = read(path)
        new = text
        for old, rep in TRANSFORMS:
            new = new.replace(old, rep)
        if new != text:
            write(path, new)


def write_manifest(dest: Path) -> None:
    pro = json.loads(read(PRO / ".claude-plugin" / "plugin.json"))
    out = {}
    for key, value in pro.items():
        out[key] = MANIFEST.get(key, value)
    write(dest / ".claude-plugin" / "plugin.json", json.dumps(out, indent=2, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ edits

def parse_edits(path: Path) -> list:
    """Return a list of (op, arg, block, block2) tuples."""
    ops, cur = [], None
    for line in read(path).split("\n"):
        if line.startswith("@@ "):
            words = line[3:].split(" ", 1)
            op, arg = words[0], (words[1] if len(words) > 1 else "")
            if op == "with":
                if cur is None or cur["op"] not in ("replace", "replace-all") or "with" in cur:
                    raise BuildError(f"{path}: '@@ with' without a replace before it")
                cur["with"] = []
                continue
            if op not in ("replace", "replace-all", "drop-line", "replace-section", "delete-section"):
                raise BuildError(f"{path}: unknown directive '{op}'")
            cur = {"op": op, "arg": arg, "find": []}
            ops.append(cur)
            continue
        if cur is None:
            if line.strip():
                raise BuildError(f"{path}: text before the first directive")
            continue
        (cur["with"] if "with" in cur else cur["find"]).append(line)
    result = []
    for o in ops:
        find = "\n".join(o["find"])
        rep = "\n".join(o.get("with", []))
        # Drop the one newline that separates a block from the next directive.
        find = find[:-1] if find.endswith("\n") else find
        rep = rep[:-1] if rep.endswith("\n") else rep
        if o["op"] in ("replace", "replace-all") and "with" not in o:
            raise BuildError(f"{path}: replace without '@@ with'")
        result.append((o["op"], o["arg"], find, rep))
    return result


def heading_level(line: str) -> int:
    m = re.match(r"^(#{1,6}) ", line)
    return len(m.group(1)) if m else 0


def section_span(lines: list, heading: str, where: str):
    idx = [i for i, l in enumerate(lines) if l == heading]
    if len(idx) != 1:
        raise BuildError(f"{where}: heading '{heading}' found {len(idx)} times, expected 1")
    start = idx[0]
    level = heading_level(heading)
    if not level:
        raise BuildError(f"{where}: '{heading}' is not a Markdown heading")
    end = len(lines)
    in_fence = False
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("```"):
            in_fence = not in_fence
        if not in_fence and 0 < heading_level(lines[i]) <= level:
            end = i
            break
    return start, end


def apply_one(text: str, op: str, arg: str, find: str, rep: str, where: str, allow_zero=False):
    """Apply one edit. Returns (new text, match count)."""
    if op == "replace":
        n = text.count(find)
        if n != 1:
            raise BuildError(f"{where}: replace target found {n} times, expected 1:\n{find[:300]}")
        return text.replace(find, rep), 1
    if op == "replace-all":
        n = text.count(find)
        if n == 0 and not allow_zero:
            raise BuildError(f"{where}: replace-all target not found:\n{find[:300]}")
        return text.replace(find, rep), n
    lines = text.split("\n")
    if op == "drop-line":
        idx = [i for i, l in enumerate(lines) if arg in l]
        if len(idx) != 1:
            raise BuildError(f"{where}: drop-line '{arg}' matched {len(idx)} lines, expected 1")
        del lines[idx[0]]
        return "\n".join(lines), 1
    if op in ("replace-section", "delete-section"):
        start, end = section_span(lines, arg, where)
        new = [] if op == "delete-section" else find.split("\n") + [""]
        lines[start:end] = new
        return "\n".join(lines), 1
    raise BuildError(f"{where}: unknown op {op}")


def apply_overlay(dest: Path) -> None:
    files = OVERLAY / "files"
    if files.is_dir():
        for src in sorted(p for p in files.rglob("*") if p.is_file()):
            target = dest / src.relative_to(files)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)

    edits_dir = OVERLAY / "edits"
    for src in sorted(p for p in edits_dir.rglob("*.edits") if p.is_file()):
        rel = src.relative_to(edits_dir)
        if str(rel) == "_all.edits":
            continue
        target = dest / str(rel)[: -len(".edits")]
        if not target.is_file():
            raise BuildError(f"{src}: target {target.relative_to(dest)} does not exist")
        text = read(target)
        for op, arg, find, rep in parse_edits(src):
            text, _ = apply_one(text, op, arg, find, rep, f"{rel}")
        write(target, text)

    all_edits = edits_dir / "_all.edits"
    if all_edits.is_file():
        files_text = {p: read(p) for p in text_files(dest)}
        for op, arg, find, rep in parse_edits(all_edits):
            if op != "replace-all":
                raise BuildError("_all.edits: only replace-all is allowed")
            total = 0
            for p in files_text:
                files_text[p], n = apply_one(files_text[p], op, arg, find, rep, "_all.edits", allow_zero=True)
                total += n
            if total == 0:
                raise BuildError(f"_all.edits: target not found in any file:\n{find[:300]}")
        for p, t in files_text.items():
            write(p, t)

    for kind in ("prepend", "append"):
        base = OVERLAY / kind
        if not base.is_dir():
            continue
        for src in sorted(p for p in base.rglob("*") if p.is_file()):
            target = dest / src.relative_to(base)
            if not target.is_file():
                raise BuildError(f"{src}: target {target.relative_to(dest)} does not exist")
            text, add = read(target), read(src)
            if kind == "append":
                text = text.rstrip("\n") + "\n\n" + add.rstrip("\n") + "\n"
            else:
                first, _, rest = text.partition("\n")
                text = first + "\n\n" + add.rstrip("\n") + "\n" + rest
            write(target, text)


def expand_placeholders(dest: Path) -> None:
    for path in text_files(dest):
        text = read(path)
        new = text
        for key, value in PLACEHOLDERS.items():
            new = new.replace(key, value)
        left = re.findall(r"\{\{[A-Z_]+\}\}", new)
        if left:
            raise BuildError(f"{path.relative_to(dest)}: unknown placeholder {left[0]}")
        if new != text:
            write(path, new)


def residue_guard(dest: Path) -> None:
    hits = []
    for path in text_files(dest):
        for n, line in enumerate(read(path).split("\n"), 1):
            for m in RESIDUE.finditer(line):
                hits.append(f"{path.relative_to(dest)}:{n}: {m.group(0)}: {line.strip()[:160]}")
    if hits:
        raise BuildError("script references remain in the gtm edition:\n" + "\n".join(hits))


def build(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copy_pro(dest)
    apply_transforms(dest)
    write_manifest(dest)
    apply_overlay(dest)
    expand_placeholders(dest)
    residue_guard(dest)


def diff_trees(a: Path, b: Path) -> list:
    def listing(root):
        return {p.relative_to(root) for p in root.rglob("*") if p.is_file()
                and "__pycache__" not in p.parts and p.name != ".DS_Store"}
    la, lb = listing(a), listing(b)
    out = [f"only in generated: {p}" for p in sorted(la - lb)]
    out += [f"only in plugins/gtm: {p}" for p in sorted(lb - la)]
    out += [f"differs: {p}" for p in sorted(la & lb) if not filecmp.cmp(a / p, b / p, shallow=False)]
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true",
                        help="regenerate into a temp folder and fail if plugins/gtm differs")
    args = parser.parse_args(argv)
    if not PRO.is_dir():
        print(f"error: {PRO} not found", file=sys.stderr)
        return 1
    try:
        if args.check:
            with tempfile.TemporaryDirectory() as tmp:
                gen = Path(tmp) / "gtm"
                build(gen)
                if not OUT.is_dir():
                    print("error: plugins/gtm does not exist; run scripts/build-gtm-edition.py", file=sys.stderr)
                    return 1
                diffs = diff_trees(gen, OUT)
                if diffs:
                    print("plugins/gtm is out of date; run python3 scripts/build-gtm-edition.py", file=sys.stderr)
                    print("\n".join(diffs), file=sys.stderr)
                    return 1
            print("ok: plugins/gtm matches plugins/gtm-pro plus the overlay")
            return 0
        with tempfile.TemporaryDirectory() as tmp:
            gen = Path(tmp) / "gtm"
            build(gen)
            if OUT.exists():
                shutil.rmtree(OUT)
            shutil.copytree(gen, OUT)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
