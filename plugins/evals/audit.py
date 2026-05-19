#!/usr/bin/env python3
"""
audit.py — mechanical audit of the post-dedup failure-mode set (step 4.7).

Replaces the LLM-driven self-audit prompt with a deterministic Python script.
Reads the v0.4 sharded pipeline via pipeline_io.load_pipeline() and emits a
JSON punch list to stdout — the orchestrator parses this to decide which
call_sites / packs / chains need a targeted-fix subagent.

Usage:
    python3 audit.py tessary-evals/
    python3 audit.py tessary-evals/ --json   # JSON output (default is human + JSON)

Exit codes:
    0 -- audit passed (no items)
    1 -- audit found items the orchestrator must fix
    2 -- usage / I/O error

The 11 checks mirror SKILL.md step 4.7. Each item in the punch list has a
`kind` (which type of fix is needed) and `target` (call_site_id / pack_id /
chain_id) so the orchestrator can fan out the right subagents.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_io  # noqa: E402


MIN_LAYER_A = 3
MIN_LAYER_B = 5
MIN_LAYER_C = 3
MIN_CHAIN_FAILURES = 3


def audit(pipeline: dict[str, Any], partial: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    call_sites = {cs.get("id"): cs for cs in pipeline.get("call_sites") or []
                  if isinstance(cs, dict)}
    chains = {c.get("id"): c for c in pipeline.get("chains") or []
              if isinstance(c, dict)}
    failure_modes = [fm for fm in pipeline.get("failure_modes") or []
                     if isinstance(fm, dict)]
    declared_packs = {p.get("id") for p in pipeline.get("packs") or []
                      if isinstance(p, dict)}
    declared_packs.discard(None)

    per_site_layer: dict[str, Counter[str]] = defaultdict(Counter)
    per_site_severity: dict[str, Counter[str]] = defaultdict(Counter)
    per_chain_count: Counter[str] = Counter()
    per_pack_count: Counter[str] = Counter()
    per_site_names: dict[str, list[str]] = defaultdict(list)

    for fm in failure_modes:
        scope = fm.get("scope")
        if scope == "single_call":
            site = fm.get("call_site_id") or ""
            per_site_layer[site][fm.get("layer") or "?"] += 1
            per_site_severity[site][fm.get("severity") or "?"] += 1
            per_site_names[site].append(fm.get("name") or "")
        elif scope == "chain":
            per_chain_count[fm.get("chain_id") or ""] += 1
        for pid in fm.get("pack_ids") or []:
            per_pack_count[pid] += 1

    # Q1-3: per-site layer coverage.
    for sid, cs in call_sites.items():
        shape = cs.get("shape")
        if shape == "embedding":
            continue
        layers = per_site_layer.get(sid, Counter())
        if layers["A"] < MIN_LAYER_A:
            items.append({"kind": "layer_a_undercoverage", "target": sid,
                          "have": layers["A"], "need": MIN_LAYER_A})
        if layers["B"] < MIN_LAYER_B:
            items.append({"kind": "layer_b_undercoverage", "target": sid,
                          "have": layers["B"], "need": MIN_LAYER_B})
        if layers["C"] < MIN_LAYER_C:
            items.append({"kind": "layer_c_undercoverage", "target": sid,
                          "have": layers["C"], "need": MIN_LAYER_C})

    # Q4: at least half of high-severity single-call failures from B+C combined.
    high_total = 0
    high_bc = 0
    for sid in call_sites:
        sev = per_site_severity.get(sid, Counter())
        layers = per_site_layer.get(sid, Counter())
        # Approximate: count high failures (we don't know the per-failure layer
        # without re-walking, so do it here once).
        pass
    layer_x_sev: Counter[tuple[str | None, str | None]] = Counter()
    for fm in failure_modes:
        if fm.get("scope") != "single_call":
            continue
        layer_x_sev[(fm.get("layer"), fm.get("severity"))] += 1
    high_total = sum(n for (_, sev), n in layer_x_sev.items() if sev == "high")
    high_bc = sum(n for (lyr, sev), n in layer_x_sev.items()
                  if sev == "high" and lyr in ("B", "C"))
    if high_total > 0 and high_bc * 2 < high_total:
        items.append({"kind": "high_severity_skew_mechanical", "target": None,
                      "high_bc": high_bc, "high_total": high_total})

    # Q5: same generic failure across every call site.
    # Requires every call site to be processed to be meaningful; skip when partial.
    if not partial:
        GENERIC_NAMES = {"hallucinates", "hallucination", "wrong_format",
                         "incorrect_output", "vulnerable_to_injection"}
        for name in GENERIC_NAMES:
            sites_with = {sid for sid, names in per_site_names.items() if name in names}
            if call_sites and len(sites_with) == len(call_sites) and len(sites_with) > 1:
                items.append({"kind": "generic_failure_repeated", "target": name,
                              "sites": sorted(sites_with)})

    # Q6: every chain has >=3 cross-call failures.
    for cid in chains:
        if per_chain_count[cid] < MIN_CHAIN_FAILURES:
            items.append({"kind": "chain_undercoverage", "target": cid,
                          "have": per_chain_count[cid], "need": MIN_CHAIN_FAILURES})

    # Q7: low-confidence chains must cite file/line in rationale.
    for cid, c in chains.items():
        if c.get("detection_method") == "sequential_composition":
            rationale = c.get("rationale") or ""
            if ":" not in rationale and "line" not in rationale.lower():
                items.append({"kind": "chain_low_confidence_no_evidence",
                              "target": cid})

    # Q8: invariant_coverage.likely_gap_in pairs each have at least one B/C failure.
    inv_cov = pipeline.get("invariant_coverage") or []
    for cov in inv_cov:
        if not isinstance(cov, dict):
            continue
        for sid in cov.get("likely_gap_in") or []:
            layers = per_site_layer.get(sid, Counter())
            if layers["B"] + layers["C"] == 0:
                items.append({"kind": "invariant_gap_uncovered", "target": sid,
                              "invariant": cov.get("invariant")})

    # Q9: every engaged pack contributed at least one failure (except quality).
    # Needs the full call-site set to be meaningful; skip when partial.
    if not partial:
        for pid in declared_packs:
            if pid == "quality":
                continue
            if per_pack_count[pid] == 0:
                items.append({"kind": "pack_no_contribution", "target": pid})

    # Q10: conflict-suffixed names exist (informational; dedup already flagged).
    for fm in failure_modes:
        name = fm.get("name") or ""
        if "__" in name and not name.startswith("_"):
            items.append({"kind": "conflict_suffix_present", "target": fm.get("id")})

    # Q11: all failure_modes[].pack_ids resolve.
    for fm in failure_modes:
        for pid in fm.get("pack_ids") or []:
            if pid not in declared_packs:
                items.append({"kind": "unresolved_pack_id", "target": fm.get("id"),
                              "pack_id": pid})

    return items


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Mechanical audit of the post-dedup failure-mode set (step 4.7).",
    )
    ap.add_argument("evals_dir", help="Path to the tessary-evals/ directory.")
    ap.add_argument("--json", action="store_true",
                    help="Emit only JSON (default also prints a human summary).")
    ap.add_argument("--partial", action="store_true",
                    help="Tolerate mid-synthesis state: report items but exit 0, and "
                         "suppress checks that need the full call-site set.")
    args = ap.parse_args()

    evals_dir = Path(args.evals_dir).resolve()
    if not (evals_dir / "pipeline").is_dir():
        print(f"audit.py: {evals_dir}/pipeline/ not found", file=sys.stderr)
        return 2

    try:
        pipeline = pipeline_io.load_pipeline(evals_dir)
    except RuntimeError as e:
        print(f"audit.py: {e}", file=sys.stderr)
        return 2

    items = audit(pipeline, partial=args.partial)

    if args.json:
        print(json.dumps({"items": items}, indent=2))
    else:
        if not items:
            print("Step 4.7: audit passed -- no items.")
        else:
            label = "warning(s)" if args.partial else "item(s)"
            print(f"Step 4.7: audit -- {len(items)} {label}:")
            for it in items:
                print(f"  - {it.get('kind')} target={it.get('target')!r} "
                      + " ".join(f"{k}={v!r}" for k, v in it.items()
                                 if k not in ("kind", "target")))
            print()
            print(json.dumps({"items": items}, indent=2))

    if args.partial:
        return 0
    return 1 if items else 0


if __name__ == "__main__":
    sys.exit(main())
