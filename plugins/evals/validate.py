#!/usr/bin/env python3
"""
validate.py — authoritative validator for synthesize-graders output.

Two modes:

    Per-file:
        python3 validate.py .tessary/graders/<file>.yaml
        python3 validate.py .tessary/graders/<file>.yaml --pipeline .tessary/

    Bundle (v0.4 — recommended at step 7):
        python3 validate.py --bundle .tessary/

    Bundle + pack filter:
        python3 validate.py --bundle .tessary/ --pack security

In v0.4 the pipeline is sharded under .tessary/pipeline/*.yaml; the validator
assembles a v0.3-compatible logical mapping via pipeline_io.load_pipeline()
and runs every check unchanged against that mapping. Passing a directory to
--pipeline (per-file mode) also routes through the shard loader.

Per-file mode enforces the rules defined in `contract/AUTHORING_CONTRACT.md` and
`contract/grader.schema.json`. Bundle mode runs every per-file check across the
whole directory plus global checks: FM↔grader bijection, chain DAG acyclicity,
duplicate IDs, orphan / unreachable taxonomy nodes, layer-A/B/C coverage gates,
pack ID resolution, dedup uniqueness, and `_meta` provenance shape.

The --pack <id> filter narrows the bundle to failures / graders that carry the
named pack_id and prints a compliance-tag coverage matrix.

Optional held-out human-labelled calibration set:
    python3 validate.py --bundle .tessary/ --calibration-set human_labels.csv

The CSV has columns `grader_id, sample_output, verdict` (verdict ∈ pass|fail|not_applicable).
The validator reports per-grader agreement against the rubric (informational; does not gate exit code).

Exit codes:
    0  — valid, or accepted-broken (a top-level `_validation_error:` key
         short-circuits all rules on that file)
    1  — invalid (errors printed to stderr, one per line)
    2  — usage / I/O error
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Final, Literal, Mapping, Sequence

try:
    import yaml
except ImportError:
    print("validate.py: requires PyYAML. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# Local import — pipeline_io ships in the same plugin dir as this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_io  # noqa: E402


# ----------------------------------------------------------------------------
# Constants — frozen so they can't be mutated by callers importing this module.
# ----------------------------------------------------------------------------

VALID_KINDS: Final[frozenset[str]] = frozenset({"llm_judge", "deterministic", "execution", "score", "agentic"})
FAILURE_KINDS: Final[frozenset[str]] = frozenset({"llm_judge", "deterministic", "execution", "agentic"})
VALID_SCOPES: Final[frozenset[str]] = frozenset({"single_call", "chain", "trace"})
# scope=trace anchors to a single call site (like single_call); only the self-test input shape differs.
CALL_SITE_SCOPES: Final[frozenset[str]] = frozenset({"single_call", "trace"})
VALID_VERDICTS: Final[frozenset[str]] = frozenset({"pass", "fail", "not_applicable"})
VALID_CONFIDENCE: Final[frozenset[str]] = frozenset({"high", "medium", "low"})
VALID_SELF_TEST_CATEGORIES: Final[frozenset[str]] = frozenset({
    "clear_pass", "clear_fail", "near_miss", "adversarial", "not_applicable",
    "clear_high", "clear_low",
})
VALID_LAYERS: Final[frozenset[str]] = frozenset({"A", "B", "C"})

# Failure-catching graders require these; score graders use a different set (below).
REQUIRED_SCALAR_FIELDS: Final[tuple[str, ...]] = (
    "id", "scope", "failure_mode_id", "name", "kind",
    "confidence", "rationale", "taxonomy_node_id",
)
REQUIRED_SCALAR_FIELDS_SCORE: Final[tuple[str, ...]] = (
    "id", "scope", "quality_dimension_id", "name", "kind",
    "confidence", "rationale",
)

# Step 4.6 coverage gates the bundle mode enforces deterministically.
MIN_LAYER_A_PER_SITE: Final[int] = 3
MIN_LAYER_B_PER_SITE: Final[int] = 5
MIN_LAYER_C_PER_SITE: Final[int] = 3  # exempt for embedding shapes (handled separately)
MIN_CHAIN_FAILURES: Final[int] = 3
ADVERSARIAL_REQUIRED_AT_SELF_TESTS_COUNT: Final[int] = 4

Scope = Literal["single_call", "chain"]
Grader = Mapping[str, Any]
Pipeline = Mapping[str, Any]


# ----------------------------------------------------------------------------
# Small predicates — pure, single-purpose.
# ----------------------------------------------------------------------------

def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _normalize_applies_when(value: Any) -> str | None:
    """Empty string is treated as null per contract."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value if isinstance(value, str) else None


# ----------------------------------------------------------------------------
# Per-rule checks. Each returns a list of error strings; callers concatenate.
# ----------------------------------------------------------------------------

def _check_required_fields(g: Grader) -> list[str]:
    return [
        f"missing or empty required field: {key}"
        for key in REQUIRED_SCALAR_FIELDS
        if not _is_nonempty_str(g.get(key))
    ]


def _check_enums(g: Grader) -> list[str]:
    errors: list[str] = []
    if g.get("scope") not in VALID_SCOPES:
        errors.append(f"scope must be one of {sorted(VALID_SCOPES)}; got {g.get('scope')!r}")
    if g.get("kind") not in VALID_KINDS:
        errors.append(f"kind must be one of {sorted(VALID_KINDS)}; got {g.get('kind')!r}")
    if g.get("confidence") not in VALID_CONFIDENCE:
        errors.append(f"confidence must be one of {sorted(VALID_CONFIDENCE)}; "
                      f"got {g.get('confidence')!r}")
    return errors


def _check_scope_routing(g: Grader, scope: str | None) -> list[str]:
    errors: list[str] = []
    if scope in CALL_SITE_SCOPES:
        if not _is_nonempty_str(g.get("call_site_id")):
            errors.append(f"scope={scope} requires non-empty call_site_id")
        if g.get("chain_id") not in (None, ""):
            errors.append(f"scope={scope} must not set chain_id")
    elif scope == "chain":
        if not _is_nonempty_str(g.get("chain_id")):
            errors.append("scope=chain requires non-empty chain_id")
        if g.get("call_site_id") not in (None, ""):
            errors.append("scope=chain must not set call_site_id (implied by chain_id)")
    return errors


def _check_kind_body(g: Grader, kind: str | None) -> list[str]:
    errors: list[str] = []
    if kind == "llm_judge":
        if not _is_nonempty_str(g.get("judge_prompt")):
            errors.append("kind=llm_judge requires non-empty judge_prompt")
        if not _is_nonempty_str(g.get("rubric")):
            errors.append("kind=llm_judge requires non-empty rubric")
    elif kind == "deterministic":
        if not _is_nonempty_str(g.get("deterministic_check")):
            errors.append("kind=deterministic requires non-empty deterministic_check")
    elif kind == "execution":
        if not _is_nonempty_str(g.get("execution_spec")):
            errors.append("kind=execution requires non-empty execution_spec")
    elif kind == "agentic":
        errors += _check_agentic_body(g)
    return errors


def _check_agentic_body(g: Grader) -> list[str]:
    """kind=agentic carries an agent_spec the runner executes (sandbox + opencode).
    The plugin only validates the spec's shape — it never runs it."""
    errors: list[str] = []
    spec = g.get("agent_spec")
    if not isinstance(spec, dict) or not spec:
        errors.append("kind=agentic requires a non-empty agent_spec mapping")
        return errors
    if spec.get("harness") != "opencode":
        errors.append(f"agent_spec.harness must be 'opencode', got {spec.get('harness')!r}")
    sandbox = spec.get("sandbox")
    if not isinstance(sandbox, dict) or not _is_nonempty_str(sandbox.get("image")):
        errors.append("agent_spec.sandbox must be a mapping with a non-empty image")
    if not _is_nonempty_str(spec.get("task_prompt")):
        errors.append("agent_spec.task_prompt must be a non-empty string")
    if not _is_nonempty_str(spec.get("verdict_contract")):
        errors.append("agent_spec.verdict_contract must be a non-empty string")
    tools = spec.get("allowed_tools")
    if tools is not None and not isinstance(tools, list):
        errors.append("agent_spec.allowed_tools must be a list when present")
    return errors


def _check_applies_when(g: Grader, kind: str | None) -> list[str]:
    """applies_when is free-form and ALWAYS LLM-evaluated at runtime (v6). For a
    deterministic grader the platform runs a separate LLM applicability gate before
    the gate-free deterministic_check; there is no code-evaluable mirror to author."""
    errors: list[str] = []
    raw = g.get("applies_when")
    if raw is not None and not isinstance(raw, str):
        errors.append("applies_when must be a string or null")

    # applies_when_check was removed in v6 (the gate is never compiled). validate.py
    # flags it as an error so authors drop it; the JSON schema still tolerates the key
    # structurally (deprecated) and the platform ignores it, so legacy files don't crash.
    if _normalize_applies_when(g.get("applies_when_check")):
        errors.append("applies_when_check was removed in v6 — applies_when is now always "
                      "evaluated by an LLM, so the deterministic body is gate-free. Drop applies_when_check.")
    return errors


def _check_pass_rate(g: Grader) -> list[str]:
    errors: list[str] = []
    for field in ("self_test_pass_rate", "self_test_variance"):
        rate = g.get(field)
        if rate is None:
            continue
        if not isinstance(rate, (int, float)) or isinstance(rate, bool):
            errors.append(f"{field} must be a number in [0, 1] or null")
            continue
        if not (0.0 <= float(rate) <= 1.0):
            errors.append(f"{field} must be in [0, 1]; got {rate}")
    return errors


def _check_self_tests(
    self_tests: Sequence[Any],
    scope: str | None,
) -> tuple[set[str], set[str], list[str]]:
    """Returns (verdicts_seen, categories_seen, errors)."""
    errors: list[str] = []
    verdicts_seen: set[str] = set()
    categories_seen: set[str] = set()

    for i, st in enumerate(self_tests):
        if not isinstance(st, dict):
            errors.append(f"self_tests[{i}] must be a mapping")
            continue

        verdict = st.get("expected_verdict")
        if verdict not in VALID_VERDICTS:
            errors.append(f"self_tests[{i}].expected_verdict must be one of "
                          f"{sorted(VALID_VERDICTS)}; got {verdict!r}")
        else:
            verdicts_seen.add(verdict)

        if not _is_nonempty_str(st.get("rationale")):
            errors.append(f"self_tests[{i}].rationale must be a non-empty string")

        category = st.get("category")
        if category is not None:
            if category not in VALID_SELF_TEST_CATEGORIES:
                errors.append(f"self_tests[{i}].category must be one of "
                              f"{sorted(VALID_SELF_TEST_CATEGORIES)}; got {category!r}")
            else:
                categories_seen.add(category)

        errors.extend(_check_self_test_body(st, scope, i))

    return verdicts_seen, categories_seen, errors


def _check_self_test_body(st: Mapping[str, Any], scope: str | None, i: int) -> list[str]:
    """Per-entry shape: single_call uses sample_output; chain uses call_site_outputs;
    trace uses input_messages (prior n-1 turns) + final_output (the graded turn)."""
    errors: list[str] = []
    if scope == "single_call":
        if "call_site_outputs" in st:
            errors.append(f"self_tests[{i}]: scope=single_call must use "
                          f"sample_output, not call_site_outputs")
        if not _is_nonempty_str(st.get("sample_output")):
            errors.append(f"self_tests[{i}].sample_output must be a non-empty string")
    elif scope == "chain":
        if "sample_output" in st:
            errors.append(f"self_tests[{i}]: scope=chain must use "
                          f"call_site_outputs, not sample_output")
        cso = st.get("call_site_outputs")
        if not isinstance(cso, dict) or not cso:
            errors.append(f"self_tests[{i}].call_site_outputs must be a non-empty mapping")
        else:
            for k, v in cso.items():
                if not _is_nonempty_str(v):
                    errors.append(f"self_tests[{i}].call_site_outputs[{k!r}] "
                                  f"must be a non-empty string")
    elif scope == "trace":
        for forbidden in ("sample_output", "call_site_outputs"):
            if forbidden in st:
                errors.append(f"self_tests[{i}]: scope=trace must use "
                              f"input_messages + final_output, not {forbidden}")
        msgs = st.get("input_messages")
        if not isinstance(msgs, list) or not msgs:
            errors.append(f"self_tests[{i}].input_messages must be a non-empty list "
                          f"(the prior n-1 conversation turns)")
        else:
            for j, m in enumerate(msgs):
                if not isinstance(m, dict) or not _is_nonempty_str(m.get("role")):
                    errors.append(f"self_tests[{i}].input_messages[{j}] must be a "
                                  f"mapping with a non-empty role")
        if not _is_nonempty_str(st.get("final_output")):
            errors.append(f"self_tests[{i}].final_output must be a non-empty string "
                          f"(the final turn the grader judges)")
    return errors


def _check_verdict_consistency(
    applies_when: str | None,
    verdicts_seen: set[str],
) -> list[str]:
    """applies_when ↔ not_applicable, bidirectional."""
    errors: list[str] = []
    if applies_when and "not_applicable" not in verdicts_seen:
        errors.append("applies_when is set but no self_test has "
                      "expected_verdict: not_applicable")
    if not applies_when and "not_applicable" in verdicts_seen:
        errors.append("self_tests contain expected_verdict: not_applicable "
                      "but applies_when is null")
    return errors


def _check_pass_fail_balance(scope: str | None, verdicts_seen: set[str]) -> list[str]:
    """At least one `pass` and at least one `fail` among non-n/a verdicts.

    Evaluated independently so a malformed entry can't mask a structurally
    missing verdict. The all-n/a case is allowed.
    """
    if not (scope and verdicts_seen and verdicts_seen != {"not_applicable"}):
        return []
    non_na = verdicts_seen - {"not_applicable"}
    errors: list[str] = []
    if "pass" not in non_na:
        errors.append("self_tests must include at least one expected_verdict: pass")
    if "fail" not in non_na:
        errors.append("self_tests must include at least one expected_verdict: fail")
    return errors


def _check_adversarial_coverage(
    self_tests: Sequence[Any],
    categories_seen: set[str],
) -> list[str]:
    """When self_tests has >= 4 entries, at least one must be category: adversarial."""
    if len(self_tests) < ADVERSARIAL_REQUIRED_AT_SELF_TESTS_COUNT:
        return []
    if "adversarial" in categories_seen:
        return []
    return [f"self_tests must include at least one category: adversarial when length >= "
            f"{ADVERSARIAL_REQUIRED_AT_SELF_TESTS_COUNT}"]


def _check_id_shape(g: Grader, scope: str | None) -> list[str]:
    gid, fmid = g.get("id"), g.get("failure_mode_id")
    if not (_is_nonempty_str(gid) and _is_nonempty_str(fmid)):
        return []
    if scope in CALL_SITE_SCOPES and gid != f"{fmid}::grader":
        return [f"id should be '{fmid}::grader' for scope={scope}; got {gid!r}"]
    if scope == "chain":
        cid = g.get("chain_id")
        if _is_nonempty_str(cid) and not (gid.startswith(f"{cid}::") and gid.endswith("::grader")):
            return [f"id should match '{cid}::<failure_name>::grader' "
                    f"for scope=chain; got {gid!r}"]
    return []


def _check_meta(g: Grader) -> list[str]:
    """_meta is optional but, when present, must include required provenance fields."""
    meta = g.get("_meta")
    if meta is None:
        return []
    if not isinstance(meta, dict):
        return ["_meta must be a mapping"]
    errors: list[str] = []
    for key in ("author", "synthesized_at", "synth_inputs_digest"):
        if not _is_nonempty_str(meta.get(key)):
            errors.append(f"_meta.{key} must be a non-empty string when _meta is present")
    locked = meta.get("locked_fields")
    if locked is not None and not isinstance(locked, list):
        errors.append("_meta.locked_fields must be a list when present")
    human_edited = meta.get("human_edited")
    if human_edited is not None and not isinstance(human_edited, bool):
        errors.append("_meta.human_edited must be a boolean when present")
    return errors


def _check_pipeline_refs(
    g: Grader,
    pipeline: Pipeline,
    scope: str | None,
    self_tests: Sequence[Any],
) -> list[str]:
    """Cross-reference grader IDs against the pipeline manifest."""
    errors: list[str] = []
    fm_ids = {fm.get("id") for fm in pipeline.get("failure_modes") or []
              if isinstance(fm, dict)}
    cs_ids = {cs.get("id") for cs in pipeline.get("call_sites") or []
              if isinstance(cs, dict)}
    chains_by_id: dict[Any, Mapping[str, Any]] = {
        c.get("id"): c for c in pipeline.get("chains") or [] if isinstance(c, dict)
    }

    if g.get("kind") == "score":
        qd_ids = {qd.get("id") for qd in pipeline.get("quality_dimensions") or []
                  if isinstance(qd, dict)}
        qdid = g.get("quality_dimension_id")
        if qdid not in qd_ids:
            errors.append(f"quality_dimension_id {qdid!r} not found in "
                          f"pipeline.quality_dimensions")
    else:
        fmid = g.get("failure_mode_id")
        if fmid not in fm_ids:
            errors.append(f"failure_mode_id {fmid!r} not found in pipeline.failure_modes")

    if scope in CALL_SITE_SCOPES and g.get("call_site_id") not in cs_ids:
        errors.append(f"call_site_id {g.get('call_site_id')!r} "
                      f"not found in pipeline.call_sites")

    if scope == "chain":
        cid = g.get("chain_id")
        if cid not in chains_by_id:
            errors.append(f"chain_id {cid!r} not found in pipeline.chains")
        else:
            expected_keys = set(chains_by_id[cid].get("call_site_ids") or [])
            for i, st in enumerate(self_tests):
                cso = st.get("call_site_outputs") if isinstance(st, dict) else None
                if isinstance(cso, dict):
                    actual = set(cso.keys())
                    if actual != expected_keys:
                        errors.append(
                            f"self_tests[{i}].call_site_outputs keys {sorted(actual)} "
                            f"do not match chain.call_site_ids {sorted(expected_keys)}"
                        )
    return errors


# ----------------------------------------------------------------------------
# Top-level per-file validator.
# ----------------------------------------------------------------------------

def _score_scale(g: Grader) -> tuple[int, int] | None:
    sc = g.get("score_scale")
    if not isinstance(sc, dict):
        return None
    lo, hi = sc.get("min"), sc.get("max")
    if not isinstance(lo, int) or not isinstance(hi, int) or isinstance(lo, bool) or isinstance(hi, bool):
        return None
    return (lo, hi)


def _check_score_body(g: Grader) -> list[str]:
    errors: list[str] = []
    if not _is_nonempty_str(g.get("judge_prompt")):
        errors.append("kind=score requires non-empty judge_prompt")
    scale = _score_scale(g)
    if scale is None:
        errors.append("kind=score requires score_scale with integer min and max")
    elif scale[0] >= scale[1]:
        errors.append(f"score_scale.min ({scale[0]}) must be < max ({scale[1]})")
    rl = g.get("rubric_levels")
    if not isinstance(rl, dict) or not rl:
        errors.append("kind=score requires a non-empty rubric_levels mapping")
    elif scale is not None:
        expected = {str(n) for n in range(scale[0], scale[1] + 1)}
        got = {str(k) for k in rl}
        if got != expected:
            errors.append(f"rubric_levels keys must be {sorted(expected)}; got {sorted(got)}")
        for k, v in rl.items():
            if not _is_nonempty_str(v):
                errors.append(f"rubric_levels[{k!r}] must be a non-empty anchor description")
    return errors


def _check_score_self_tests(self_tests: Sequence[Any], scale: tuple[int, int] | None,
                            scope: str | None) -> list[str]:
    errors: list[str] = []
    categories_seen: set[str] = set()
    levels_seen: list[int] = []
    for i, st in enumerate(self_tests):
        if not isinstance(st, dict):
            errors.append(f"self_tests[{i}] must be a mapping")
            continue
        lvl = st.get("expected_level")
        if not isinstance(lvl, int) or isinstance(lvl, bool):
            errors.append(f"self_tests[{i}].expected_level must be an integer for kind=score")
        elif scale is not None and not (scale[0] <= lvl <= scale[1]):
            errors.append(f"self_tests[{i}].expected_level {lvl} out of score_scale "
                          f"[{scale[0]}, {scale[1]}]")
        else:
            levels_seen.append(lvl)
        if not _is_nonempty_str(st.get("rationale")):
            errors.append(f"self_tests[{i}].rationale must be a non-empty string")
        cat = st.get("category")
        if cat is not None and cat not in VALID_SELF_TEST_CATEGORIES:
            errors.append(f"self_tests[{i}].category must be one of "
                          f"{sorted(VALID_SELF_TEST_CATEGORIES)}; got {cat!r}")
        elif cat is not None:
            categories_seen.add(cat)
        errors += _check_self_test_body(st, scope, i)
    # Require anchored extremes + a near-miss.
    for need in ("clear_high", "clear_low", "near_miss"):
        if need not in categories_seen:
            errors.append(f"score graders must include a self_test with category: {need}")
    if len(self_tests) >= ADVERSARIAL_REQUIRED_AT_SELF_TESTS_COUNT and "adversarial" not in categories_seen:
        errors.append(f"self_tests must include a category: adversarial when length >= "
                      f"{ADVERSARIAL_REQUIRED_AT_SELF_TESTS_COUNT}")
    return errors


def _check_id_shape_score(g: Grader) -> list[str]:
    gid, qdid = g.get("id"), g.get("quality_dimension_id")
    if not (_is_nonempty_str(gid) and _is_nonempty_str(qdid)):
        return []
    if gid != f"{qdid}::grader":
        return [f"id should be '{qdid}::grader' for kind=score; got {gid!r}"]
    return []


def _validate_score_grader(g: Grader, pipeline: Pipeline | None) -> list[str]:
    errors: list[str] = []
    errors += [f"missing or empty required field: {k}"
               for k in REQUIRED_SCALAR_FIELDS_SCORE if not _is_nonempty_str(g.get(k))]
    errors += _check_enums(g)
    scope = g.get("scope") if g.get("scope") in VALID_SCOPES else None
    errors += _check_scope_routing(g, scope)
    errors += _check_score_body(g)
    errors += _check_pass_rate(g)
    errors += _check_meta(g)
    if g.get("applies_when") not in (None, ""):
        errors.append("kind=score must not set applies_when (a score grader always applies)")

    raw_tests = g.get("self_tests")
    if not isinstance(raw_tests, list) or len(raw_tests) < 3:
        got = len(raw_tests) if isinstance(raw_tests, list) else type(raw_tests).__name__
        errors.append(f"self_tests must be a list of >= 3 entries; got {got}")
        self_tests: list[Any] = raw_tests if isinstance(raw_tests, list) else []
    else:
        self_tests = list(raw_tests)
    errors += _check_score_self_tests(self_tests, _score_scale(g), scope)
    errors += _check_id_shape_score(g)
    if pipeline is not None:
        errors += _check_pipeline_refs(g, pipeline, scope, self_tests)
    return errors


def validate_grader(g: Grader, pipeline: Pipeline | None = None) -> list[str]:
    # Accepted-broken short-circuit. See contract § "Retry semantics".
    if _is_nonempty_str(g.get("_validation_error")):
        return []

    if g.get("kind") == "score":
        return _validate_score_grader(g, pipeline)

    errors: list[str] = []
    errors += _check_required_fields(g)
    errors += _check_enums(g)

    scope = g.get("scope") if g.get("scope") in VALID_SCOPES else None
    kind = g.get("kind") if g.get("kind") in VALID_KINDS else None

    errors += _check_scope_routing(g, scope)
    errors += _check_kind_body(g, kind)
    errors += _check_applies_when(g, kind)
    errors += _check_pass_rate(g)
    errors += _check_meta(g)

    raw_tests = g.get("self_tests")
    if not isinstance(raw_tests, list) or len(raw_tests) < 3:
        got = len(raw_tests) if isinstance(raw_tests, list) else type(raw_tests).__name__
        errors.append(f"self_tests must be a list of >= 3 entries; got {got}")
        self_tests: list[Any] = raw_tests if isinstance(raw_tests, list) else []
    else:
        self_tests = list(raw_tests)

    verdicts_seen, categories_seen, st_errors = _check_self_tests(self_tests, scope)
    errors += st_errors

    applies_when = _normalize_applies_when(g.get("applies_when"))
    errors += _check_verdict_consistency(applies_when, verdicts_seen)
    errors += _check_pass_fail_balance(scope, verdicts_seen)
    errors += _check_adversarial_coverage(self_tests, categories_seen)
    errors += _check_id_shape(g, scope)

    if pipeline is not None:
        errors += _check_pipeline_refs(g, pipeline, scope, self_tests)

    return errors


# ----------------------------------------------------------------------------
# Bundle-level checks. Each takes loaded data, returns list[str] of errors.
# ----------------------------------------------------------------------------

def _bundle_fm_grader_bijection(
    pipeline: Pipeline,
    graders_by_id: Mapping[str, Grader],
    partial: bool = False,
) -> list[str]:
    errors: list[str] = []
    fms = pipeline.get("failure_modes") or []
    expected_grader_ids: set[str] = set()
    for fm in fms:
        if not isinstance(fm, dict):
            continue
        if partial and fm.get("grader_deferred") is True:
            continue
        gid = fm.get("grader_id")
        if not _is_nonempty_str(gid):
            errors.append(f"failure_mode {fm.get('id')!r} is missing grader_id")
            continue
        expected_grader_ids.add(gid)

    # Only failure-catching graders participate in the FM bijection; score
    # graders are matched against quality dimensions separately.
    actual = {gid for gid, g in graders_by_id.items() if g.get("kind") != "score"}
    missing = expected_grader_ids - actual
    orphan = actual - expected_grader_ids
    for gid in sorted(missing):
        errors.append(f"pipeline references grader_id {gid!r} but no grader file exists")
    for gid in sorted(orphan):
        errors.append(f"grader file {gid!r} has no matching failure_mode.grader_id in pipeline")
    return errors


def _bundle_qd_grader_bijection(
    pipeline: Pipeline,
    graders_by_id: Mapping[str, Grader],
) -> list[str]:
    """Quality dimensions <-> score graders. Quality dimensions are always graded
    in the first sweep (never deferred), so this is enforced in full and partial mode."""
    errors: list[str] = []
    expected: set[str] = set()
    for qd in pipeline.get("quality_dimensions") or []:
        if not isinstance(qd, dict):
            continue
        gid = qd.get("grader_id")
        if not _is_nonempty_str(gid):
            errors.append(f"quality_dimension {qd.get('id')!r} is missing grader_id")
            continue
        expected.add(gid)
    actual = {gid for gid, g in graders_by_id.items() if g.get("kind") == "score"}
    for gid in sorted(expected - actual):
        errors.append(f"quality_dimension references grader_id {gid!r} but no score "
                      f"grader file exists")
    for gid in sorted(actual - expected):
        errors.append(f"score grader {gid!r} has no matching "
                      f"quality_dimension.grader_id in pipeline")
    return errors


# Shapes whose output involves judgment — must carry >= 1 quality dimension.
JUDGMENT_SHAPES: Final[frozenset[str]] = frozenset({
    "agent_step", "route", "rag_answer", "classify", "draft", "rerank",
    "summarize", "conversational_turn",
})

# How the model is reached (call-site `invocation`); absent means in-process SDK.
VALID_INVOCATIONS: Final[frozenset[str]] = frozenset({
    "sdk", "cli_agent", "http", "sandbox_agent",
})

# How a call site's turns are grouped for grading (call-site `default_grade_mode`,
# schema 0.11.0); absent means per_turn.
VALID_GRADE_MODES: Final[frozenset[str]] = frozenset({
    "per_turn", "per_conversation",
})


def _bundle_invocation_enum(pipeline: Pipeline) -> list[str]:
    """If a call site declares `invocation`, it must be a known kind.

    Absent is allowed and treated as `sdk` (the only value pre-0.9.0)."""
    errors: list[str] = []
    for cs in pipeline.get("call_sites") or []:
        if not isinstance(cs, dict):
            continue
        inv = cs.get("invocation")
        if inv is not None and inv not in VALID_INVOCATIONS:
            errors.append(f"call_site {cs.get('id')!r} has invalid invocation "
                          f"{inv!r}; expected one of {sorted(VALID_INVOCATIONS)}")
    return errors


def _bundle_grade_mode_enum(pipeline: Pipeline) -> list[str]:
    """If a call site declares `default_grade_mode`, it must be a known value.

    Absent is allowed and treated as `per_turn` (the pre-0.11.0 behavior).
    `per_conversation` marks a multi-turn site whose graders should be `scope: trace`."""
    errors: list[str] = []
    for cs in pipeline.get("call_sites") or []:
        if not isinstance(cs, dict):
            continue
        mode = cs.get("default_grade_mode")
        if mode is not None and mode not in VALID_GRADE_MODES:
            errors.append(f"call_site {cs.get('id')!r} has invalid default_grade_mode "
                          f"{mode!r}; expected one of {sorted(VALID_GRADE_MODES)}")
    return errors


def _bundle_quality_coverage(pipeline: Pipeline) -> list[str]:
    """Every judgment-shape call site must have at least one quality dimension.

    This is the never-skipped guarantee: the gap the synthesizer used to leave
    (no quality/grey-area evals at all) is now a hard error."""
    errors: list[str] = []
    qd_sites = {qd.get("call_site_id") for qd in pipeline.get("quality_dimensions") or []
                if isinstance(qd, dict)}
    for cs in pipeline.get("call_sites") or []:
        if not isinstance(cs, dict):
            continue
        if cs.get("shape") in JUDGMENT_SHAPES and cs.get("id") not in qd_sites:
            errors.append(f"call_site {cs.get('id')!r} (shape={cs.get('shape')!r}) has no "
                          f"quality dimensions — judgment call sites must be scored on "
                          f"at least one quality axis")
    return errors


def _bundle_duplicate_ids(graders: Sequence[tuple[Path, Grader]]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for path, g in graders:
        gid = g.get("id")
        if not _is_nonempty_str(gid):
            continue
        if gid in seen:
            errors.append(f"duplicate grader id {gid!r}: {seen[gid]} and {path}")
        else:
            seen[gid] = path
    return errors


def _bundle_taxonomy_reachability(pipeline: Pipeline) -> list[str]:
    errors: list[str] = []
    tax = pipeline.get("taxonomy") or []
    tax_ids = {t.get("id") for t in tax if isinstance(t, dict) and _is_nonempty_str(t.get("id"))}
    fm_node_ids: set[str] = set()
    fms = pipeline.get("failure_modes") or []
    for fm in fms:
        if not isinstance(fm, dict):
            continue
        node = fm.get("taxonomy_node_id")
        if _is_nonempty_str(node):
            fm_node_ids.add(node)
            if node not in tax_ids:
                errors.append(f"failure_mode {fm.get('id')!r} references "
                              f"unknown taxonomy_node_id {node!r}")
    orphan_nodes = tax_ids - fm_node_ids - {None}
    # Parent nodes are allowed to be empty if children exist; check that
    parent_ids = {t.get("parent_id") for t in tax if isinstance(t, dict)}
    truly_orphan = {n for n in orphan_nodes if n not in parent_ids}
    for node in sorted(truly_orphan):
        errors.append(f"taxonomy node {node!r} has no failure_modes and no children — "
                      f"either populate or remove")
    return errors


def _bundle_chain_acyclic(pipeline: Pipeline) -> list[str]:
    """Detect cycles in chain.call_site_ids ordering across chains.

    A chain that lists [A, B, A] is a cycle within itself. A pair of chains
    where chain1=[A,B] and chain2=[B,A] is a cross-chain cycle when one
    chain's last call site appears before the first call site of another
    chain that loops back.
    """
    errors: list[str] = []
    chains = pipeline.get("chains") or []

    # Internal cycle check
    for c in chains:
        if not isinstance(c, dict):
            continue
        sites = c.get("call_site_ids") or []
        if len(sites) != len(set(sites)):
            counts = Counter(sites)
            # ensemble is allowed to repeat the same id; differentiate by detection_method
            if c.get("detection_method") != "ensemble":
                dupes = [s for s, n in counts.items() if n > 1]
                errors.append(f"chain {c.get('id')!r} repeats call_site_ids {dupes!r} "
                              f"without detection_method=ensemble")

    # Cross-chain DAG check
    graph: dict[str, set[str]] = defaultdict(set)
    for c in chains:
        if not isinstance(c, dict):
            continue
        sites = c.get("call_site_ids") or []
        for a, b in zip(sites, sites[1:]):
            graph[a].add(b)

    # Tarjan-lite cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(lambda: WHITE)

    def visit(node: str, path: list[str]) -> str | None:
        if color[node] == GRAY:
            cycle_start = path.index(node)
            return " -> ".join(path[cycle_start:] + [node])
        if color[node] == BLACK:
            return None
        color[node] = GRAY
        path.append(node)
        for nxt in graph.get(node, ()):
            found = visit(nxt, path)
            if found:
                return found
        path.pop()
        color[node] = BLACK
        return None

    for start in list(graph.keys()):
        if color[start] == WHITE:
            cycle = visit(start, [])
            if cycle:
                errors.append(f"chains contain a cycle: {cycle}")
                break
    return errors


def _bundle_pack_resolution(pipeline: Pipeline, graders: Sequence[tuple[Path, Grader]]) -> list[str]:
    """Every pack_id on a failure mode or grader must resolve to pipeline.packs[].id."""
    errors: list[str] = []
    declared = {p.get("id") for p in pipeline.get("packs") or [] if isinstance(p, dict)}
    declared.discard(None)
    for fm in pipeline.get("failure_modes") or []:
        if not isinstance(fm, dict):
            continue
        for pid in fm.get("pack_ids") or []:
            if pid not in declared:
                errors.append(f"failure_mode {fm.get('id')!r} carries pack_id "
                              f"{pid!r} not in pipeline.packs[]")
    for path, g in graders:
        for pid in g.get("pack_ids") or []:
            if pid not in declared:
                errors.append(f"{path}: pack_id {pid!r} not in pipeline.packs[]")
    return errors


def _bundle_dedup_uniqueness(pipeline: Pipeline) -> list[str]:
    """After step 4.6 dedup, no two failures may share (scope, call_site|chain, name)."""
    errors: list[str] = []
    seen: dict[tuple[str, str, str], str] = {}
    for fm in pipeline.get("failure_modes") or []:
        if not isinstance(fm, dict):
            continue
        scope = fm.get("scope") or ""
        site_or_chain = fm.get("call_site_id") if scope == "single_call" else fm.get("chain_id")
        if not _is_nonempty_str(site_or_chain):
            continue
        name = fm.get("name") or ""
        key = (scope, site_or_chain, name)
        if key in seen:
            errors.append(f"dedup invariant violated: failure_modes {seen[key]!r} and "
                          f"{fm.get('id')!r} share ({scope}, {site_or_chain}, {name}) — "
                          f"step 4.6 should have merged or conflict-suffixed")
        else:
            seen[key] = fm.get("id") or ""
    return errors


def _bundle_pack_dependencies(pipeline: Pipeline) -> list[str]:
    """Pack dependencies satisfied; conflicts not co-engaged.

    Reads pack manifests from the live pack registry if available; otherwise
    relies on dependency/conflict lists embedded in pipeline.packs[] entries
    (which the orchestrator records at step 0.5).
    """
    errors: list[str] = []
    packs = pipeline.get("packs") or []
    declared = {p.get("id") for p in packs if isinstance(p, dict)}
    for p in packs:
        if not isinstance(p, dict):
            continue
        pid = p.get("id") or ""
        for dep in p.get("dependencies") or []:
            if dep not in declared:
                errors.append(f"pack {pid!r} declares dependency on {dep!r} "
                              f"but that pack is not engaged")
        for conf in p.get("conflicts") or []:
            if conf in declared:
                errors.append(f"pack {pid!r} declares conflict with {conf!r} "
                              f"but both are engaged")
    return errors


def _bundle_coverage_gates(pipeline: Pipeline) -> list[str]:
    """Enforce step 4.6 gates per call site / chain."""
    errors: list[str] = []
    call_sites = {cs.get("id"): cs for cs in pipeline.get("call_sites") or []
                  if isinstance(cs, dict)}
    chains = {c.get("id"): c for c in pipeline.get("chains") or [] if isinstance(c, dict)}
    fms = pipeline.get("failure_modes") or []

    per_site_layer: dict[str, Counter[str]] = defaultdict(Counter)
    per_chain_count: Counter[str] = Counter()
    for fm in fms:
        if not isinstance(fm, dict):
            continue
        scope = fm.get("scope")
        layer = fm.get("layer")
        if scope == "single_call":
            site = fm.get("call_site_id")
            if site:
                per_site_layer[site][layer or "?"] += 1
        elif scope == "chain":
            cid = fm.get("chain_id")
            if cid:
                per_chain_count[cid] += 1

    for site_id, cs in call_sites.items():
        layers = per_site_layer.get(site_id, Counter())
        shape = cs.get("shape")
        if layers["A"] < MIN_LAYER_A_PER_SITE and shape != "embedding":
            errors.append(f"call_site {site_id!r} has {layers['A']} Layer A failures; "
                          f"step 4.6 requires >= {MIN_LAYER_A_PER_SITE}")
        if layers["B"] < MIN_LAYER_B_PER_SITE and shape not in ("embedding",):
            errors.append(f"call_site {site_id!r} has {layers['B']} Layer B failures; "
                          f"step 4.6 requires >= {MIN_LAYER_B_PER_SITE}")
        if layers["C"] < MIN_LAYER_C_PER_SITE and shape != "embedding":
            errors.append(f"call_site {site_id!r} has {layers['C']} Layer C failures; "
                          f"step 4.6 requires >= {MIN_LAYER_C_PER_SITE}")

    for cid in chains:
        if per_chain_count[cid] < MIN_CHAIN_FAILURES:
            errors.append(f"chain {cid!r} has {per_chain_count[cid]} cross-call failures; "
                          f"step 4.6 requires >= {MIN_CHAIN_FAILURES}")
    return errors


# ----------------------------------------------------------------------------
# Lock file + calibration-set helpers.
# ----------------------------------------------------------------------------

def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_lock_consistency(evals_dir: Path, lock: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    locked_graders = lock.get("graders") or {}
    graders_dir = evals_dir / "graders"
    if not isinstance(locked_graders, dict):
        return [".tessary/.synth-lock.yaml graders: must be a mapping"]
    for safe_id, expected_hash in locked_graders.items():
        path = graders_dir / f"{safe_id}.yaml"
        if not path.is_file():
            errors.append(f".synth-lock.yaml references {safe_id}.yaml but file is missing")
            continue
        actual = _sha256_hex(path.read_text(encoding="utf-8"))
        if actual != expected_hash:
            # Diverged. Only an error if locked_fields is empty AND human_edited is false.
            try:
                grader = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                grader = {}
            meta = grader.get("_meta") or {}
            locked_fields = meta.get("locked_fields") or []
            human_edited = bool(meta.get("human_edited"))
            if not locked_fields and not human_edited:
                errors.append(f"{safe_id}.yaml diverged from .synth-lock.yaml without "
                              f"_meta.locked_fields or human_edited=true — "
                              f"pass --force to overwrite, or set _meta to preserve")
    return errors


def _run_calibration_set(
    csv_path: Path,
    graders_by_id: Mapping[str, Grader],
) -> list[str]:
    """Informational: read CSV (grader_id, sample_output, verdict), compare to grader.

    This validator can't run an LLM judge; we just report per-grader counts so the
    operator can wire up their own calibration runner.
    """
    notes: list[str] = []
    if not csv_path.is_file():
        return [f"--calibration-set: file not found: {csv_path}"]
    try:
        with csv_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        return [f"--calibration-set: cannot read CSV: {e}"]
    needed = {"grader_id", "sample_output", "verdict"}
    if rows and not needed.issubset(rows[0].keys()):
        return [f"--calibration-set: CSV must have columns {sorted(needed)}; "
                f"got {sorted(rows[0].keys())}"]
    counts: Counter[tuple[str, str]] = Counter()
    for r in rows:
        gid = (r.get("grader_id") or "").strip()
        v = (r.get("verdict") or "").strip()
        if gid and v in VALID_VERDICTS:
            counts[(gid, v)] += 1
    grader_ids = sorted({gid for gid, _ in counts})
    notes.append(f"calibration-set: {len(rows)} labelled rows across {len(grader_ids)} grader(s)")
    for gid in grader_ids:
        if gid not in graders_by_id:
            notes.append(f"  - {gid}: UNKNOWN grader id (skipped)")
            continue
        breakdown = {v: counts[(gid, v)] for v in sorted(VALID_VERDICTS)}
        notes.append(f"  - {gid}: {breakdown}")
    return notes


# ----------------------------------------------------------------------------
# IO + CLI.
# ----------------------------------------------------------------------------

def _load_yaml(path: Path, label: str) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"validate.py: YAML parse error in {label} ({path}): {e}", file=sys.stderr)
        sys.exit(1 if label == "grader" else 2)


def _run_per_file(grader_path: Path, pipeline_path: Path | None) -> int:
    grader = _load_yaml(grader_path, "grader")
    if not isinstance(grader, dict):
        print(f"validate.py: {grader_path}: must be a YAML mapping at the top level",
              file=sys.stderr)
        return 1

    pipeline: Mapping[str, Any] | None = None
    if pipeline_path:
        # --pipeline accepts a .tessary/ directory (preferred) for the v0.4 sharded
        # layout, or a legacy single pipeline.yaml file.
        if pipeline_path.is_dir():
            try:
                pipeline = pipeline_io.load_pipeline(pipeline_path)
            except RuntimeError as e:
                print(f"validate.py: {e}", file=sys.stderr)
                return 1
        elif pipeline_path.is_file():
            loaded = _load_yaml(pipeline_path, "pipeline")
            if not isinstance(loaded, dict):
                print(f"validate.py: {pipeline_path}: must be a YAML mapping at the top level",
                      file=sys.stderr)
                return 1
            pipeline = loaded
        else:
            print(f"validate.py: --pipeline path not found: {pipeline_path}", file=sys.stderr)
            return 2

    errors = validate_grader(grader, pipeline)
    if errors:
        for msg in errors:
            print(f"{grader_path}: {msg}", file=sys.stderr)
        return 1
    print(f"{grader_path}: OK")
    return 0


def _pack_filter_report(
    pipeline: Pipeline,
    graders_by_id: Mapping[str, Grader],
    pack_id: str,
) -> list[str]:
    """Print a coverage matrix for one pack: which failures / graders / compliance tags."""
    declared = {p.get("id") for p in pipeline.get("packs") or [] if isinstance(p, dict)}
    if pack_id not in declared:
        return [f"pack {pack_id!r} not engaged in this pipeline (declared packs: "
                f"{sorted(x for x in declared if x)})"]
    lines = [f"--pack {pack_id}: coverage matrix"]
    layer_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    matched_grader_ids: set[str] = set()
    for fm in pipeline.get("failure_modes") or []:
        if not isinstance(fm, dict):
            continue
        if pack_id not in (fm.get("pack_ids") or []):
            continue
        layer_counter[fm.get("layer") or "?"] += 1
        for tag in fm.get("compliance_tags") or []:
            tag_counter[tag] += 1
        if _is_nonempty_str(fm.get("grader_id")):
            matched_grader_ids.add(fm["grader_id"])
    lines.append(f"  failures: {sum(layer_counter.values())} "
                 f"({dict(sorted(layer_counter.items()))})")
    lines.append(f"  graders: {len(matched_grader_ids)}")
    if tag_counter:
        lines.append(f"  compliance tags:")
        for tag, n in sorted(tag_counter.items()):
            lines.append(f"    {tag}: {n}")
    return lines


def _run_bundle(evals_dir: Path, calibration_csv: Path | None,
                pack_filter: str | None = None,
                partial: bool = False) -> int:
    if not evals_dir.is_dir():
        print(f"validate.py: --bundle path is not a directory: {evals_dir}", file=sys.stderr)
        return 2

    pipeline_root = evals_dir / "pipeline"
    if not pipeline_root.is_dir():
        print(f"validate.py: {pipeline_root}/ missing (v0.4 sharded layout)",
              file=sys.stderr)
        return 2
    try:
        pipeline = pipeline_io.load_pipeline(evals_dir)
    except RuntimeError as e:
        print(f"validate.py: {e}", file=sys.stderr)
        return 1
    if not isinstance(pipeline, dict):
        print(f"validate.py: {pipeline_root}: assembled pipeline view is not a mapping",
              file=sys.stderr)
        return 1

    graders_dir = evals_dir / "graders"
    graders: list[tuple[Path, Grader]] = []
    per_file_errors: list[str] = []
    if graders_dir.is_dir():
        for path in sorted(graders_dir.glob("*.yaml")):
            g = _load_yaml(path, "grader")
            if not isinstance(g, dict):
                per_file_errors.append(f"{path}: must be a YAML mapping at the top level")
                continue
            graders.append((path, g))
            for msg in validate_grader(g, pipeline):
                per_file_errors.append(f"{path}: {msg}")
    elif not partial:
        print(f"validate.py: {graders_dir} missing", file=sys.stderr)
        return 2

    graders_by_id: dict[str, Grader] = {
        g.get("id"): g for _, g in graders if _is_nonempty_str(g.get("id"))
    }

    bundle_errors: list[str] = []
    bundle_errors += _bundle_fm_grader_bijection(pipeline, graders_by_id, partial=partial)
    bundle_errors += _bundle_qd_grader_bijection(pipeline, graders_by_id)
    bundle_errors += _bundle_quality_coverage(pipeline)
    bundle_errors += _bundle_invocation_enum(pipeline)
    bundle_errors += _bundle_grade_mode_enum(pipeline)
    bundle_errors += _bundle_duplicate_ids(graders)
    bundle_errors += _bundle_taxonomy_reachability(pipeline)
    bundle_errors += _bundle_chain_acyclic(pipeline)
    bundle_errors += _bundle_pack_resolution(pipeline, graders)
    bundle_errors += _bundle_dedup_uniqueness(pipeline)
    bundle_errors += _bundle_pack_dependencies(pipeline)

    coverage_msgs = _bundle_coverage_gates(pipeline)
    if partial:
        bundle_warnings = list(coverage_msgs)
    else:
        bundle_errors += coverage_msgs
        bundle_warnings = []

    lock_path = evals_dir / ".synth-lock.yaml"
    if lock_path.is_file():
        lock = _load_yaml(lock_path, "lock")
        if isinstance(lock, dict):
            bundle_errors += _check_lock_consistency(evals_dir, lock)

    notes: list[str] = []
    if calibration_csv is not None:
        notes += _run_calibration_set(calibration_csv, graders_by_id)
    if pack_filter:
        notes += _pack_filter_report(pipeline, graders_by_id, pack_filter)

    print(f"bundle: {len(graders)} grader file(s) under {graders_dir}")
    for line in notes:
        print(line)
    for warn in bundle_warnings:
        print(f"warn: {warn}", file=sys.stderr)

    all_errors = per_file_errors + bundle_errors
    if all_errors:
        for msg in all_errors:
            print(msg, file=sys.stderr)
        print(f"bundle: {len(all_errors)} error(s)", file=sys.stderr)
        return 1
    if partial:
        print(f"bundle: OK (partial; {len(bundle_warnings)} coverage warning(s))")
    else:
        print("bundle: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a grader YAML or a full .tessary/ bundle.")
    ap.add_argument("file", nargs="?", help="Path to a grader YAML file (per-file mode).")
    ap.add_argument("--pipeline", help="Optional path to .tessary/ (preferred) or a legacy "
                                       "pipeline.yaml file for per-file cross-checks.")
    ap.add_argument("--bundle", help="Path to a .tessary/ directory for full-bundle validation.")
    ap.add_argument("--calibration-set", help="Optional CSV (grader_id,sample_output,verdict) for "
                                              "informational agreement reporting.")
    ap.add_argument("--pack", help="Bundle mode only — narrow output to a single pack id and "
                                   "print a compliance-tag coverage matrix.")
    ap.add_argument("--partial", action="store_true",
                    help="Bundle mode — tolerate deferred failure modes (no grader file yet) "
                         "and downgrade per-site coverage shortfalls to warnings.")
    args = ap.parse_args()

    if args.bundle:
        if args.file or args.pipeline:
            print("validate.py: --bundle is mutually exclusive with the positional file / --pipeline",
                  file=sys.stderr)
            return 2
        evals_dir = Path(args.bundle).resolve()
        cal = Path(args.calibration_set).resolve() if args.calibration_set else None
        return _run_bundle(evals_dir, cal, args.pack, partial=args.partial)
    if args.pack:
        print("validate.py: --pack is only valid with --bundle", file=sys.stderr)
        return 2

    if not args.file:
        ap.print_usage(sys.stderr)
        return 2
    grader_path = Path(args.file).resolve()
    if not grader_path.is_file():
        print(f"validate.py: not a file: {grader_path}", file=sys.stderr)
        return 2
    pipeline_path = Path(args.pipeline).resolve() if args.pipeline else None
    return _run_per_file(grader_path, pipeline_path)


if __name__ == "__main__":
    sys.exit(main())
