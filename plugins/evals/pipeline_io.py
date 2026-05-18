#!/usr/bin/env python3
"""
pipeline_io.py — read/write shards under `evals/pipeline/`.

The v0.4 layout splits what was a single `evals/pipeline.yaml` into one shard
per logical artifact. This module is the single place that knows the on-disk
layout. Consumers (`validate.py`, `viewer.py`, `dedup.py`, `audit.py`,
`finalize.py`) read shards through `load_pipeline()`, which returns the
v0.3-compatible top-level mapping so existing logic stays unchanged.

Shard paths under `evals/pipeline/`:
    meta.yaml                       -> version, product_hint, runtime
    packs.yaml                      -> packs[]
    product_profile.yaml            -> product_profile
    invariants.yaml                 -> implicit_invariants, invariant_coverage
    chains.yaml                     -> chains[]
    taxonomy.yaml                   -> taxonomy[]
    call_sites/<id_safe>.yaml       -> one call_site mapping per file
    failure_modes/<id_safe>.yaml    -> {failure_modes: [...]} per call site
    failure_modes/_chains.yaml      -> {failure_modes: [...]} for chain scope
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except ImportError:
    print("pipeline_io: requires PyYAML. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# Filenames substitute `::` -> `__`. Mirrors the grader-filename convention.
def id_safe(ident: str) -> str:
    return ident.replace("::", "__")


def pipeline_dir(evals_dir: Path) -> Path:
    return evals_dir / "pipeline"


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RuntimeError(f"YAML parse error in {path}: {e}") from e


def _expect_mapping(value: Any, path: Path) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{path}: expected a YAML mapping at the top level")
    return value


def _expect_list(value: Any, key: str, path: Path) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"{path}: {key!r} must be a list")
    return value


def load_pipeline(evals_dir: Path) -> dict[str, Any]:
    """Assemble the v0.3-compatible pipeline mapping from shards under evals/pipeline/.

    Missing shards are tolerated (treated as empty). Malformed YAML or wrong
    top-level shape raises RuntimeError so the caller can surface a clean error.
    """
    p = pipeline_dir(evals_dir)
    out: dict[str, Any] = {
        "version": None,
        "product_hint": None,
        "packs": [],
        "product_profile": None,
        "implicit_invariants": [],
        "invariant_coverage": [],
        "runtime": {},
        "call_sites": [],
        "chains": [],
        "failure_modes": [],
        "taxonomy": [],
    }

    meta = _expect_mapping(_load_yaml(p / "meta.yaml"), p / "meta.yaml")
    if meta:
        out["version"] = meta.get("version")
        out["product_hint"] = meta.get("product_hint")
        runtime = meta.get("runtime")
        out["runtime"] = runtime if isinstance(runtime, dict) else {}

    packs_doc = _expect_mapping(_load_yaml(p / "packs.yaml"), p / "packs.yaml")
    out["packs"] = _expect_list(packs_doc.get("packs"), "packs", p / "packs.yaml")

    profile_doc = _expect_mapping(
        _load_yaml(p / "product_profile.yaml"), p / "product_profile.yaml"
    )
    out["product_profile"] = profile_doc.get("product_profile")

    invariants_doc = _expect_mapping(
        _load_yaml(p / "invariants.yaml"), p / "invariants.yaml"
    )
    out["implicit_invariants"] = _expect_list(
        invariants_doc.get("implicit_invariants"), "implicit_invariants",
        p / "invariants.yaml",
    )
    out["invariant_coverage"] = _expect_list(
        invariants_doc.get("invariant_coverage"), "invariant_coverage",
        p / "invariants.yaml",
    )

    chains_doc = _expect_mapping(_load_yaml(p / "chains.yaml"), p / "chains.yaml")
    out["chains"] = _expect_list(chains_doc.get("chains"), "chains", p / "chains.yaml")

    taxonomy_doc = _expect_mapping(_load_yaml(p / "taxonomy.yaml"), p / "taxonomy.yaml")
    out["taxonomy"] = _expect_list(
        taxonomy_doc.get("taxonomy"), "taxonomy", p / "taxonomy.yaml"
    )

    # Call sites: one file per site.
    sites_dir = p / "call_sites"
    if sites_dir.is_dir():
        for site_path in sorted(sites_dir.glob("*.yaml")):
            site = _expect_mapping(_load_yaml(site_path), site_path)
            if site:
                out["call_sites"].append(site)

    # Failure modes: one file per call site + one `_chains.yaml` for chain scope.
    fms_dir = p / "failure_modes"
    if fms_dir.is_dir():
        for fm_path in sorted(fms_dir.glob("*.yaml")):
            fm_doc = _expect_mapping(_load_yaml(fm_path), fm_path)
            shard = _expect_list(fm_doc.get("failure_modes"), "failure_modes", fm_path)
            out["failure_modes"].extend(shard)

    return out


# ---------------------------------------------------------------------------
# Writers — used by subagents and the finalize/dedup scripts. Each writer is
# self-contained and creates parent dirs as needed.
# ---------------------------------------------------------------------------

def _dump(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(dict(doc), sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def write_meta(evals_dir: Path, version: str, product_hint: str | None,
               runtime: Mapping[str, Any]) -> Path:
    path = pipeline_dir(evals_dir) / "meta.yaml"
    _dump(path, {"version": version, "product_hint": product_hint, "runtime": dict(runtime)})
    return path


def write_packs(evals_dir: Path, packs: list[Mapping[str, Any]]) -> Path:
    path = pipeline_dir(evals_dir) / "packs.yaml"
    _dump(path, {"packs": list(packs)})
    return path


def write_product_profile(evals_dir: Path, profile: Mapping[str, Any]) -> Path:
    path = pipeline_dir(evals_dir) / "product_profile.yaml"
    _dump(path, {"product_profile": dict(profile)})
    return path


def write_invariants(evals_dir: Path,
                     implicit_invariants: list[Mapping[str, Any]],
                     invariant_coverage: list[Mapping[str, Any]]) -> Path:
    path = pipeline_dir(evals_dir) / "invariants.yaml"
    _dump(path, {
        "implicit_invariants": list(implicit_invariants),
        "invariant_coverage": list(invariant_coverage),
    })
    return path


def write_chains(evals_dir: Path, chains: list[Mapping[str, Any]]) -> Path:
    path = pipeline_dir(evals_dir) / "chains.yaml"
    _dump(path, {"chains": list(chains)})
    return path


def write_taxonomy(evals_dir: Path, taxonomy: list[Mapping[str, Any]]) -> Path:
    path = pipeline_dir(evals_dir) / "taxonomy.yaml"
    _dump(path, {"taxonomy": list(taxonomy)})
    return path


def write_call_site(evals_dir: Path, site: Mapping[str, Any]) -> Path:
    sid = site.get("id")
    if not isinstance(sid, str) or not sid:
        raise ValueError("call_site missing id")
    path = pipeline_dir(evals_dir) / "call_sites" / f"{id_safe(sid)}.yaml"
    _dump(path, dict(site))
    return path


def write_failure_modes_for_site(evals_dir: Path, call_site_id: str,
                                 failure_modes: list[Mapping[str, Any]]) -> Path:
    path = pipeline_dir(evals_dir) / "failure_modes" / f"{id_safe(call_site_id)}.yaml"
    _dump(path, {"failure_modes": list(failure_modes)})
    return path


def write_chain_failure_modes(evals_dir: Path,
                              failure_modes: list[Mapping[str, Any]]) -> Path:
    path = pipeline_dir(evals_dir) / "failure_modes" / "_chains.yaml"
    _dump(path, {"failure_modes": list(failure_modes)})
    return path


# ---------------------------------------------------------------------------
# Shard discovery (used by lock + validate).
# ---------------------------------------------------------------------------

def iter_shard_paths(evals_dir: Path) -> list[Path]:
    """All shard files under evals/pipeline/, in stable sorted order."""
    p = pipeline_dir(evals_dir)
    if not p.is_dir():
        return []
    return sorted([f for f in p.rglob("*.yaml") if f.is_file()])
