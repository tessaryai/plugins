#!/usr/bin/env python3
"""sop_lint.py — validator for v3 SOP-conformance files (`.tessary/sops/<call_site_id>.yaml`).

A v3 SOP is the CUSTOMER-side artifact of the platform's SOP-conformance classifier: seven
concepts — `agent`, `intents` (id → `means:`), `observations` (id → one atomic sentence, with
optional `counts:`/`counts_not:` frame exemplars), and `rules` with
`in:`/`when:`/`unless:`/`at:`/`expect:`|`never:` (optional `either:`/`of:`) — pure meaning,
zero mechanism. Everything mechanical (routing, detector synthesis, thresholds, bindings) is
compiled SERVER-SIDE by the platform; none of it ever appears in this file, and this script is
deliberately a **validator only** — it performs no compilation and produces no bindings. The
schema is specified in the evals-platform repo's `classifiers/experiments/SCHEMA-V3.md`.

Validation is COLLECT-ALL: every problem in the file comes back at once, naming its place.

Lint classes, per SCHEMA-V3's style laws:

  ERROR   structure      — missing/ill-typed concepts; a rule must carry exactly one of
                           `expect:` / `never:`; enums (`at:`, `within:`) must hold
  ERROR   atomicity      — a conjunction word (without / unless / before / after / instead of)
                           inside an observation sentence is smuggled rule structure: split the
                           condition into `when:`/`unless:`/`at:`/ordering, keep the atom (law 1)
  ERROR   unknown refs   — `when`/`unless`/`expect`/`never`/`either` must name observations;
                           `in:` must name intents (or `any`)
  ERROR   exemplar shape — `counts:`/`counts_not:` must be lists of non-empty mini-scenario
                           strings under an `is:` sentence (law 3)
  WARNING specificity    — a hedge word (properly / appropriately / correctly / …) marks a
                           judgement sentence that does not name its mechanism (law 2);
                           suppressed when the observation carries ≥2 frame exemplars, which
                           are law 3's remedy for exactly this residue
  WARNING never polarity — a `never:` target whose sentence looks compound (two act verbs
                           joined by and/or) violates law 4's atomic-act requirement
  WARNING exemplar count — frame exemplars work in 2–3 adjudicated mini-scenarios; 1 is too
                           few to carry a convention, more than 3 is a spec, not a frame

Usage:
  python3 sop_lint.py <sop.yaml> [<sop.yaml> ...]

Exit codes (contract, like platform.py's):
  0  every file parsed and linted clean (warnings allowed)
  1  at least one file has lint/validation errors
  2  usage error, unreadable file, or invalid YAML

Dependencies: Python 3 + PyYAML. Nothing else, matching platform.py's single-file packaging.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "sop_lint.py needs PyYAML (the one non-stdlib dependency): pip install pyyaml\n"
    )
    sys.exit(2)

#: Law 1's conjunction words: rule structure smuggled into an observation sentence.
CONJUNCTION_RX = re.compile(r"\b(without|unless|before|after)\b|\binstead of\b", re.IGNORECASE)
#: Law 2's hedge words: judgement without a named mechanism.
HEDGE_RX = re.compile(
    r"\b(properly|appropriately|correctly|adequately|suitably|reasonably|as needed|"
    r"in a timely manner|timely)\b",
    re.IGNORECASE,
)
#: Small act-verb lexicon for the never:-polarity heuristic (two of these joined by and/or in
#: one sentence = compound-looking). Deliberately small: false silence is fine (warning-only),
#: false noise is not.
ACT_VERBS = {
    "asks", "requests", "repeats", "states", "gives", "issues", "recommends", "advises",
    "tells", "marks", "reveals", "records", "explains", "quotes", "names", "provides",
    "summarises", "summarizes", "poses", "authorizes", "apologizes", "waives", "confirms",
    "promises", "offers", "shares", "sends", "handles",
}

AT_VALUES = ("session-start", "session-end")
WITHIN_VALUES = ("conversation", "turn")

TOP_LEVEL_KEYS = {"agent", "intents", "observations", "rules"}
RULE_KEYS = {"in", "when", "unless", "at", "expect", "never", "either", "of"}
OBS_MAPPING_KEYS = {"is", "counts", "counts_not"}


class Findings:
    """Collect-all sink; every message names its place in the file."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _exemplar_list(spec: dict, key: str, oid: str, f: Findings) -> list[str]:
    raw = spec.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(e, str) and e.strip() for e in raw):
        f.error(
            f"observation {oid}: exemplar shape — '{key}:' must be a list of non-empty "
            f"mini-scenario strings (style law 3)"
        )
        return []
    return [e.strip() for e in raw]


def _parse_observations(raw: object, f: Findings) -> dict[str, dict]:
    """Return oid -> {'is': sentence, 'counts': [...], 'counts_not': [...]}."""
    observations: dict[str, dict] = {}
    if not isinstance(raw, dict) or not raw:
        f.error("'observations' must be a non-empty mapping of id -> sentence")
        return observations
    for oid, spec in raw.items():
        if isinstance(spec, str) and spec.strip():
            observations[oid] = {"is": spec.strip(), "counts": [], "counts_not": []}
        elif isinstance(spec, dict):
            for key in spec:
                if key not in OBS_MAPPING_KEYS:
                    f.warning(f"observation {oid}: unknown key {key!r} ignored")
            sentence = spec.get("is")
            if not isinstance(sentence, str) or not sentence.strip():
                f.error(
                    f"observation {oid}: exemplar shape — the mapping form requires "
                    f"'is: \"<one atomic sentence>\"' alongside counts:/counts_not:"
                )
                continue
            counts = _exemplar_list(spec, "counts", oid, f)
            counts_not = _exemplar_list(spec, "counts_not", oid, f)
            n = len(counts) + len(counts_not)
            if n == 1 or n > 3:
                f.warning(
                    f"observation {oid}: exemplar count — {n} exemplar(s); frame exemplars "
                    f"work in 2–3 adjudicated mini-scenarios (style law 3)"
                )
            observations[oid] = {
                "is": sentence.strip(), "counts": counts, "counts_not": counts_not,
            }
        else:
            f.error(
                f"observation {oid}: the value must be one atomic sentence, or a mapping "
                f"{{is: <sentence>, counts: [...], counts_not: [...]}}"
            )
    return observations


def _lint_observations(observations: dict[str, dict], f: Findings) -> None:
    for oid, spec in observations.items():
        sentence = spec["is"]
        m = CONJUNCTION_RX.search(sentence)
        if m:
            f.error(
                f"observation {oid}: atomicity — the sentence contains {m.group(0)!r}, "
                f"which smuggles rule structure; split the condition into "
                f"when:/unless:/at:/ordering and keep the atom (style law 1)"
            )
        h = HEDGE_RX.search(sentence)
        if h and len(spec["counts"]) + len(spec["counts_not"]) < 2:
            f.warning(
                f"observation {oid}: specificity — hedge word {h.group(0)!r}; name the "
                f"mechanism the judgement rests on, or carry the convention in 2–3 "
                f"counts:/counts_not: exemplars (style laws 2–3)"
            )


def _looks_compound(sentence: str) -> bool:
    if not re.search(r"\b(and|or)\b", sentence, re.IGNORECASE):
        return False
    verbs = {w.lower() for w in re.findall(r"[A-Za-z]+", sentence)} & ACT_VERBS
    return len(verbs) >= 2


def _lint_rule(
    raw: object,
    index: int,
    observations: dict[str, dict],
    intents: dict[str, str],
    f: Findings,
) -> None:
    where = f"rules[{index}]"
    if not isinstance(raw, dict):
        f.error(f"{where}: each rule must be a mapping")
        return
    for key in raw:
        if key not in RULE_KEYS:
            f.warning(f"{where}: unknown key {key!r} ignored")

    if "in" not in raw:
        f.error(f"{where}: missing required 'in:' (owed-scope)")
    else:
        rv = raw["in"]
        scope = [rv] if isinstance(rv, str) and rv != "any" else rv
        if rv == "any":
            pass
        elif isinstance(scope, list) and scope and all(isinstance(i, str) for i in scope):
            for iid in scope:
                if iid not in intents:
                    f.error(f"{where}: unknown intent ref {iid!r} in 'in:'")
        else:
            f.error(f"{where}: 'in:' must be an intent id, a list of them, or 'any'")

    def obs_ref(key: str) -> None:
        v = raw.get(key, "")
        if not v:
            return
        if not isinstance(v, str):
            f.error(f"{where}: '{key}:' must be an observation id")
        elif v not in observations:
            f.error(f"{where}: unknown observation ref {v!r} in '{key}:'")

    obs_ref("when")
    obs_ref("unless")

    at = raw.get("at", "")
    if at and at not in AT_VALUES:
        f.error(f"{where}: 'at:' must be one of {AT_VALUES}, got {at!r}")

    if "expect" in raw:
        ev = raw["expect"]
        if isinstance(ev, str):
            if ev not in observations:
                f.error(f"{where}: unknown observation ref {ev!r} in 'expect:'")
        elif isinstance(ev, dict):
            unknown = set(ev) - {"tool", "before", "paired_by", "within"}
            if unknown:
                f.warning(f"{where}: unknown expect keys {sorted(unknown)} ignored")
            tool = ev.get("tool")
            if not isinstance(tool, str) or not tool:
                f.error(f"{where}: expect tool form requires a non-empty 'tool'")
            within = ev.get("within", "conversation")
            if within not in WITHIN_VALUES:
                f.error(f"{where}: expect 'within' must be one of {WITHIN_VALUES}, got {within!r}")
        else:
            f.error(f"{where}: 'expect:' must be an observation id or a tool mapping")

    if "never" in raw:
        nv = raw["never"]
        if isinstance(nv, str):
            if nv not in observations:
                f.error(f"{where}: unknown observation ref {nv!r} in 'never:'")
            elif _looks_compound(observations[nv]["is"]):
                # Law 4 polarity: never: requires an atomic act; a compound-looking sentence
                # should decompose into when: + a deterministic obligation. Warning-only —
                # the heuristic is a surface read.
                f.warning(
                    f"{where}: never: polarity — observation {nv!r} looks compound "
                    f"({observations[nv]['is']!r}); rare compound violations should "
                    f"decompose into when: + a deterministic obligation (style law 4)"
                )
        elif not (isinstance(nv, dict) and isinstance(nv.get("tool"), str) and nv["tool"]):
            f.error(f"{where}: 'never:' must be an observation id or {{tool: t}}")

    if ("expect" in raw) == ("never" in raw):
        f.error(f"{where}: exactly one of 'expect:' / 'never:' is required")

    either = raw.get("either", [])
    if either:
        if not isinstance(either, list) or not all(isinstance(e, str) for e in either):
            f.error(f"{where}: 'either:' must be a list of observation ids")
        else:
            for e in either:
                if e not in observations:
                    f.error(f"{where}: unknown observation ref {e!r} in 'either:'")

    of = raw.get("of", "")
    if of and not isinstance(of, str):
        f.error(f"{where}: 'of:' must be a delegate-role string")


def lint_file(path: Path) -> Findings:
    f = Findings()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        f.error("top level must be a mapping with the seven v3 concepts")
        return f

    for key in raw:
        if key not in TOP_LEVEL_KEYS:
            f.warning(f"unknown top-level key {key!r} ignored")

    agent = raw.get("agent")
    if not isinstance(agent, str) or not agent:
        f.error("missing required 'agent' (the call-site id, verbatim)")

    intents: dict[str, str] = {}
    intents_raw = raw.get("intents") or {}
    if not isinstance(intents_raw, dict):
        f.error("'intents' must be a mapping of intent id -> {means: ...}")
    else:
        for iid, spec in intents_raw.items():
            if isinstance(spec, dict) and isinstance(spec.get("means"), str) and spec["means"]:
                intents[iid] = spec["means"]
                for key in spec:
                    if key != "means":
                        f.warning(f"intent {iid}: unknown key {key!r} ignored")
            else:
                f.error(f'intent {iid}: requires {{means: "<one sentence>"}}')

    observations = _parse_observations(raw.get("observations") or {}, f)
    _lint_observations(observations, f)

    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        f.error("'rules' must be a non-empty list")
    else:
        for i, r in enumerate(rules_raw):
            _lint_rule(r, i, observations, intents, f)

    return f


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv]
    if not paths:
        sys.stderr.write(__doc__.split("Usage:")[1].split("Exit codes")[0])
        return 2
    any_errors = False
    for path in paths:
        try:
            findings = lint_file(path)
        except FileNotFoundError:
            sys.stderr.write(f"{path}: no such file\n")
            return 2
        except yaml.YAMLError as exc:
            sys.stderr.write(f"{path}: not valid YAML: {exc}\n")
            return 2
        for msg in findings.errors:
            print(f"{path}: ERROR   {msg}")
        for msg in findings.warnings:
            print(f"{path}: WARNING {msg}")
        n_e, n_w = len(findings.errors), len(findings.warnings)
        verdict = "FAIL" if n_e else "OK"
        print(f"{path}: {verdict} — {n_e} error(s), {n_w} warning(s)")
        any_errors = any_errors or bool(n_e)
    return 1 if any_errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
