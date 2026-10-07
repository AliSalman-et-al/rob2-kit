"""Question advisories verify provenance and preserve the original assessment."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from support import rob2 as support
from test_inline_visual_references import _neutral_graphics, _reference

from rob2_kit.application._state import _db, _state
from rob2_kit.application.source_check import (
    FORMAT,
    SourceCheckReport,
    export_current_packet,
    validate_report,
)
from scripts.export_factual_audit import (
    READ_TOOLS,
    check_native_review_schema,
    native_review_schema,
    prepare_native_review,
)

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
        "These counts do not establish observed outcome availability.",
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
    return {
        "format": FORMAT,
        "snapshot_identity": packet["snapshot_identity"],
        "questions": [
            {"claim_id": q["claim_id"], "disposition": "retain"} for q in packet["questions"]
        ],
    }


def _revise(packet: dict[str, Any]) -> dict[str, Any]:
    report = _report(packet)
    span = next(
        s for s in packet["cited_spans"] if s.get("numbered_text", "").startswith("1|" + FACT)
    )
    report["questions"][0].update(
        disposition="revise",
        affected_entries=["/justification"],
        reason="A hypothetical qualification requires assessor review.",
        references=[span["evidence_identity"]],
    )
    return report


def _protected(workspace: Path) -> tuple[bytes, bytes]:
    root = workspace / ".rob2-kit"
    return (root / "canonical.sqlite3").read_bytes(), (root / "working.sqlite3").read_bytes()


def test_full_canonical_answers_paired_guidance_pixels_and_fresh_preparation(assessment, tmp_path):
    workspace, packet = assessment
    before = _protected(workspace)
    record = _state(workspace)["domain_records"]["trial:domain:selection"]
    for question, answer in zip(packet["questions"], record["answers"], strict=True):
        assert question["assessment"] == answer
        assert question["question_id"] == answer["question_id"]
        assert question["wording"] and question["official_guidance"]
        assert "/answer" in question["entry_ids"] and "/justification" in question["entry_ids"]
    assert packet == export_current_packet(workspace, "trial", "domain:selection")
    assert "instruction" not in packet
    for span in packet["cited_spans"]:
        if span["kind"] == "narrative":
            assert "quote" not in span
            assert span["numbered_text"]
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
    assert manifest["model_calls"] == 0 and manifest["fresh_exec"] and not manifest["resume"]
    assert manifest["accepted_checkpoints_not_model_input"] == [record]
    guidance = json.loads((output / "guidance.json").read_text(encoding="utf-8"))
    assert "questions" not in guidance and guidance["shared_sections"]
    assert manifest["allowed_tools"] == list(READ_TOOLS)
    assert not set(READ_TOOLS) & {"save_domain_judgment", "review_trial", "get_status"}
    assert "--image" in manifest["command"] and "--output-schema" in manifest["command"]
    assert "Attached image 1" in (output / "prompt.txt").read_text(encoding="utf-8")
    assert "Not supplied" in manifest["delivery"]["filesystem_isolation"]
    assert _protected(workspace) == before
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


def test_retaining_uncertainty_and_even_wrong_criticism_are_non_authoritative(assessment):
    workspace, packet = assessment
    before = _protected(workspace)
    for raw in (_report(packet), _revise(packet)):
        receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(raw))
        assert receipt["advisory_only"] and not receipt["semantic_support_verified"]
        assert receipt["retention_is_not_correctness_proof"] and not receipt["assessment_mutated"]
    assert packet["questions"][0]["assessment"]["unknowns"]
    assert _protected(workspace) == before


@pytest.mark.parametrize("branch", ["retain", "revise", "uncertain"])
def test_schema_branch_requirements_match_runtime(branch):
    report: dict[str, Any] = {
        "format": FORMAT,
        "snapshot_identity": "sha256:" + "1" * 64,
        "questions": [{"claim_id": "sha256:" + "2" * 64, "disposition": branch}],
    }
    row = report["questions"][0]
    if branch != "retain":
        row.update(reason="Bounded premise remains unresolved.", references=[], affected_entries=[])
    if branch == "revise":
        row.update(affected_entries=["/justification"], references=["eh_" + "3" * 16])
    SourceCheckReport.model_validate(report)
    schema = native_review_schema()
    check_native_review_schema(schema)
    names = {
        s["properties"]["disposition"]["const"]: s
        for s in schema["$defs"].values()
        if "disposition" in s.get("properties", {})
    }
    assert set(names) == {"retain", "revise", "uncertain"}
    assert set(names[branch]["required"]) == set(row)
    if branch == "revise":
        for field in ("affected_entries", "references"):
            assert names[branch]["properties"][field]["minItems"] == 1
            invalid = copy.deepcopy(report)
            invalid["questions"][0][field] = []
            with pytest.raises(ValueError):
                SourceCheckReport.model_validate(invalid)
    if branch != "retain":
        row["reason"] = " "
        with pytest.raises(ValueError):
            SourceCheckReport.model_validate(report)


@pytest.mark.parametrize(
    "failure",
    [
        "unknown-claim",
        "missing-question",
        "duplicate-question",
        "snapshot",
        "invented-entry",
        "extra-answer",
        "old-format",
        "null-quote",
        "mixed-reference",
        "wrong-quote",
        "invented-handle",
        "agent-claim",
    ],
)
def test_invalid_contract_fails_without_mutating_assessment(assessment, failure):
    workspace, packet = assessment
    before = _protected(workspace)
    report = _revise(packet)
    row = report["questions"][0]
    if failure == "unknown-claim":
        row["claim_id"] = "sha256:" + "0" * 64
    elif failure == "missing-question":
        report["questions"] = report["questions"][:1]
    elif failure == "duplicate-question":
        report["questions"].append(copy.deepcopy(row))
    elif failure == "snapshot":
        report["snapshot_identity"] = "sha256:" + "0" * 64
    elif failure == "invented-entry":
        row["affected_entries"] = ["/unknowns/999"]
    elif failure == "extra-answer":
        row["answer"] = "no"
    elif failure == "old-format":
        report["format"] = "rob2-kit.source-check.v1"
    elif failure == "invented-handle":
        row["references"] = ["eh_" + "0" * 16]
    elif failure == "agent-claim":
        row["references"] = [row["claim_id"]]
    else:
        ref = {"handle": row["references"][0], "quote": "Invented source words"}
        if failure == "null-quote":
            ref["quote"] = None
        if failure == "mixed-reference":
            ref["source_id"] = "sh_" + "0" * 16
        row["references"] = [ref]
    with pytest.raises(ValueError):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _protected(workspace) == before


def test_exact_handle_no_quote_and_optional_narrower_quote_do_not_widen(assessment):
    workspace, packet = assessment
    before = _protected(workspace)
    report = _revise(packet)
    row = report["questions"][0]
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    original = receipt["resolved_references"][0]
    assert original["quote"].startswith(FACT)
    row["references"] = [{"handle": row["references"][0], "quote": "Alpha 20"}]
    narrowed = validate_report(workspace, packet, SourceCheckReport.model_validate(report))[
        "resolved_references"
    ][0]
    assert narrowed["quote"] == "Alpha 20"
    assert narrowed["resolved_subspan"]["start_char"] == len("Period 1: ")
    assert narrowed["resolved_subspan"]["end_char"] < original["resolved_subspan"]["end_char"]
    span = next(
        s for s in packet["cited_spans"] if s.get("numbered_text", "").startswith("1|" + FACT)
    )
    support._call(
        workspace, "read_pages", {"trial_id": "trial", "source_id": span["source_id"], "pages": [1]}
    )
    selected = support._call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": span["source_id"],
            "page": 1,
            "selected_text": "Alpha 20",
        },
    )["data"]["evidence"]
    row["references"] = [selected["handle"]]
    exact = validate_report(workspace, packet, SourceCheckReport.model_validate(report))[
        "resolved_references"
    ][0]
    assert (
        exact["quote"] == "Alpha 20" and exact["resolved_subspan"] == narrowed["resolved_subspan"]
    )
    row["references"] = [{"handle": selected["handle"], "quote": "Period 1: Alpha 20"}]
    with pytest.raises(ValueError, match="contiguous source excerpt"):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _protected(workspace) == before


def test_wrong_full_identity_ambiguous_corrupt_and_foreign_handles_fail(assessment):
    workspace, packet = assessment
    report = _revise(packet)
    before = _protected(workspace)
    identity = report["questions"][0]["references"][0]
    report["questions"][0]["references"] = [identity[:-1] + ("0" if identity[-1] != "0" else "1")]
    with pytest.raises(ValueError, match="identity does not match"):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    report["questions"][0]["references"] = [identity]
    with _db(workspace, "derivative.sqlite3") as db:
        raw = bytes(
            db.execute(
                "SELECT payload FROM evidence_handles WHERE identity=?", (identity,)
            ).fetchone()[0]
        )
        item = json.loads(raw)
        other = identity[:23] + "f" * 48
        db.execute("INSERT INTO evidence_handles VALUES (?,?)", (other, raw))
    with pytest.raises(ValueError):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    with _db(workspace, "derivative.sqlite3") as db:
        db.execute("DELETE FROM evidence_handles WHERE identity=?", (other,))
        item["trial_id"] = "foreign"
        db.execute(
            "UPDATE evidence_handles SET payload=? WHERE identity=?",
            (json.dumps(item).encode(), identity),
        )
    with pytest.raises(ValueError):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _protected(workspace) == before


@pytest.mark.parametrize("omit_region", [False, True])
def test_visual_handles_keep_original_region_and_new_regions_need_authentic_delivery(
    assessment, omit_region: bool
):
    workspace, packet = assessment
    before = _protected(workspace)
    report = _revise(packet)
    figure = next(s for s in packet["cited_spans"] if s["kind"] == "figure")
    row = report["questions"][0]
    row["references"] = [figure["evidence_identity"]]
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert receipt["resolved_references"][0]["verified_provenance"]["region"] == figure["region"]
    row["references"] = [
        {"handle": figure["evidence_identity"], "quote": "unverified transcription"}
    ]
    with pytest.raises(ValueError, match="not a verified text quote"):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    visual = {
        "delivery_receipt": figure["delivery_receipt"],
        "region": figure["region"],
        "transcription": "Qualified observation",
        "uncertainty": "Interpretation may be wrong.",
    }
    if omit_region:
        del visual["region"]
    row["references"] = [visual]
    assert not validate_report(workspace, packet, SourceCheckReport.model_validate(report))[
        "semantic_support_verified"
    ]
    visual["delivery_receipt"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="authentic current-Trial"):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _protected(workspace) == before


def test_followup_recovery_and_tampered_packet_cannot_rewrite_original_support(assessment):
    workspace, packet = assessment
    before = _protected(workspace)
    report = _revise(packet)
    sources = support._call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    source = next(s for s in sources if s["label"] == "uncited.txt")
    page = support._call(
        workspace, "read_pages", {"trial_id": "trial", "source_id": source["id"], "pages": [1]}
    )["data"]["pages"][0]
    report["questions"][0]["references"] = [page["passage_ref"]]
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert "does not retroactively" in receipt["resolved_references"][0]["binding"]
    assert "complete uncited" in receipt["resolved_references"][0]["quote"]
    from rob2_kit.application._state import _identity

    changed = copy.deepcopy(packet)
    changed["questions"][0]["assessment"]["justification"] = "invented"
    changed["snapshot_identity"] = _identity(
        {k: v for k, v in changed.items() if k != "snapshot_identity"}
    )
    report["snapshot_identity"] = changed["snapshot_identity"]
    with pytest.raises(ValueError, match="current canonical review"):
        validate_report(workspace, changed, SourceCheckReport.model_validate(report))
    old = copy.deepcopy(packet)
    old["format"] = "rob2-kit.source-check.v1"
    with pytest.raises(ValueError, match="Historical advisory contract"):
        validate_report(workspace, old, SourceCheckReport.model_validate(_report(packet)))
    assert _protected(workspace) == before


def test_duplicate_saved_text_has_distinct_bound_entry_ids_without_clause_copying(assessment):
    workspace, packet = assessment
    question = packet["questions"][0]
    assert question["assessment"]["unknowns"][0] == question["assessment"]["unknowns"][1]
    assert {"/unknowns/0", "/unknowns/1"} <= set(question["entry_ids"])
    report = _revise(packet)
    report["questions"][0]["affected_entries"] = ["/unknowns/0", "/unknowns/1"]
    receipt = validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert [e["entry_id"] for e in receipt["resolved_entries"]] == ["/unknowns/0", "/unknowns/1"]
    assert receipt["resolved_entries"][0]["value"] == receipt["resolved_entries"][1]["value"]


def test_all_five_domains_and_only_active_answers_are_reviewed(tmp_path):
    workspace, evidence, revision = support._assessment_workspace(tmp_path)
    for domain in ("randomization", "deviations", "missing", "measurement", "selection"):
        did = "domain:" + domain
        support._call(workspace, "get_domain_context", {"trial_id": "trial", "domain_id": did})
        draft = support._domain_draft("trial", did, revision, evidence)
        if domain == "missing":
            draft["answers"][0]["answer"] = "yes"
        result = support._call(workspace, "save_domain_judgment", draft)
        assert result["outcome"] == "success", result
        revision = result["head"]["state_revision"]
    packet = export_current_packet(workspace, "trial")
    assert {q["domain_id"] for q in packet["questions"]} == {
        "domain:" + d
        for d in ("randomization", "deviations", "missing", "measurement", "selection")
    }
    missing = [q for q in packet["questions"] if q["domain_id"] == "domain:missing"]
    assert len(missing) == 1
    assert validate_report(workspace, packet, SourceCheckReport.model_validate(_report(packet)))[
        "advisory_only"
    ]


def test_current_checkpoint_change_rejects_old_snapshot(assessment):
    workspace, packet = assessment
    report = _report(packet)
    state = _state(workspace)
    support._call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:selection"}
    )
    identity = packet["questions"][0]["assessment"]["bases"][0]["evidence"]
    draft = support._domain_draft(
        "trial", "domain:selection", state["revision"], {"handle": "eh_" + identity[7:23]}
    )
    draft["answers"][0]["justification"] = "Revised interpretation of the original Evidence."
    draft["supersedes"] = packet["checkpoint_identities"][0]
    draft["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "Original interpretation corrected.",
    }
    changed = support._call(workspace, "save_domain_judgment", draft)
    assert changed["outcome"] == "success", changed
    before = _protected(workspace)
    with pytest.raises(ValueError, match="checkpoint is stale"):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _protected(workspace) == before


def test_source_bytes_cannot_be_replaced_by_a_reviewer_assertion(assessment):
    workspace, packet = assessment
    report = _revise(packet)
    state = _state(workspace)
    source_id = state["batch"]["trials"][0]["sources"][0]["id"]
    source = workspace / ".rob2-kit/sources/trial" / (source_id + ".bin")
    source.write_bytes(b"An agent claims this is the source.")
    before = _protected(workspace)
    with pytest.raises(ValueError):
        validate_report(workspace, packet, SourceCheckReport.model_validate(report))
    assert _protected(workspace) == before
