"""Source checking binds observations, never turns reviewer criticism into a label."""

from __future__ import annotations

import copy
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from support import rob2 as support
from test_inline_visual_references import _neutral_graphics, _reference

from rob2_kit.application._state import _canonical_evidence_records, _identity, _state
from rob2_kit.application.source_check import (
    SourceCheckReport,
    build_packet,
    export_current_packet,
    validate_report,
)
from scripts.export_factual_audit import READ_TOOLS, prepare_native_review

FACT = "Period 1: Alpha 20, Beta 30, Gamma 40 randomized participants."
INFERENCE = "Subjective symptom scoring may involve clinical judgment."


@pytest.fixture
def assessment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    original = support._workspace

    def create(path: Path, requested_outcome: str = "requested outcome") -> Path:
        result = original(path, requested_outcome)
        _neutral_graphics(result / "input/trial/figures.pdf")
        (result / "input/trial/supplement.txt").write_text(
            FACT + "\nSymptoms were scored subjectively.\n"
            "Period 2: Gamma had 9 adverse-event discontinuations.\n"
            "Available-case mean at day 30 used ANCOVA; "
            "randomized counts are not observed counts.\n",
            encoding="utf-8",
        )
        (result / "input/trial/uncited.txt").write_text(
            "\n".join(f"Line {n}: complete uncited follow-up context." for n in range(1, 601)),
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(support, "_workspace", create)
    workspace, text, revision = support._assessment_workspace(tmp_path)
    sources = support._call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    notes = next(source for source in sources if source["label"] == "supplement.txt")
    image = next(source for source in sources if source["label"] == "figures.pdf")
    visual = _reference(workspace, image, 1)
    support._call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:selection"}
    )
    draft = support._domain_draft("trial", "domain:selection", revision, text)
    first = draft["answers"][0]
    first["justification"] = FACT + " " + INFERENCE
    first["unknowns"] = [
        "These counts do not establish observed outcome availability.",
        "The outcome measurement method remains unresolved.",
    ]
    first["bases"] += [
        {
            "evidence": {"source_id": notes["id"], "page": 1, "start_line": 1, "end_line": 2},
            "role": "context",
        },
        {"evidence": visual, "role": "context"},
    ]
    first["counterevidence"] = [
        {"evidence": [visual], "implication": "Allocation is not follow-up completeness."}
    ]
    assert support._call(workspace, "save_domain_judgment", draft)["outcome"] == "success"
    packet = export_current_packet(workspace, "trial", "domain:selection")
    return workspace, packet


def _report(packet: dict[str, Any]) -> dict[str, Any]:
    span = next(span for span in packet["cited_spans"] if span.get("quote", "").startswith(FACT))
    reference = {
        "location": {key: span[key] for key in ("source_id", "page", "start_line", "end_line")},
        "quote": span["quote"],
        "relation": "supports",
    }
    findings = [
        {
            "claim_id": claim["claim_id"],
            "field": "justification",
            "clause": claim["justification"],
            "classification": "unresolved",
            "explanation": "No additional assertion about source support.",
            "uncertainty": "This offline fixture does not adjudicate other statements.",
            "references": [],
        }
        for claim in packet["claims"]
    ]
    findings[0].update(
        clause=FACT,
        classification="supported_fact",
        explanation="Counts identify allocation in Period 1, not outcome observation.",
        uncertainty="Exact fact retained; outcome availability remains unknown.",
        references=[reference],
    )
    findings.append(
        {
            **findings[0],
            "clause": INFERENCE,
            "classification": "legitimate_inference",
            "explanation": "Clinical judgment is a qualified inference from subjective scoring.",
            "uncertainty": "Does not prove differential measurement or bias.",
        }
    )
    return {"snapshot_identity": packet["snapshot_identity"], "findings": findings}


def _canonical_hash(workspace: Path) -> str:
    return hashlib.sha256((workspace / ".rob2-kit/canonical.sqlite3").read_bytes()).hexdigest()


def test_full_claims_blind_labels_exact_sources_visual_provenance_and_native_preparation(
    assessment: tuple[Path, dict[str, Any]],
    tmp_path: Path,
) -> None:
    workspace, packet = assessment
    before = _canonical_hash(workspace)
    record = _state(workspace)["domain_records"]["trial:domain:selection"]
    for claim, answer in zip(packet["claims"], record["answers"], strict=True):
        for field in ("justification", "unknowns", "counterevidence", "missing_data"):
            assert claim[field] == answer.get(field)
        assert claim["citations"] == answer["bases"]
    keys = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            keys.update(value)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(packet)
    assert not keys & {"answer", "judgment", "question_id", "domain_id", "driver"}
    assert packet == export_current_packet(workspace, "trial", "domain:selection")
    figure = next(span for span in packet["cited_spans"] if span["kind"] == "figure")
    assert figure["delivery_receipt"] and figure["region"] and figure["render"]["png_sha256"]
    assert figure["uncertainty"]
    output = tmp_path / "request"
    manifest = prepare_native_review(
        workspace,
        "trial",
        "domain:selection",
        output,
        assessor_model="declared-assessor",
        assessor_effort="medium",
        reviewer_model="declared-reviewer",
        reviewer_effort="low",
    )
    assert manifest["model_calls"] == 0 and manifest["fresh_exec"]
    assert manifest["accepted_checkpoints_not_model_input"] == [record]
    guidance = json.loads((output / "guidance.json").read_text())
    from rob2_kit.packs import SCIENTIFIC_PACK

    accepted_ids = {answer["question_id"] for answer in record["answers"]}
    assert guidance["questions"] == [
        {
            "wording": question.wording,
            "official": question.guidance.official.model_dump(mode="json"),
        }
        for question in SCIENTIFIC_PACK.questions
        if question.id in accepted_ids
    ]
    assert guidance["shared_sections"] == [
        {"source_url": section.source_url, "official": section.guidance.model_dump(mode="json")}
        for section in SCIENTIFIC_PACK.official_sections or ()
        if section.domain_id in {"all", record["domain_id"]}
    ]
    assert (
        json.dumps(guidance, ensure_ascii=False, indent=2)
        in (output / "instructions.md").read_text()
    )
    assert (
        manifest["guidance_sha256"]
        == hashlib.sha256((output / "guidance.json").read_bytes()).hexdigest()
    )
    assert "Not supplied" in manifest["delivery"]["filesystem_isolation"]
    assert "Availability is not actual delivery" in manifest["delivery"]["followup"]
    assert "Attached image 1: Evidence " in (output / "prompt.txt").read_text(encoding="utf-8")
    assert "assessor_routing_not_model_input" not in (output / "prompt.txt").read_text(
        encoding="utf-8"
    )
    assert manifest["assessor_routing_not_model_input"][0]["question_id"]
    assert manifest["allowed_tools"] == list(READ_TOOLS)
    assert not set(READ_TOOLS) & {"save_domain_judgment", "review_trial", "get_status"}
    assert "--image" in manifest["command"] and "--output-schema" in manifest["command"]
    for index, item in enumerate(manifest["command"]):
        if item == "-c":
            tomllib.loads(manifest["command"][index + 1])
    image = manifest["images"][0]
    assert "sha256:" + image["png_sha256"] == figure["render"]["png_sha256"]
    assert _canonical_hash(workspace) == before
    with pytest.raises(FileExistsError):
        prepare_native_review(
            workspace,
            "trial",
            None,
            output,
            assessor_model="a",
            assessor_effort="low",
            reviewer_model="b",
            reviewer_effort="low",
        )


def test_supported_fact_and_legitimate_inference_retained_dubious_critique_cannot_edit(
    assessment: tuple[Path, dict[str, Any]],
) -> None:
    workspace, packet = assessment
    original = _canonical_hash(workspace)
    report = _report(packet)
    valid = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert valid["advisory_only"] and not valid["semantic_support_verified"]
    assert {finding["classification"] for finding in valid["report"]["findings"]} >= {
        "supported_fact",
        "legitimate_inference",
    }
    assert all("this claim's original" in ref["binding"] for ref in valid["resolved_references"])
    report["findings"][0]["classification"] = "contradicted_fact"
    report["findings"][0]["explanation"] = (
        "Dubious reviewer criticism with authentic but irrelevant quote."
    )
    # A valid locator is not an entailment judgment. Even this false critique is
    # an advisory artifact and cannot downgrade, rewrite or finalize anything.
    assert validate_report(workspace, packet, SourceCheckReport.model_validate(report))[
        "advisory_only"
    ]
    assert _canonical_hash(workspace) == original


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-quote",
        "foreign-source",
        "invented-clause",
        "snapshot",
        "empty-uncertainty",
        "missing-claim",
        "risk-label",
    ],
)
def test_invalid_review_binding_rejected_without_canonical_mutation(
    assessment: tuple[Path, dict[str, Any]],
    failure: str,
) -> None:
    workspace, packet = assessment
    before = _canonical_hash(workspace)
    report = _report(packet)
    first = report["findings"][0]
    if failure == "wrong-quote":
        first["references"][0]["quote"] = "Invented source words"
    elif failure == "foreign-source":
        first["references"][0]["location"]["source_id"] = "sh_" + "a" * 16
    elif failure == "invented-clause":
        first["clause"] = "A count or assertion never saved by the assessor"
    elif failure == "snapshot":
        report["snapshot_identity"] = "sha256:" + "0" * 64
    elif failure == "empty-uncertainty":
        first["uncertainty"] = ""
    elif failure == "missing-claim":
        report["findings"] = report["findings"][:1]
    else:
        first["judgment"] = "high"
    with pytest.raises(ValueError):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _canonical_hash(workspace) == before


def test_followup_window_does_not_retroactively_repair_original_binding(
    assessment: tuple[Path, dict[str, Any]],
) -> None:
    workspace, packet = assessment
    report = _report(packet)
    reference = report["findings"][0]["references"][0]
    reference["location"].update(start_line=3, end_line=3)
    reference["quote"] = "Period 2: Gamma had 9 adverse-event discontinuations."
    reference["relation"] = "limits"
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert "does not retroactively" in receipt["resolved_references"][0]["binding"]
    changed = copy.deepcopy(packet)
    changed["claims"][0]["justification"] = "changed after review"
    changed["snapshot_identity"] = _identity(
        {key: value for key, value in changed.items() if key != "snapshot_identity"}
    )
    changed_report = copy.deepcopy(report)
    changed_report["snapshot_identity"] = changed["snapshot_identity"]
    with pytest.raises(ValueError, match="current canonical review"):
        validate_report(workspace, changed, SourceCheckReport.model_validate(changed_report))
    # Supplied packet is bound to its immutable original; altering the packet
    # cannot be hidden behind the old reviewer snapshot identity.
    with pytest.raises(ValueError, match="snapshot binding"):
        validate_report(workspace, changed, SourceCheckReport.model_validate(report))


def test_visual_review_receipt_checked_but_transcription_not_certified(
    assessment: tuple[Path, dict[str, Any]],
) -> None:
    workspace, packet = assessment
    original = _canonical_hash(workspace)
    report = _report(packet)
    figure = next(span for span in packet["cited_spans"] if span["kind"] == "figure")
    reference = {
        "location": {
            "delivery_receipt": figure["delivery_receipt"],
            "region": figure["region"],
            "transcription": "Reviewer sees Alpha 20 allocated participants.",
            "uncertainty": "Does not establish observed outcomes.",
        },
        "relation": "limits",
    }
    report["findings"][0]["references"].append(reference)
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    selected = receipt["resolved_references"][1]["verified_provenance"]
    assert selected["render"]["png_sha256"] == figure["render"]["png_sha256"]
    assert not receipt["semantic_support_verified"]
    reference["location"]["delivery_receipt"] = "sha256:" + "a" * 64
    with pytest.raises(ValueError, match="authentic current-Trial"):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _canonical_hash(workspace) == original


def test_captured_but_unrelated_trial_evidence_cannot_enter_packet(
    assessment: tuple[Path, dict[str, Any]],
) -> None:
    workspace, packet = assessment
    state = _state(workspace)
    record = state["domain_records"]["trial:domain:selection"]
    sources = {item["id"]: item for item in state["batch"]["trials"][0]["sources"]}
    evidence = _canonical_evidence_records(
        workspace,
        {
            basis["evidence"]
            for answer in record["answers"]
            for basis in answer["bases"]
            if "evidence" in basis
        },
    )
    next(iter(evidence.values()))["trial_id"] = "unrelated-trial"
    from rob2_kit.application.trials import _approved_result

    with pytest.raises(ValueError, match="current-Trial Evidence"):
        build_packet(_approved_result(state, "trial"), [record], evidence, sources, "trial")
    assert packet == export_current_packet(workspace, "trial", "domain:selection")


def test_native_review_schema_requires_nullable_fields_and_preserves_visual_array_contract():
    from scripts.export_factual_audit import native_review_schema

    schema = native_review_schema()
    local = SourceCheckReport.model_json_schema()
    assert "quote" not in local["$defs"]["SourceCheckReference"]["required"]
    assert "uncertainty" not in local["$defs"]["VisualEvidenceReference"]["required"]
    assert "prefixItems" in local["$defs"]["VisualEvidenceReference"]["properties"]["region"]

    def check(value: Any) -> None:
        if isinstance(value, dict):
            assert "default" not in value and "prefixItems" not in value
            if value.get("type") == "object":
                assert set(value["required"]) == set(value["properties"])
                assert value["additionalProperties"] is False
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(schema)
    coordinate = schema["$defs"]["VisualEvidenceReference"]["properties"]["region"]
    assert coordinate["minItems"] == coordinate["maxItems"] == 4
    assert coordinate["items"] == {"type": "number", "minimum": 0, "maximum": 1}
    nullable_quote = schema["$defs"]["SourceCheckReference"]["properties"]["quote"]["anyOf"]
    assert {"type": "null"} in nullable_quote
    # These are locally accepted nullable observations, never mandatory OCR facts.
    visual = schema["$defs"]["VisualEvidenceReference"]["properties"]["uncertainty"]
    assert {"type": "null"} in visual["anyOf"]


@pytest.mark.parametrize(
    "failure", ["root", "optional", "extra-properties", "broken-ref", "keyword"]
)
def test_native_preflight_rejects_unsupported_or_unbound_schema_before_inference(failure: str):
    from scripts.export_factual_audit import check_native_review_schema, native_review_schema

    schema = native_review_schema()
    if failure == "root":
        schema["anyOf"] = [{"type": "string"}]
    elif failure == "optional":
        schema["$defs"]["SourceCheckReference"]["required"].remove("quote")
    elif failure == "extra-properties":
        schema["$defs"]["VisualEvidenceReference"]["additionalProperties"] = True
    elif failure == "broken-ref":
        schema["properties"]["findings"]["items"]["$ref"] = "#/$defs/nonexistent"
    else:
        schema["$defs"]["WorkingSourceRange"]["properties"]["page"]["ge"] = 1
    with pytest.raises(ValueError):
        check_native_review_schema(schema)


def test_native_preflight_preserves_integer_bound_and_local_text_limits():
    from scripts.export_factual_audit import native_review_schema

    schema = native_review_schema()
    page = schema["$defs"]["WorkingSourceRange"]["properties"]["page"]
    assert page["minimum"] == 1 and "ge" not in page
    assert "minLength" not in schema["$defs"]["SourceCheckFinding"]["properties"]["uncertainty"]
    with pytest.raises(ValueError):
        SourceCheckReport.model_validate(
            {
                "snapshot_identity": "sha256:" + "0" * 64,
                "findings": [
                    {
                        "claim_id": "claim",
                        "field": "justification",
                        "clause": "fact",
                        "classification": "unresolved",
                        "explanation": "unknown",
                        "uncertainty": " ",
                        "references": [],
                    }
                ],
            }
        )


def test_excerpt_receipt_and_saved_unknown_entry_identity(
    assessment: tuple[Path, dict[str, Any]],
) -> None:
    workspace, packet = assessment
    report = _report(packet)
    reference = report["findings"][0]["references"][0]
    reference["quote"] = "Alpha 20, Beta 30, Gamma 40 randomized participants."
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    resolved = receipt["resolved_references"][0]
    assert resolved["quote"] == reference["quote"]
    assert resolved["resolved_subspan"]["start_char"] == len("Period 1: ")
    assert resolved["resolved_location"]["end_line"] == 1
    first = report["findings"][0]
    first["field"] = "unknowns"
    unknowns = packet["claims"][0]["unknowns"]
    first["clause"] = unknowns[0]
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert receipt["resolved_clauses"][0]["entry_path"] == [0]
    first["clause"] = " ".join(unknowns)
    with pytest.raises(ValueError, match="one exact saved field entry"):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))


def test_advisory_source_tools_recover_complete_uncited_context_without_checkpoint_edits(
    assessment: tuple[Path, dict[str, Any]],
) -> None:
    workspace, packet = assessment
    before = _canonical_hash(workspace)
    working = (workspace / ".rob2-kit/working.sqlite3").read_bytes()
    sources = support._call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    source = next(item for item in sources if item["label"] == "uncited.txt")
    assert source["id"] in {item["source_id"] for item in packet["source_inventory"]}
    assert not any(span["source_id"] == source["id"] for span in packet["cited_spans"])
    lines = []
    start = 1
    while start:
        receipt = support._call(
            workspace,
            "read_pages",
            {"trial_id": "trial", "source_id": source["id"], "pages": [1], "start_line": start},
        )
        page = receipt["data"]["pages"][0]
        lines.extend(line.split("|", 1)[1] for line in page["numbered_text"].splitlines())
        start = page["next_start_line"]
    assert lines == (workspace / "input/trial/uncited.txt").read_text().splitlines()
    assert len(lines) == 600
    assert (
        support._call(workspace, "read_guidance", {"document": "references/source-audit.md"})[
            "outcome"
        ]
        == "success"
    )
    assert _canonical_hash(workspace) == before
    assert (workspace / ".rob2-kit/working.sqlite3").read_bytes() == working


def test_inactive_questions_do_not_create_audit_claims_or_invented_accepted_answers(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = support._assessment_workspace(tmp_path)
    support._call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:missing"}
    )
    draft = support._domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][0]["answer"] = "yes"
    draft["answers"][0]["justification"] = "Captured outcome records support availability."
    draft["answers"][0]["unknowns"] = ["Individual observation records are unavailable."]
    # Ordinary submission decides the active path. Export must not restore
    # ignored branches or ask the reviewer to complete new assessments.
    saved = support._call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    record = _state(workspace)["domain_records"]["trial:domain:missing"]
    assert len(record["answers"]) == 1
    output = tmp_path / "fresh-request"
    request = prepare_native_review(
        workspace,
        "trial",
        "domain:missing",
        output,
        assessor_model="declared-assessor",
        assessor_effort="low",
        reviewer_model="declared-reviewer",
        reviewer_effort="low",
    )
    assert len(json.loads((output / "packet.json").read_text())["claims"]) == 1
    assert len(json.loads((output / "guidance.json").read_text())["questions"]) == 1
    assert request["accepted_checkpoints_not_model_input"] == [record]
    assert record["answers"][0]["unknowns"] == ["Individual observation records are unavailable."]
