#!/usr/bin/env python3
"""
finalize.py — assemble final tessary-evals/ artifacts at step 7.

Reads the v0.4 sharded pipeline under tessary-evals/pipeline/ and the per-grader files
under tessary-evals/graders/, then:

  1. Writes tessary-evals/pipeline/meta.yaml from CLI flags (version, product_hint,
     runtime). Skips if --skip-meta is passed (orchestrator wrote it already).
  2. Generates tessary-evals/report.md from the shard contents.
  3. Writes tessary-evals/.synth-lock.yaml with SHA-256 of every shard and every grader.
  4. Runs validate.py --bundle tessary-evals/ and surfaces its exit status.

Usage:
    python3 finalize.py tessary-evals/ \
        [--version 0.9.0] \
        [--product-hint "<string>"] \
        [--runtime-yaml runtime.yaml] \
        [--inputs-digest <hex>] \
        [--skip-meta] \
        [--skip-report] \
        [--skip-validate]

Exit codes:
    0 -- finalize succeeded and validate.py --bundle returned 0
    1 -- validate.py --bundle returned non-zero (report.md still written)
    2 -- usage / I/O error
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("finalize.py: requires PyYAML. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_io  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Report generation. Mirrors the section order documented in output_format.md.
# ---------------------------------------------------------------------------

def _render_packs(packs: list[dict[str, Any]],
                  per_pack_counts: dict[str, int]) -> str:
    if not packs:
        return "## Engaged packs\n\n*(none — baseline-only run)*\n"
    lines = ["## Engaged packs", ""]
    lines.append("| id | name | tier_hint | enabled_by | contributed failures |")
    lines.append("|---|---|---|---|---|")
    for p in packs:
        pid = p.get("id") or ""
        lines.append(
            f"| `{pid}` | {p.get('name') or ''} | {p.get('tier_hint') or ''} "
            f"| {p.get('enabled_by') or ''} | {per_pack_counts.get(pid, 0)} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_product_profile(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return "## Product profile\n\n*(no profile produced)*\n"
    lines = ["## Product profile", ""]
    if profile.get("domain"):
        lines.append(f"**Domain:** {profile['domain']}")
    if profile.get("business_model"):
        lines.append(f"**Business model:** {profile['business_model']}")
    if profile.get("user_types"):
        lines.append("")
        lines.append("**User types:**")
        for u in profile["user_types"]:
            if isinstance(u, dict):
                lines.append(f"- {u.get('role', '?')} ({u.get('surface', '?')}): "
                             f"{u.get('constraints', '')}")
    if profile.get("regulatory_context"):
        lines.append("")
        lines.append("**Regulatory context:**")
        for r in profile["regulatory_context"]:
            if isinstance(r, dict):
                lines.append(f"- {r.get('regime')} -- {r.get('evidence')}")
    if profile.get("data_sensitivity"):
        lines.append("")
        lines.append("**Data sensitivity:**")
        for d in profile["data_sensitivity"]:
            if isinstance(d, dict):
                lines.append(f"- {d.get('kind')} -- {d.get('evidence')}")
    return "\n".join(lines) + "\n"


def _render_invariants(invariants: list[dict[str, Any]]) -> str:
    if not invariants:
        return "## Implicit invariants\n\n*(none)*\n"
    lines = ["## Implicit invariants", "", "| name | confidence | description |",
             "|---|---|---|"]
    for inv in invariants:
        if not isinstance(inv, dict):
            continue
        lines.append(f"| `{inv.get('name')}` | {inv.get('confidence')} "
                     f"| {(inv.get('description') or '').splitlines()[0] if inv.get('description') else ''} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_taxonomy(taxonomy: list[dict[str, Any]],
                     failure_modes: list[dict[str, Any]]) -> str:
    if not taxonomy:
        return "## Failure taxonomy\n\n*(none)*\n"
    children: dict[str | None, list[dict[str, Any]]] = {}
    for t in taxonomy:
        if not isinstance(t, dict):
            continue
        children.setdefault(t.get("parent_id"), []).append(t)
    # Count failures per node, split by scope.
    counts: dict[str, dict[str, int]] = {}
    for fm in failure_modes:
        node = fm.get("taxonomy_node_id")
        if not node:
            continue
        bucket = counts.setdefault(node, {"single_call": 0, "chain": 0})
        bucket[fm.get("scope") or "single_call"] = bucket.get(
            fm.get("scope") or "single_call", 0) + 1

    lines = ["## Failure taxonomy", ""]

    def walk(parent: str | None, depth: int) -> None:
        for node in sorted(children.get(parent, []), key=lambda n: n.get("id") or ""):
            nid = node.get("id") or ""
            c = counts.get(nid, {})
            badge = f"({c.get('single_call', 0)} single-call, {c.get('chain', 0)} chain)"
            lines.append(f"{'  ' * depth}- `{nid}` -- {node.get('name', '')} {badge}")
            walk(nid, depth + 1)

    walk(None, 0)
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_chains(chains: list[dict[str, Any]],
                   failure_modes: list[dict[str, Any]],
                   graders_by_fm: dict[str, dict[str, Any]]) -> str:
    if not chains:
        return "## Chains\n\n*(no chains detected)*\n"
    by_chain: dict[str, list[dict[str, Any]]] = {}
    for fm in failure_modes:
        if fm.get("scope") == "chain":
            by_chain.setdefault(fm.get("chain_id") or "", []).append(fm)
    lines = ["## Chains", ""]
    for c in chains:
        if not isinstance(c, dict):
            continue
        cid = c.get("id") or ""
        lines.append(f"### `{cid}` -- {c.get('name', '')}")
        lines.append(f"- Detection: `{c.get('detection_method')}` "
                     f"(confidence: {c.get('confidence')})")
        sites = c.get("call_site_ids") or []
        lines.append(f"- Call sites: {', '.join(f'`{s}`' for s in sites)}")
        if c.get("rationale"):
            lines.append(f"- Rationale: {c.get('rationale')}")
        for fm in by_chain.get(cid, []):
            g = graders_by_fm.get(fm.get("id") or "", {})
            lines.append(f"  - **{fm.get('name')}** ({fm.get('severity')}) "
                         f"-- {fm.get('description')}")
            if g:
                lines.append(f"    grader: `{g.get('id')}` "
                             f"(confidence: {g.get('confidence')})")
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_call_sites(call_sites: list[dict[str, Any]],
                       failure_modes: list[dict[str, Any]],
                       graders_by_fm: dict[str, dict[str, Any]]) -> str:
    if not call_sites:
        return "## Call sites\n\n*(no call sites)*\n"
    by_site: dict[str, list[dict[str, Any]]] = {}
    for fm in failure_modes:
        if fm.get("scope") == "single_call":
            by_site.setdefault(fm.get("call_site_id") or "", []).append(fm)
    lines = ["## Call sites", ""]
    for cs in call_sites:
        if not isinstance(cs, dict):
            continue
        sid = cs.get("id") or ""
        lines.append(f"### `{sid}` -- {cs.get('use_case', '')}")
        invocation = cs.get("invocation") or "sdk"
        if invocation != "sdk":
            lines.append(f"- Invocation: `{invocation}` (indirect)")
        lines.append(f"- Provider/model: `{cs.get('provider')}` / "
                     f"`{cs.get('model')}`")
        lines.append(f"- Shape: `{cs.get('shape')}` "
                     f"(confidence: {cs.get('shape_confidence')})")
        if cs.get("intent"):
            lines.append(f"- Intent: {cs['intent']}")
        observed = cs.get("observed") or {}
        if any(v is not None for v in observed.values()) if isinstance(observed, dict) else False:
            lines.append("- Observed:")
            for k, v in observed.items():
                if v is not None:
                    lines.append(f"  - {k}: {v}")
        site_fms = by_site.get(sid, [])
        if site_fms:
            lines.append("")
            lines.append("**Failure modes:**")
            for fm in site_fms:
                g = graders_by_fm.get(fm.get("id") or "", {})
                lines.append(f"  - **{fm.get('name')}** "
                             f"(layer {fm.get('layer')}, {fm.get('severity')}) "
                             f"-- {fm.get('description')}")
                if g:
                    lines.append(f"    grader: `{g.get('id')}` "
                                 f"(confidence: {g.get('confidence')})")
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_quality_dimensions(quality_dimensions: list[dict[str, Any]],
                               graders_by_qd: dict[str, dict[str, Any]]) -> str:
    if not quality_dimensions:
        return "## Quality dimensions\n\n*(none — no judgment call sites scored)*\n"
    by_site: dict[str, list[dict[str, Any]]] = {}
    for qd in quality_dimensions:
        if isinstance(qd, dict):
            by_site.setdefault(qd.get("call_site_id") or "", []).append(qd)
    lines = ["## Quality dimensions",
             "",
             "Continuous 1–5 quality scores tracked as a trend over time (never gates)."]
    for site in sorted(by_site):
        lines.append("")
        lines.append(f"### `{site}`")
        for qd in by_site[site]:
            g = graders_by_qd.get(qd.get("id") or "", {})
            conf = f" (judge confidence: {g.get('confidence')})" if g else ""
            lines.append(f"- **{qd.get('name')}** — {qd.get('description') or ''}{conf}")
            if qd.get("why_it_matters"):
                lines.append(f"  - *Why:* {qd.get('why_it_matters')}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_validation_warnings(graders: list[dict[str, Any]]) -> str:
    bad = [g for g in graders
           if isinstance(g, dict) and g.get("_validation_error")]
    if not bad:
        return ""
    lines = ["## Validation warnings", ""]
    for g in bad:
        lines.append(f"- `{g.get('id')}` -- {g.get('_validation_error')}")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_report(pipeline: dict[str, Any],
                  graders: list[dict[str, Any]]) -> str:
    fm_list = [fm for fm in pipeline.get("failure_modes") or []
               if isinstance(fm, dict)]
    single_fms = [fm for fm in fm_list if fm.get("scope") == "single_call"]
    chain_fms = [fm for fm in fm_list if fm.get("scope") == "chain"]
    single_graders = [g for g in graders if g.get("scope") == "single_call"]
    chain_graders = [g for g in graders if g.get("scope") == "chain"]
    failed = [g for g in graders if g.get("_validation_error")]
    low_conf = [g for g in graders if g.get("confidence") == "low"]

    per_pack_counts: dict[str, int] = {}
    for fm in fm_list:
        for pid in fm.get("pack_ids") or []:
            per_pack_counts[pid] = per_pack_counts.get(pid, 0) + 1

    graders_by_fm = {g.get("failure_mode_id"): g for g in graders
                     if isinstance(g, dict) and g.get("failure_mode_id")}
    graders_by_qd = {g.get("quality_dimension_id"): g for g in graders
                     if isinstance(g, dict) and g.get("quality_dimension_id")}
    quality_dimensions = [qd for qd in pipeline.get("quality_dimensions") or []
                          if isinstance(qd, dict)]

    head = [
        "# Synthesized eval pipeline",
        "",
        f"**Product hint:** {pipeline.get('product_hint') or '*(none)*'}",
        "",
        (f"**Summary:** {len(pipeline.get('call_sites') or [])} call sites, "
         f"{len(pipeline.get('chains') or [])} chains, "
         f"{len(single_fms)} single-call failures + {len(chain_fms)} chain failures, "
         f"{len(graders)} graders ({len(single_graders)} single-call + "
         f"{len(chain_graders)} chain, {len(failed)} failed validation, "
         f"{len(low_conf)} low-confidence), "
         f"{len(pipeline.get('taxonomy') or [])} taxonomy nodes, "
         f"{len(pipeline.get('packs') or [])} packs."),
        "",
    ]
    body = (
        _render_packs(pipeline.get("packs") or [], per_pack_counts)
        + _render_product_profile(pipeline.get("product_profile"))
        + _render_invariants(pipeline.get("implicit_invariants") or [])
        + _render_taxonomy(pipeline.get("taxonomy") or [], fm_list)
        + _render_chains(pipeline.get("chains") or [], fm_list, graders_by_fm)
        + _render_call_sites(pipeline.get("call_sites") or [], fm_list, graders_by_fm)
        + _render_quality_dimensions(quality_dimensions, graders_by_qd)
        + _render_validation_warnings(graders)
    )
    return "\n".join(head) + body


# ---------------------------------------------------------------------------
# Lock file.
# ---------------------------------------------------------------------------

def _compute_progress(pipeline: dict[str, Any],
                      graders: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize how much of the synthesis is done so the viewer can show progress."""
    call_sites = [cs for cs in pipeline.get("call_sites") or [] if isinstance(cs, dict)]
    sites_total = len(call_sites)
    fms = [fm for fm in pipeline.get("failure_modes") or [] if isinstance(fm, dict)]
    deferred = sum(1 for fm in fms if fm.get("grader_deferred") is True)

    grader_ids = {g.get("id") for g in graders if isinstance(g, dict)}
    per_site_expected: dict[str, int] = {}
    per_site_emitted: dict[str, int] = {}
    for fm in fms:
        if fm.get("scope") != "single_call":
            continue
        sid = fm.get("call_site_id")
        if not sid:
            continue
        if fm.get("grader_deferred") is True:
            continue
        per_site_expected[sid] = per_site_expected.get(sid, 0) + 1
        if fm.get("grader_id") in grader_ids:
            per_site_emitted[sid] = per_site_emitted.get(sid, 0) + 1

    sites_completed = 0
    for cs in call_sites:
        sid = cs.get("id")
        if not sid:
            continue
        if cs.get("shape") is None:
            continue
        expected = per_site_expected.get(sid, 0)
        emitted = per_site_emitted.get(sid, 0)
        if expected == 0 or emitted >= expected:
            sites_completed += 1

    return {
        "sites_completed": sites_completed,
        "sites_total": sites_total,
        "deferred_failure_count": deferred,
    }


def write_lock(evals_dir: Path, inputs_digest: str | None) -> Path:
    existing = pipeline_io.read_lock(evals_dir)

    shards: dict[str, str] = {}
    for path in pipeline_io.iter_shard_paths(evals_dir):
        rel = path.relative_to(evals_dir).as_posix()
        shards[rel] = _sha256_hex(path.read_text(encoding="utf-8"))
    graders: dict[str, str] = {}
    graders_dir = evals_dir / "graders"
    if graders_dir.is_dir():
        for gpath in sorted(graders_dir.glob("*.yaml")):
            graders[gpath.stem] = _sha256_hex(gpath.read_text(encoding="utf-8"))

    lock = {
        "version": 1,
        "synthesized_at": _iso_now(),
        "inputs_digest": inputs_digest,
        "shards": shards,
        "graders": graders,
    }
    if isinstance(existing.get("completed_steps"), dict):
        lock["completed_steps"] = existing["completed_steps"]
    out = evals_dir / ".synth-lock.yaml"
    out.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assemble final tessary-evals/ artifacts at step 7.",
    )
    ap.add_argument("evals_dir", help="Path to the tessary-evals/ directory.")
    ap.add_argument("--version", default="0.9.0",
                    help="On-disk schema version written into meta.yaml.")
    ap.add_argument("--product-hint", default=None)
    ap.add_argument("--runtime-yaml", default=None,
                    help="Optional YAML file with runtime fields to embed in meta.yaml.")
    ap.add_argument("--inputs-digest", default=None,
                    help="Optional digest over orchestrator inputs (recorded in lock).")
    ap.add_argument("--skip-meta", action="store_true",
                    help="Skip writing meta.yaml (orchestrator wrote it earlier).")
    ap.add_argument("--skip-report", action="store_true")
    ap.add_argument("--skip-validate", action="store_true")
    ap.add_argument("--partial", action="store_true",
                    help="Mid-synthesis run: deferred failures get no grader, bundle "
                         "validator runs in --partial mode, meta.yaml records progress.")
    args = ap.parse_args()

    evals_dir = Path(args.evals_dir).resolve()
    if not (evals_dir / "pipeline").is_dir():
        print(f"finalize.py: {evals_dir}/pipeline/ not found", file=sys.stderr)
        return 2

    # Load assembled pipeline + grader files for the report and progress fields.
    try:
        pipeline = pipeline_io.load_pipeline(evals_dir)
    except RuntimeError as e:
        print(f"finalize.py: {e}", file=sys.stderr)
        return 2
    graders: list[dict[str, Any]] = []
    graders_dir = evals_dir / "graders"
    if graders_dir.is_dir():
        for gpath in sorted(graders_dir.glob("*.yaml")):
            try:
                doc = yaml.safe_load(gpath.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                doc = {"id": gpath.stem, "_load_error": True}
            if isinstance(doc, dict):
                graders.append(doc)

    progress = _compute_progress(pipeline, graders)

    # 1. meta.yaml
    if not args.skip_meta:
        runtime: dict[str, Any] = {}
        if args.runtime_yaml:
            runtime_path = Path(args.runtime_yaml).resolve()
            if runtime_path.is_file():
                loaded = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    runtime = loaded
        pipeline_io.write_meta(evals_dir, args.version, args.product_hint, runtime,
                               progress=progress)

    # 2. report.md
    if not args.skip_report:
        report = render_report(pipeline, graders)
        (evals_dir / "report.md").write_text(report, encoding="utf-8")

    # 3. .synth-lock.yaml (after all shards + graders are in place).
    write_lock(evals_dir, args.inputs_digest)

    # 4. validate.py --bundle
    bundle_rc = 0
    if not args.skip_validate:
        validate_path = SCRIPT_DIR / "validate.py"
        cmd = [sys.executable, str(validate_path), "--bundle", str(evals_dir)]
        if args.partial:
            cmd.append("--partial")
        proc = subprocess.run(cmd, capture_output=False)
        bundle_rc = proc.returncode

    # Summary line for the orchestrator log.
    fm_list = [fm for fm in pipeline.get("failure_modes") or []
               if isinstance(fm, dict)]
    failed = sum(1 for g in graders if g.get("_validation_error"))
    low = sum(1 for g in graders if g.get("confidence") == "low")
    print(
        f"tessary-evals/ written: {len(pipeline.get('call_sites') or [])} call sites | "
        f"{len(pipeline.get('chains') or [])} chains | "
        f"{len(fm_list)} failures | {len(graders)} graders "
        f"({failed} failed validation, {low} low-confidence) | "
        f"{len(pipeline.get('taxonomy') or [])} taxonomy nodes | "
        f"{len(pipeline.get('packs') or [])} packs"
    )
    if failed:
        print(f"WARN: {failed} grader(s) failed schema validation -- "
              f"inspect: tessary-evals/graders/<id>.yaml")
    return 0 if bundle_rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
