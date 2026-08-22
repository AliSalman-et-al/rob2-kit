from __future__ import annotations

import json

from rob2_kit.application.admissibility import validate_answer
from rob2_kit.application.archive import verify_archive, write_archive
from rob2_kit.application.contracts import (
    AuthoritativePresentation,
    EvidenceReference,
    PreflightSourcesContinuation,
    ReviewAuthority,
    ReviewAuthorityRequirement,
    VerifiedCurrentStatus,
    WorkflowPhase,
)
from rob2_kit.application.drafts import DraftPatch, apply_patches
from rob2_kit.application.provenance import (
    FieldEvidenceBinding,
    ProvenanceDeclaration,
    TableAxisMap,
    TableCellBinding,
    validate_complete_reported_provenance,
)
from rob2_kit.application.transport import (
    annotate_handles,
    resolve_handles,
    sanitize_model_output,
)
from rob2_kit.interfaces.mcp.server import PUBLIC_TOOL_NAMES


def _status(phase: WorkflowPhase = WorkflowPhase.EMPTY) -> VerifiedCurrentStatus:
    return VerifiedCurrentStatus(
        phase=phase,
        review=ReviewAuthorityRequirement(
            required=ReviewAuthority.NONE, satisfied=True
        ),
        continuation=(
            PreflightSourcesContinuation()
            if phase is WorkflowPhase.EMPTY
            else None
        ),
        presentation=AuthoritativePresentation(
            code=phase.value, headline=phase.value, summary=phase.value
        ),
    )


def test_continuation_discriminator_survives_default_exclusion() -> None:
    payload = json.loads(
        _status().model_dump_json(exclude_none=True, exclude_defaults=True)
    )
    assert payload["continuation"]["operation"] == "preflight_sources"
    assert payload["continuation"]["authority"] == "host"


def test_short_handles_round_trip_without_removing_hashes(tmp_path) -> None:
    reference = {"kind": "evidence", "identity": "sha256:" + "a" * 64}
    rendered = annotate_handles(tmp_path, reference)
    assert rendered["identity"] == reference["identity"]
    assert rendered["handle"] == "e1"
    assert resolve_handles(tmp_path, "e1") == reference


def test_nonfinal_completion_claim_is_suppressed() -> None:
    sanitized = sanitize_model_output(
        "Assessment completed successfully.\nScientific note remains.", _status()
    )
    assert "completed" not in sanitized.text.casefold()
    assert sanitized.text == "Scientific note remains."
    assert sanitized.contradictions


def test_allocation_concealment_rejects_reputation_proxy() -> None:
    defects = validate_answer(
        "sq:randomization:concealment",
        "probably_yes",
        "Allocation was probably concealed.",
        [
            {
                "source_fact": (
                    "Patients were enrolled by ECOG-ACRIN and baseline groups "
                    "were well-balanced."
                ),
                "inference": "ECOG-ACRIN trials standardly use central allocation.",
            }
        ],
        pointer="/active_answers/0",
    )
    assert {item.code for item in defects} >= {
        "inadmissible_proxy",
        "generic_expectation",
    }


def test_field_provenance_rejects_value_free_quote() -> None:
    evidence = EvidenceReference(kind="evidence", identity="sha256:" + "b" * 64)
    card = {
        "reported": {
            "effect": {
                "statistic": "hazard ratio",
                "group_or_category": "a vs b",
                "value": 0.61,
                "denominator_basis": "time-to-event analysis",
            },
            "quantities": [],
            "precision": None,
        }
    }
    declaration = ProvenanceDeclaration(
        source_reported_outcome="progression-free survival",
        relationship_to_requested="exact",
        field_bindings=tuple(
            FieldEvidenceBinding(path=path, evidence=(evidence,))
            for path in (
                "/reported/effect/value",
                "/reported/effect/statistic",
                "/reported/effect/group_or_category",
                "/reported/effect/denominator_basis",
            )
        ),
    )
    defects = validate_complete_reported_provenance(
        card,
        declaration,
        lambda _reference: "Clinical progression was defined by increasing symptoms.",
    )
    assert "value_not_in_evidence" in {item.code for item in defects}


def test_related_endpoint_requires_clarification() -> None:
    evidence = EvidenceReference(kind="evidence", identity="sha256:" + "c" * 64)
    card = {"reported": {"categories": []}}
    declaration = ProvenanceDeclaration(
        source_reported_outcome="time to clinical progression",
        relationship_to_requested="related",
        field_bindings=(),
    )
    defects = validate_complete_reported_provenance(
        card,
        declaration,
        lambda _reference: "time to clinical progression",
    )
    assert "endpoint_mismatch_requires_clarification" in {
        item.code for item in defects
    }


def test_table_axis_rejects_grade_three_as_grade_three_or_higher() -> None:
    evidence = EvidenceReference(kind="evidence", identity="sha256:" + "d" * 64)
    category = {
        "statistic": "incidence",
        "unit": "percent",
        "group_or_category": "Grade 3 or higher",
        "value": "16.7",
        "denominator_basis": "390 patients",
    }
    card = {"reported": {"categories": [category]}}
    bindings = tuple(
        FieldEvidenceBinding(
            path=f"/reported/categories/0/{field}",
            evidence=(evidence,),
            required_values=(value,),
        )
        for field, value in category.items()
    )
    declaration = ProvenanceDeclaration(
        source_reported_outcome="adverse events",
        relationship_to_requested="exact",
        field_bindings=bindings,
        table=TableAxisMap(
            title="Adverse Events",
            population="390 patients",
            row_axis="event",
            column_axis="grade",
            row_labels=("Any event",),
            column_labels=("Grade 3", "Grade 4", "Grade 5"),
            required_cells=(("Any event", "Grade 3"),),
        ),
        table_cells=(
            TableCellBinding(
                path="/reported/categories/0/value",
                evidence=evidence,
                row_label="Any event",
                column_label="Grade 3",
                raw_text="65 (16.7%)",
                value="16.7",
                unit="percent",
                denominator_basis="390 patients",
            ),
        ),
    )
    source = (
        "Adverse Events 390 patients Any event Grade 3 65 (16.7%) "
        "Grade 4 49 (12.6%) Grade 5 1 (0.3%)"
    )
    defects = validate_complete_reported_provenance(
        card, declaration, lambda _reference: source
    )
    assert "unsupported_cumulative_category" in {item.code for item in defects}


def test_patchable_proposal_draft() -> None:
    result = apply_patches(
        {"results": [{"value": 1}]},
        (DraftPatch(op="replace", path="/results/0/value", value=2),),
    )
    assert result == {"results": [{"value": 2}]}


def test_compact_archive_is_deterministic_and_verified(tmp_path) -> None:
    kwargs = {
        "approved_identity": "sha256:" + "e" * 64,
        "summary": {"identity": "sha256:" + "f" * 64},
        "records": {},
        "root_record_ids": [],
        "sources": {"article.txt": b"article"},
        "renders": {},
        "report_html": "<p>report</p>",
    }
    first = write_archive(tmp_path, **kwargs)
    second = write_archive(tmp_path, **kwargs)
    assert first == second
    assert verify_archive(tmp_path, first)


def test_public_tool_surface_remains_narrow() -> None:
    assert PUBLIC_TOOL_NAMES == (
        "preflight_sources",
        "inspect_candidate_sources",
        "save_intake_plan",
        "capture_batch",
        "list_sources",
        "retrieve_evidence",
        "render_page",
        "save_proposal",
        "approve_batch",
        "validate_domain_judgment",
        "commit_domain_judgment",
        "prepare_trial_finish",
        "finish_trial",
        "finalize_batch",
        "read_record",
    )
