#!/usr/bin/env python3
"""
viewer.py — build a self-contained HTML viewer for a synthesized eval pipeline.

Reads:
    <evals_dir>/pipeline/**/*.yaml  (v0.4 sharded layout — assembled via pipeline_io)
    <evals_dir>/graders/**/*.yaml
    <evals_dir>/report.md           (optional)

Writes:
    <evals_dir>/index.html     (or the path passed via --output)

The output is a single HTML file with all data embedded inline — no fetch, no
build step, no external assets. Open it directly in a browser.

Template files (edit to customize the UI — no Python edits required):
    viewer_template/template.html  — page skeleton with {{styles}}, {{script}},
                                     {{data_json}}, {{config_json}}, {{cta_url}},
                                     {{cta_label}} placeholders
    viewer_template/styles.css     — all CSS
    viewer_template/app.js         — all client-side rendering logic

Usage:
    python3 viewer.py                       # defaults to ./evals
    python3 viewer.py path/to/evals
    python3 viewer.py path/to/evals --template-dir /custom/template
    python3 viewer.py path/to/evals --cta-url https://example.com

Exit codes:
    0  — wrote the viewer
    2  — usage / I/O error (missing inputs, missing template files, bad PyYAML)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Final, Mapping

try:
    import yaml
except ImportError:
    print("viewer.py: requires PyYAML. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_io  # noqa: E402


SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_DIR: Final[Path] = SCRIPT_DIR / "viewer_template"
DEFAULT_CTA_URL: Final[str] = "https://evals.tessary.ai"
DEFAULT_CTA_LABEL: Final[str] = "Continue on evals.tessary.ai"

# Mustache-style placeholders: {{name}} where `name` is [a-z][a-z0-9_]*.
# Single-pass substitution (see _apply_template) so a placeholder-shaped string
# inside user data — e.g. the literal `{{script}}` in a report.md — flows
# through unchanged.
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_SAFE_URL_SCHEME: Final[re.Pattern[str]] = re.compile(r"^(https?:|mailto:|/|#)", re.IGNORECASE)


def _load_yaml(path: Path) -> Mapping[str, Any]:
    """Load a YAML mapping; return an empty mapping for empty/non-mapping files."""
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    return loaded if isinstance(loaded, dict) else {}


def _dumps_for_script_island(obj: object) -> str:
    """JSON-encode for embedding inside <script type="application/json">.

    Escapes the `</` sequence so a literal `</script>` in any string value can't
    terminate the script tag early.
    """
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def _apply_template(tmpl: str, values: Mapping[str, str]) -> str:
    """Single-pass substitution of `{{name}}` placeholders.

    Order-independent: a substituted value can contain another placeholder-shaped
    string without triggering a second substitution. Unknown placeholders are
    left in place so they're visible during template authoring.
    """
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return values[key] if key in values else match.group(0)
    return _PLACEHOLDER_RE.sub(repl, tmpl)


def _safe_url(url: str) -> str:
    """Reject `javascript:` and other dangerous schemes; fall back to `#`."""
    return url if _SAFE_URL_SCHEME.match(url) else "#"


def collect(evals_dir: Path) -> dict[str, Any]:
    """Read pipeline.yaml + every graders/**/*.yaml + report.md from `evals_dir`.

    Individual grader load failures are captured into a placeholder entry
    rather than aborting the run, so a malformed file doesn't lose the
    rest of the bundle.
    """
    pipeline_root = evals_dir / "pipeline"
    if not pipeline_root.is_dir():
        pipeline: dict[str, Any] = {
            "version": None, "product_hint": None, "packs": [],
            "product_profile": None, "implicit_invariants": [], "invariant_coverage": [],
            "runtime": {}, "progress": {},
            "call_sites": [], "chains": [], "failure_modes": [], "taxonomy": [],
        }
    else:
        try:
            pipeline = pipeline_io.load_pipeline(evals_dir)
        except RuntimeError as e:
            print(f"viewer.py: {e}", file=sys.stderr)
            sys.exit(2)

    graders: list[Mapping[str, Any]] = []
    graders_dir = evals_dir / "graders"
    if graders_dir.is_dir():
        for gpath in sorted(graders_dir.rglob("*.yaml")):
            try:
                graders.append(_load_yaml(gpath))
            except Exception as e:  # YAML errors, permission errors, etc.
                rel = gpath.relative_to(evals_dir).as_posix()
                graders.append({"id": pipeline_io.grader_id_from_rel_path(rel),
                                "_load_error": str(e)})

    report_path = evals_dir / "report.md"
    report_md = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""

    return {"pipeline": pipeline, "graders": graders, "report_md": report_md}


def load_template(template_dir: Path) -> tuple[str, str, str]:
    """Return (template.html, styles.css, app.js); exit 2 if any file is missing."""
    required: tuple[tuple[str, str], ...] = (
        ("template.html", "page skeleton"),
        ("styles.css", "stylesheet"),
        ("app.js", "client script"),
    )
    contents: list[str] = []
    for fname, desc in required:
        path = template_dir / fname
        if not path.is_file():
            print(f"viewer.py: missing {desc} at {path}", file=sys.stderr)
            sys.exit(2)
        contents.append(path.read_text(encoding="utf-8"))
    return contents[0], contents[1], contents[2]


def build_html(
    data: Mapping[str, Any],
    template_dir: Path,
    cta_url: str,
    cta_label: str,
) -> str:
    tmpl, css, js = load_template(template_dir)
    safe_cta = _safe_url(cta_url)
    # `cta_url` lands inside an href="..." attribute; `cta_label` lands in
    # element text. Both need HTML escaping for their context.
    values: Mapping[str, str] = {
        "styles": css,
        "script": js,
        "cta_url": html.escape(safe_cta, quote=True),
        "cta_label": html.escape(cta_label, quote=False),
        "data_json": _dumps_for_script_island(data),
        "config_json": _dumps_for_script_island({"cta_url": safe_cta, "cta_label": cta_label}),
    }
    return _apply_template(tmpl, values)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build a self-contained HTML viewer for a .tessary/ directory.",
    )
    ap.add_argument("evals_dir", nargs="?", default=".tessary",
                    help="Path to the .tessary/ directory (default: ./.tessary)")
    ap.add_argument("-o", "--output",
                    help="Output HTML path (default: <evals_dir>/index.html)")
    ap.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR),
                    help="Template directory (default: <plugin>/viewer_template)")
    ap.add_argument("--cta-url", default=DEFAULT_CTA_URL,
                    help=f"URL for the header CTA button (default: {DEFAULT_CTA_URL})")
    ap.add_argument("--cta-label", default=DEFAULT_CTA_LABEL,
                    help=f"Label text for the header CTA button (default: {DEFAULT_CTA_LABEL!r})")
    args = ap.parse_args()

    evals_dir = Path(args.evals_dir).resolve()
    if not evals_dir.is_dir():
        print(f"viewer.py: {evals_dir} is not a directory", file=sys.stderr)
        return 2

    template_dir = Path(args.template_dir).resolve()
    if not template_dir.is_dir():
        print(f"viewer.py: template dir not found: {template_dir}", file=sys.stderr)
        return 2

    data = collect(evals_dir)
    out_path = Path(args.output).resolve() if args.output else (evals_dir / "index.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        build_html(data, template_dir, args.cta_url, args.cta_label),
        encoding="utf-8",
    )

    pipeline = data["pipeline"] if isinstance(data["pipeline"], dict) else {}
    cs = len(pipeline.get("call_sites") or [])
    ch = len(pipeline.get("chains") or [])
    fm = len(pipeline.get("failure_modes") or [])
    gn = len(data["graders"])
    print(f"viewer.py: wrote {out_path} "
          f"({cs} call sites, {ch} chains, {fm} failure modes, {gn} graders)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
