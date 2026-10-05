"""One-off synthetic packet binding check; no inference, semantics or assessment edits."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from diagnostic_evidence_preflight import check_manifest
from export_factual_audit import check_native_review_schema
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from rob2_kit.application.source_check import SourceCheckReport, resolve_quote_excerpt
from rob2_kit.workflow_models import NonBlankText, WorkingSourceRange

ROOT = Path(__file__).resolve().parent


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(data: bytes) -> Any:
    return json.loads(data, object_pairs_hook=unique_object)


def preflight() -> dict[str, Any]:
    freeze = load((ROOT / "freeze.json").read_bytes())
    for name, expected in freeze["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen artifact changed: {name}")
    schema = load((ROOT / "output.schema.json").read_bytes())
    check_native_review_schema(schema)
    Draft202012Validator.check_schema(schema)
    coverage = {
        arm: check_manifest(ROOT / f"{arm}.manifest.json", ROOT / f"{arm}.prompt.txt")
        for arm in ("ordinary", "contrastive")
    }
    return {"coverage": coverage, "wire_subset": "passed", "provider_acceptance": "not tested"}


def exact_coverage(ids: list[str], expected: set[str], name: str) -> None:
    if len(ids) != 13 or set(ids) != expected or any(n != 1 for n in Counter(ids).values()):
        raise ValueError(f"{name} must cover exactly 13 unique frozen claim IDs")


def check(data: bytes) -> dict[str, Any]:
    preflight()
    if len(data) > 24_000:
        raise ValueError("Response exceeds frozen 24,000-byte acceptance budget")
    value = load(data)
    schema = load((ROOT / "output.schema.json").read_bytes())
    Draft202012Validator(schema).validate(value)
    # Retain authoritative stricter nonblank, strict integer and coordinate rules.
    report = SourceCheckReport.model_validate(value["review"])
    packet_bytes = (ROOT / "sources-and-claims.json").read_bytes()
    packet = load(packet_bytes)
    expected_snapshot = "sha256:" + hashlib.sha256(packet_bytes).hexdigest()
    if report.snapshot_identity != expected_snapshot:
        raise ValueError("Stale snapshot binding")
    claims = {c["claim_id"]: (case, c) for case in packet["cases"] for c in case["claims"]}
    if len(claims) != 13:
        raise ValueError("Frozen packet does not contain 13 unique claims")
    exact_coverage([f.claim_id for f in report.findings], set(claims), "Findings")
    exact_coverage([r["claim_id"] for r in value["revisions"]], set(claims), "Revisions")
    if [f.claim_id for f in report.findings] != list(claims):
        raise ValueError("Findings must follow frozen packet order")
    if [r["claim_id"] for r in value["revisions"]] != list(claims):
        raise ValueError("Revisions must follow frozen packet order")
    reference_count = 0
    for finding in report.findings:
        case, claim = claims[finding.claim_id]
        if finding.field != claim["field"] or finding.clause != claim["text"]:
            raise ValueError("Finding must bind the complete unchanged claim and field")
        lines = []
        for number, numbered in enumerate(case["numbered_text"].splitlines(), 1):
            prefix, text = numbered.split("|", 1)
            if prefix != str(number):
                raise ValueError("Frozen source line numbering changed")
            lines.append(text)
        source = "\n".join(lines) + "\n"
        if hashlib.sha256(source.encode()).hexdigest() != case["source_sha256"]:
            raise ValueError("Frozen source identity changed")
        if case["source_id"] != "sh_" + case["source_sha256"][:16]:
            raise ValueError("Synthetic source shorthand changed")
        if not finding.references:
            raise ValueError("Each finding requires at least one text citation")
        for reference in finding.references:
            location = reference.location
            if not isinstance(location, WorkingSourceRange):
                raise ValueError("Synthetic packet contains no visual evidence")
            if location.source_id != case["source_id"] or location.page != 1:
                raise ValueError("Reference belongs outside this case/page")
            if not 1 <= location.start_line <= location.end_line <= len(lines):
                raise ValueError("Reference lines outside frozen source")
            if reference.quote is None:
                raise ValueError("Text reference requires a contiguous source quote")
            window = "\n".join(lines[location.start_line - 1 : location.end_line])
            resolve_quote_excerpt(window, reference.quote)
            reference_count += 1
    for revision in value["revisions"]:
        TypeAdapter(NonBlankText).validate_python(revision["revised_text"])
        TypeAdapter(NonBlankText).validate_python(revision["rationale"])
    return {
        "valid": True,
        "claims": 13,
        "references": reference_count,
        "response_sha256": hashlib.sha256(data).hexdigest(),
        "scope": "Frozen synthetic structure/provenance only; no semantics or application",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args()
    print(json.dumps(check(args.output.read_bytes()) if args.output else preflight(), indent=2))
