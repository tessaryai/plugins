#!/usr/bin/env python3
"""Check that a plugin folder holds only the file types an unverified
organization may ship in the Anthropic plugin directory.

Usage:
    python3 scripts/check-plugin-files.py plugins/gtm [more folders ...]

A file fails when:
- its extension is not .md, .txt, .json, .yaml, .yml, .png, .jpg, .jpeg, .gif,
  .webp or .ico (files named LICENSE, README or .gitignore, with no extension,
  are also allowed),
- it starts with "#!",
- it is a text file that is not valid UTF-8, or
- it is a text file that holds a NUL byte.

A symbolic link also fails. Exit 0 when every file passes, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}
BARE_NAMES = {"LICENSE", "README", ".gitignore"}


def check_file(path: Path) -> list:
    problems = []
    if path.is_symlink():
        return ["is a symbolic link"]
    suffix = path.suffix.lower()
    is_text = suffix in TEXT_SUFFIXES or path.name in BARE_NAMES
    if not is_text and suffix not in IMAGE_SUFFIXES:
        problems.append(f"file type not allowed ({suffix or 'no extension'})")
    data = path.read_bytes()
    if data.startswith(b"#!"):
        problems.append("starts with #!")
    if is_text:
        if b"\x00" in data:
            problems.append("holds a NUL byte")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"not valid UTF-8 (byte {exc.start})")
    return problems


def check_folder(root: Path) -> list:
    failures = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        for problem in check_file(path):
            failures.append(f"{path}: {problem}")
    return failures


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 1
    failures, count = [], 0
    for arg in args:
        root = Path(arg)
        if not root.is_dir():
            print(f"error: {root} is not a folder", file=sys.stderr)
            return 1
        count += sum(1 for p in root.rglob("*") if not p.is_dir() or p.is_symlink())
        failures += check_folder(root)
    if failures:
        print("\n".join(failures))
        print(f"{len(failures)} problem(s) in {count} file(s)", file=sys.stderr)
        return 1
    print(f"ok: {count} file(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
