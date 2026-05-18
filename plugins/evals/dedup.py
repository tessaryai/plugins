#!/usr/bin/env python3
"""
dedup.py — deterministic three-pass dedup over failure_modes/ shards.

Replaces step 4.6's LLM-driven dedup with a pure Python function. Given the
same set of shard contents and the same engaged packs, this script produces
byte-identical output across re-runs — a contract requirement for the
synthesizer.

Usage:
    python3 dedup.py tessary-evals/

Reads:
    tessary-evals/pipeline/failure_modes/*.yaml

Writes (in place):
    Each shard rewritten with merged entries.

Prints:
    Step 4.6: dedup -- N raw failures -> M canonical (K exact-merged, J semantic-merged, R conflict-suffixed); packs contributing: [<id>, ...]

Three passes, in order:

  Pass 1 (exact)     -- same (scope, call_site|chain, name) -> merge via
                        union/max/longest reconciliation rules.
  Pass 2 (semantic)  -- within the same (scope, call_site|chain, layer),
                        names with morphology overlap and high description
                        similarity merge under the lexicographically smaller
                        name. Threshold: difflib.SequenceMatcher >= 0.85 on
                        (name + first 200 chars of description).
  Pass 3 (conflict)  -- if any post-pass collision survives, the larger
                        pack_id contributor renames to <name>__<pack_id>.

Layer precedence (most specific wins): C > B > A.
Severity precedence: high > medium > low.

Exit codes:
    0 -- ran cleanly (no errors; may still print WARN lines for conflicts)
    1 -- malformed input shard
    2 -- usage / I/O error
"""
from __future__ import annotations

import argparse
import difflib
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:
    print("dedup.py: requires PyYAML. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_io  # noqa: E402


SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
LAYER_RANK = {None: -1, "": -1, "A": 0, "B": 1, "C": 2}
SIM_THRESHOLD = 0.85


def _sev_max(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if SEVERITY_RANK.get(a, -1) >= SEVERITY_RANK.get(b, -1) else b


def _layer_max(a: str | None, b: str | None) -> str | None:
    return a if LAYER_RANK.get(a, -1) >= LAYER_RANK.get(b, -1) else b


def _union(a: Iterable[str] | None, b: Iterable[str] | None) -> list[str]:
    s: set[str] = set()
    if a:
        s.update(x for x in a if isinstance(x, str))
    if b:
        s.update(x for x in b if isinstance(x, str))
    return sorted(s)


def _longest_desc(a: str | None, b: str | None) -> str | None:
    """Pick the longer non-empty description; tiebreak lexicographically smaller."""
    a = a or ""
    b = b or ""
    if not a:
        return b or None
    if not b:
        return a or None
    if len(a) != len(b):
        return a if len(a) > len(b) else b
    return min(a, b)


def _reconcile(survivor: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Apply pass-1 reconciliation rules. Survivor's id/scope/site/chain/name win."""
    out = dict(survivor)
    out["pack_ids"] = _union(survivor.get("pack_ids"), other.get("pack_ids"))
    out["compliance_tags"] = _union(survivor.get("compliance_tags"),
                                    other.get("compliance_tags"))
    out["severity"] = _sev_max(survivor.get("severity"), other.get("severity"))
    out["layer"] = _layer_max(survivor.get("layer"), other.get("layer"))
    out["description"] = _longest_desc(survivor.get("description"),
                                       other.get("description"))
    return out


def _canonical_sort_key(fm: dict[str, Any]) -> tuple[Any, ...]:
    scope = fm.get("scope") or ""
    site_or_chain = fm.get("call_site_id") if scope == "single_call" else fm.get("chain_id")
    name = fm.get("name") or ""
    return (0 if scope == "single_call" else 1, site_or_chain or "", name)


def _sim_text(fm: dict[str, Any]) -> str:
    name = fm.get("name") or ""
    desc = (fm.get("description") or "")[:200]
    return f"{name}\n{desc}"


def dedup(failures: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Run the three-pass dedup. Returns (canonical_failures, stats).

    stats keys: exact_merged, semantic_merged, conflict_suffixed.
    """
    # Canonical sort.
    failures = sorted([dict(f) for f in failures], key=_canonical_sort_key)
    stats = {"exact_merged": 0, "semantic_merged": 0, "conflict_suffixed": 0}

    # Pass 1: exact merge on (scope, call_site|chain, name).
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for fm in failures:
        scope = fm.get("scope") or ""
        site_or_chain = (fm.get("call_site_id") if scope == "single_call"
                         else fm.get("chain_id")) or ""
        name = fm.get("name") or ""
        key = (scope, site_or_chain, name)
        if key in buckets:
            buckets[key] = _reconcile(buckets[key], fm)
            stats["exact_merged"] += 1
        else:
            buckets[key] = fm
    survivors = list(buckets.values())

    # Pass 2: semantic merge within (scope, site|chain, layer).
    groups: dict[tuple[str, str, Any], list[dict[str, Any]]] = defaultdict(list)
    for fm in survivors:
        scope = fm.get("scope") or ""
        site_or_chain = (fm.get("call_site_id") if scope == "single_call"
                         else fm.get("chain_id")) or ""
        groups[(scope, site_or_chain, fm.get("layer"))].append(fm)

    after_pass2: list[dict[str, Any]] = []
    for _, group in groups.items():
        # Within the group, sort by name asc so the lexicographically smaller wins.
        group = sorted(group, key=lambda f: f.get("name") or "")
        merged_indices: set[int] = set()
        for i, fa in enumerate(group):
            if i in merged_indices:
                continue
            current = fa
            for j in range(i + 1, len(group)):
                if j in merged_indices:
                    continue
                fb = group[j]
                ratio = difflib.SequenceMatcher(
                    None, _sim_text(current), _sim_text(fb)
                ).ratio()
                if ratio >= SIM_THRESHOLD:
                    # Merge fb into current (current is lex-smaller-named).
                    current = _reconcile(current, fb)
                    # Recompute id from current.name in case the merger
                    # shifted (no — id stays as the survivor's id).
                    merged_indices.add(j)
                    stats["semantic_merged"] += 1
            after_pass2.append(current)
    survivors = after_pass2

    # Pass 3: conflict suffix. After pass 2 a name collision can re-emerge if
    # pass-2 merging produced two entries within the same group whose names
    # coincide post-rename. Detect and disambiguate.
    final: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for fm in sorted(survivors, key=_canonical_sort_key):
        scope = fm.get("scope") or ""
        site_or_chain = (fm.get("call_site_id") if scope == "single_call"
                         else fm.get("chain_id")) or ""
        name = fm.get("name") or ""
        key = (scope, site_or_chain, name)
        if key in seen:
            # Pick the larger pack_id deterministically.
            pack_ids = sorted(fm.get("pack_ids") or [])
            tag = pack_ids[-1] if pack_ids else "x"
            new_name = f"{name}__{tag}"
            fm = dict(fm)
            fm["name"] = new_name
            fm["id"] = f"{site_or_chain}::{new_name}"
            fm["grader_id"] = f"{fm['id']}::grader"
            stats["conflict_suffixed"] += 1
            print(
                f"WARN: name conflict at {site_or_chain}::{name} across packs "
                f"{sorted(set((seen[key].get('pack_ids') or [])) | set(fm.get('pack_ids') or []))} "
                f"-- renamed second to {new_name}; pack authors should namespace",
                file=sys.stderr,
            )
            final.append(fm)
        else:
            seen[key] = fm
            final.append(fm)

    return sorted(final, key=_canonical_sort_key), stats


def _load_shard(path: Path) -> list[dict[str, Any]]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RuntimeError(f"{path}: YAML parse error: {e}") from e
    if doc is None:
        return []
    if not isinstance(doc, dict):
        raise RuntimeError(f"{path}: top level must be a mapping")
    fms = doc.get("failure_modes") or []
    if not isinstance(fms, list):
        raise RuntimeError(f"{path}: failure_modes must be a list")
    return [fm for fm in fms if isinstance(fm, dict)]


def _write_shard(path: Path, failure_modes: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump({"failure_modes": failure_modes},
                          sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic dedup over failure_modes/ shards (step 4.6).",
    )
    ap.add_argument("evals_dir", help="Path to the tessary-evals/ directory.")
    args = ap.parse_args()

    evals_dir = Path(args.evals_dir).resolve()
    fms_dir = evals_dir / "pipeline" / "failure_modes"
    if not fms_dir.is_dir():
        print(f"dedup.py: {fms_dir} not found", file=sys.stderr)
        return 2

    shards = sorted(fms_dir.glob("*.yaml"))
    if not shards:
        print(f"dedup.py: no failure_mode shards under {fms_dir}", file=sys.stderr)
        return 2

    # Load all shards; remember which shard each failure came from so we can
    # write back per-shard rather than to one mega-file. After dedup, each
    # surviving failure is routed to its shard via (scope, site_or_chain).
    all_failures: list[dict[str, Any]] = []
    raw_count = 0
    try:
        for shard in shards:
            fms = _load_shard(shard)
            raw_count += len(fms)
            all_failures.extend(fms)
    except RuntimeError as e:
        print(f"dedup.py: {e}", file=sys.stderr)
        return 1

    pack_ids_seen: set[str] = set()
    for fm in all_failures:
        for pid in fm.get("pack_ids") or []:
            if isinstance(pid, str):
                pack_ids_seen.add(pid)

    canonical, stats = dedup(all_failures)

    # Route survivors back to their shards: single_call -> per-site shard;
    # chain -> _chains.yaml.
    routed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fm in canonical:
        scope = fm.get("scope")
        if scope == "single_call":
            site = fm.get("call_site_id") or ""
            shard_name = f"{pipeline_io.id_safe(site)}.yaml"
        else:
            shard_name = "_chains.yaml"
        routed[shard_name].append(fm)

    # Overwrite every existing shard (even those that become empty).
    existing_shard_names = {s.name for s in shards}
    target_names = existing_shard_names | set(routed.keys())
    for shard_name in target_names:
        _write_shard(fms_dir / shard_name, routed.get(shard_name, []))

    pack_summary = ", ".join(sorted(pack_ids_seen)) or "(none)"
    print(
        f"Step 4.6: dedup -- {raw_count} raw failures -> {len(canonical)} canonical "
        f"({stats['exact_merged']} exact-merged, {stats['semantic_merged']} semantic-merged, "
        f"{stats['conflict_suffixed']} conflict-suffixed); packs contributing: [{pack_summary}]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
