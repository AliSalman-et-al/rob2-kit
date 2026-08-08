from __future__ import annotations

import sqlite3
from pathlib import Path

import anyio
import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    PrepareRunRequest,
    ReadEvidenceRequest,
    ReadEvidenceResponse,
    RunOperation,
    RunProposalSelection,
    SearchEvidenceRequest,
    SearchQueryEnvelope,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
    WorkflowCondition,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.evidence import (
    CanonicalBlock,
    CanonicalEvidenceUnit,
    CanonicalPage,
    CanonicalUnitKind,
    CropBox,
    DocumentZone,
    EvidenceApplicability,
    EvidenceContext,
    EvidenceScope,
    EvidenceSearchIndex,
    ReadContextMode,
    SearchPolicy,
    SearchQuery,
    TrialDiscourseScope,
    VisualCandidate,
    VisualCandidateKind,
    VisualNominationBasis,
    canonicalize_evidence_units,
)
from rob2_kit.evidence.errors import (
    CursorScopeMismatch,
    InvalidRetrievalRequest,
    OperationalRetrievalFailure,
    RetrievalErrorCode,
    RetrievalFailure,
    ScopeMismatch,
    StaleCursor,
    StaleWorkToken,
)
from rob2_kit.evidence.search import EvidenceRead
from rob2_kit.ingestion.project import (
    PageExtraction,
    PageTextItem,
    ParserResult,
    _normalized_parse_output,
    _optional_metadata,
)
from rob2_kit.interfaces.mcp.server import _retrieval_error, create_server

HASH = "sha256:" + "a" * 64


def test_retrieval_error_codes_preserve_scope_and_validation_boundaries() -> None:
    scope_error = _retrieval_error(
        CursorScopeMismatch("read continuation cursor belongs to a different Evidence scope")
    )
    assert scope_error.error.code is RetrievalErrorCode.CURSOR_SCOPE_MISMATCH
    assert scope_error.error.field == "cursor"
    assert scope_error.error.message.startswith("read continuation cursor")
    invalid_error = _retrieval_error(
        InvalidRetrievalRequest("query terms are invalid", field="query.terms")
    )
    assert invalid_error.error.code is RetrievalErrorCode.INVALID_REQUEST
    assert invalid_error.error.field == "query.terms"


def test_retrieval_error_transport_maps_every_typed_failure_without_substring_parsing() -> None:
    failures: tuple[RetrievalFailure, ...] = (
        StaleCursor("cursor is stale"),
        CursorScopeMismatch("cursor belongs to another scope"),
        ScopeMismatch("unit is outside scope", field="unit_id"),
        StaleWorkToken("token is stale"),
        InvalidRetrievalRequest("query is invalid", field="query"),
        OperationalRetrievalFailure("database is locked"),
    )
    expected = (
        RetrievalErrorCode.STALE_CURSOR,
        RetrievalErrorCode.CURSOR_SCOPE_MISMATCH,
        RetrievalErrorCode.SCOPE_MISMATCH,
        RetrievalErrorCode.STALE_WORK_TOKEN,
        RetrievalErrorCode.INVALID_REQUEST,
        RetrievalErrorCode.OPERATIONAL,
    )
    for failure, code in zip(failures, expected, strict=True):
        response = _retrieval_error(failure)
        assert response.error.code is code
        assert response.error.message == failure.message
        assert response.error.field == failure.field
        assert response.error.recovery == failure.recovery
        assert response.next_actions == failure.next_actions


def test_retrieval_error_transport_does_not_hide_programming_errors() -> None:
    with pytest.raises(RuntimeError, match="bug"):
        _retrieval_error(RuntimeError("bug"))


def test_neighbors_fail_closed_without_structural_anchor(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(
        _unit(
            f"unit:empty-{number}", "source:report", "allocation", reading_order=number
        ).model_copy(update={"section_path": (), "hierarchy_path": ()})
        for number in range(3)
    )
    index.replace_units(units)
    context = index.read_context(
        units[0].unit_id,
        mode=ReadContextMode.NEIGHBORS,
        scope=EvidenceScope(trial_id="trial:active"),
    )
    assert context.neighbors == ()
    assert "structural_boundary_reached" in context.warnings
    assert context.omitted_neighbor_count == 0


def test_unit_mode_fail_closed_without_structural_anchor_reports_no_omissions(
    tmp_path: Path,
) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(
        _unit(
            f"unit:empty-{number}", "source:report", "allocation", reading_order=number
        ).model_copy(update={"section_path": (), "hierarchy_path": ()})
        for number in range(3)
    )
    index.replace_units(units)
    context = index.read_context(
        units[0].unit_id,
        mode=ReadContextMode.UNIT,
        scope=EvidenceScope(trial_id="trial:active"),
    )
    assert context.neighbors == ()
    assert "structural_boundary_reached" in context.warnings
    assert context.omitted_neighbor_count == 0


def test_line_wrap_hyphen_is_stripped_and_rejoined() -> None:
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:1",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="Patient characteristics were well balanced be-",
                        spatial=(20.0, 30.0, 400.0, 50.0),
                        reading_order=1,
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="tween the two groups (Table 1).",
                        spatial=(20.0, 52.0, 400.0, 72.0),
                        reading_order=2,
                    ),
                ),
            ),
        ),
    )
    assert len(units) == 1
    unit = units[0]
    assert unit.text == (
        "Patient characteristics were well balanced between the two groups (Table 1)."
    )
    assert "-" not in unit.text
    assert len(unit.fragment_ids) == 2
    # The deleted hyphen keeps a zero-width canonical mapping (ADR-0014):
    # the trailing span from the first fragment shrinks by one character and
    # a zero-width sibling span records the hyphen's own source position.
    first_fragment_id, second_fragment_id = unit.fragment_ids
    assert [span.fragment_id for span in unit.fragment_spans] == [
        first_fragment_id,
        first_fragment_id,
        second_fragment_id,
    ]
    shrunk_span, deleted_hyphen_span, second_fragment_span = unit.fragment_spans
    assert deleted_hyphen_span.canonical_start == deleted_hyphen_span.canonical_end
    assert deleted_hyphen_span.canonical_start == shrunk_span.canonical_end
    assert shrunk_span.canonical_end == len("Patient characteristics were well balanced be")
    assert second_fragment_span.canonical_start == shrunk_span.canonical_end
    assert second_fragment_span.canonical_end == len(unit.text)


def test_genuine_hyphenated_compound_at_line_break_is_also_rejoined() -> None:
    # ADR-0013: no dictionary check, so a genuine compound word landing on a
    # line break is merged too, accepted as a known limitation of the fix.
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:1",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="Overall well-",
                        spatial=(20.0, 30.0, 400.0, 50.0),
                        reading_order=1,
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="being improved.",
                        spatial=(20.0, 52.0, 400.0, 72.0),
                        reading_order=2,
                    ),
                ),
            ),
        ),
    )
    assert len(units) == 1
    assert units[0].text == "Overall wellbeing improved."


def test_non_hyphen_line_wraps_still_require_whitespace_boundary() -> None:
    # Ordinary line wraps (no trailing hyphen) must keep requiring a
    # whitespace boundary; two words separated only by page geometry, with no
    # space or hyphen, must not be silently mashed together.
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:1",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="randomly",
                        spatial=(20.0, 30.0, 400.0, 50.0),
                        reading_order=1,
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="assigned",
                        spatial=(20.0, 52.0, 400.0, 72.0),
                        reading_order=2,
                    ),
                ),
            ),
        ),
    )
    assert len(units) == 2


def test_trial_wide_canonical_block_does_not_inherit_result_id() -> None:
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:1",
        trial_id="trial:one",
        result_id="result:one",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="Trial-wide outcome statement",
                        spatial=(0, 0, 10, 10),
                        applicability=EvidenceApplicability.TRIAL_WIDE,
                        applicable_result_ids=("result:one", "result:two"),
                    ),
                ),
            ),
        ),
    )
    assert units[0].applicability is EvidenceApplicability.TRIAL_WIDE
    assert units[0].result_id is None
    assert units[0].applicable_result_ids == ("result:one", "result:two")


def test_uncertain_and_other_trial_discourse_remain_visible_with_warnings(
    tmp_path: Path,
) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    uncertain = _unit("unit:uncertain", "source:report", "allocation").model_copy(
        update={"discourse_scope": TrialDiscourseScope.UNCERTAIN}
    )
    other = _unit("unit:other", "source:report", "allocation", reading_order=1).model_copy(
        update={"discourse_scope": TrialDiscourseScope.OTHER}
    )
    index.replace_units((uncertain, other))
    scope = EvidenceScope(
        trial_id="trial:active",
        result_id="result:active",
        include_uncertain=True,
    )
    page = index.search(SearchQuery(terms=("allocation",)), scope=scope)
    assert {hit.unit.unit_id for hit in page.hits} == {uncertain.unit_id, other.unit_id}


def test_legacy_null_result_rows_migrate_to_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE evidence_units ("
            "unit_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
            "source_artifact_hash TEXT NOT NULL, parse_id TEXT NOT NULL, page INTEGER NOT NULL, "
            "kind TEXT NOT NULL, text TEXT NOT NULL, spatial TEXT, word_boxes TEXT, "
            "trial_id TEXT, result_id TEXT, "
            "document_zone TEXT)"
        )
        connection.execute(
            "INSERT INTO evidence_units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "unit:legacy",
                "source:legacy",
                HASH,
                "parse:legacy",
                1,
                "paragraph",
                "allocation",
                None,
                None,
                "trial:legacy",
                None,
                "methods",
            ),
        )
    unit = EvidenceSearchIndex(path).read_unit("unit:legacy")
    assert unit.applicability is EvidenceApplicability.UNRESOLVED


def _unit(
    unit_id: str,
    source_id: str,
    text: str,
    *,
    trial_id: str = "trial:active",
    result_id: str | None = "result:active",
    section: tuple[str, ...] = ("Methods",),
    zone: DocumentZone = DocumentZone.METHODS,
    discourse: TrialDiscourseScope = TrialDiscourseScope.ACTIVE,
    duplicate_group_id: str | None = None,
    reading_order: int = 0,
    domain_id: str | None = None,
    question_ids: tuple[str, ...] = (),
) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=unit_id,
        source_id=source_id,
        source_artifact_hash=HASH,
        parse_id=f"parse:{source_id.removeprefix('source:')}",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        trial_id=trial_id,
        result_id=result_id,
        domain_id=domain_id,
        question_ids=question_ids,
        section_path=section,
        reading_order=reading_order,
        document_zone=zone,
        discourse_scope=discourse,
        duplicate_group_id=duplicate_group_id,
    )


def test_scope_keeps_reference_and_other_trial_candidates_visible(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units(
        (
            _unit("unit:active", "source:report", "allocation concealed"),
            _unit(
                "unit:bibliography",
                "source:report",
                "allocation concealed",
                zone=DocumentZone.BIBLIOGRAPHY,
            ),
            _unit(
                "unit:other",
                "source:report",
                "allocation concealed",
                discourse=TrialDiscourseScope.OTHER,
            ),
            _unit(
                "unit:other-trial",
                "source:other",
                "allocation concealed",
                trial_id="trial:other",
                result_id="result:other",
            ),
        )
    )

    page = index.search(
        SearchQuery(terms=("allocation",)),
        scope=EvidenceScope(
            trial_id="trial:active",
            result_id="result:active",
            source_ids=("source:report",),
        ),
    )

    assert {hit.unit.unit_id for hit in page.hits} == {
        "unit:active",
        "unit:bibliography",
        "unit:other",
    }
    assert page.excluded_count == 1
    assert page.condition == "results"
    ordinary = index.search(SearchQuery(terms=("allocation",)))
    assert "unit:bibliography" in {hit.unit.unit_id for hit in ordinary.hits}
    assert "unit:active" in {hit.unit.unit_id for hit in ordinary.hits}
    bibliography_only = index.search(
        SearchQuery(terms=("allocation",), document_zones=(DocumentZone.BIBLIOGRAPHY,))
    )
    assert "unit:bibliography" in {hit.unit.unit_id for hit in bibliography_only.hits}

    unclassified = _unit("unit:unclassified", "source:report", "allocation")
    index.replace_units((unclassified,))
    assert index.search(
        SearchQuery(terms=("allocation",)),
        scope=EvidenceScope(
            trial_id="trial:active",
            result_id="result:active",
            domain_id="domain:randomization",
            allow_unclassified=True,
        ),
    ).hits


def test_unknown_or_missing_zone_remains_visible_with_diagnostic_warnings(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units(
        (
            _unit("unit:unknown", "source:report", "allocation", zone=DocumentZone.UNKNOWN),
            _unit("unit:missing", "source:report", "allocation", zone=None),
        )
    )
    page = index.search(
        SearchQuery(terms=("allocation",)),
        scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
    )
    assert {hit.unit.unit_id for hit in page.hits} == {"unit:unknown", "unit:missing"}
    assert page.condition == "results"
    assert all(any("document_zone" in warning for warning in hit.warnings) for hit in page.hits)


def test_domain_and_question_provenance_remains_visible_for_review(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units(
        (
            _unit("unit:no-domain", "source:report", "allocation"),
            _unit(
                "unit:no-question",
                "source:report",
                "allocation",
                domain_id="domain:randomization",
            ),
        )
    )
    page = index.search(
        SearchQuery(terms=("allocation",), question_id="sq:randomization:sequence"),
        scope=EvidenceScope(
            trial_id="trial:active",
            result_id="result:active",
            domain_id="domain:randomization",
            question_id="sq:randomization:sequence",
        ),
    )
    assert {hit.unit.unit_id for hit in page.hits} == {"unit:no-domain", "unit:no-question"}
    assert page.condition == "results"


def test_duplicate_groups_collapse_and_sources_are_diversified(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units(
        (
            _unit("unit:a1", "source:a", "allocation", duplicate_group_id="duplicate:one"),
            _unit("unit:b1", "source:b", "allocation"),
            _unit("unit:a2", "source:a", "allocation"),
        )
    )
    page = index.search(SearchQuery(terms=("allocation",)))

    assert [hit.unit.source_id for hit in page.hits] == ["source:a", "source:b", "source:a"]
    assert {hit.duplicate_group_id for hit in page.hits} == {None, "duplicate:one"}


def test_section_and_unit_reads_are_bounded_and_scope_safe(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = (
        _unit("unit:one", "source:report", "one", reading_order=1),
        _unit("unit:two", "source:report", "two", reading_order=2),
        _unit(
            "unit:other-section",
            "source:report",
            "three",
            section=("Results",),
            reading_order=3,
        ),
    )
    index.replace_units(units)
    scope = EvidenceScope(trial_id="trial:active", result_id="result:active")

    single = index.read_context(units[0].unit_id, mode=ReadContextMode.UNIT, scope=scope)
    section = index.read_context(units[0].unit_id, mode=ReadContextMode.SECTION, scope=scope)

    assert single.neighbors == ()
    assert [item.unit_id for item in section.neighbors] == [units[1].unit_id]
    assert section.mode is ReadContextMode.SECTION
    assert index.read_unit("unit:other-section", scope=EvidenceScope(trial_id="trial:other")) == (
        units[2]
    )


def test_neighbors_cross_semantic_labels_but_stop_at_structural_boundaries(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = (
        _unit("unit:target", "source:report", "target", reading_order=1).model_copy(
            update={"hierarchy_path": ("1",)}
        ),
        _unit("unit:same", "source:report", "same", reading_order=2).model_copy(
            update={"hierarchy_path": ("1",)}
        ),
        _unit(
            "unit:other-zone",
            "source:report",
            "other",
            zone=DocumentZone.RESULTS,
            discourse=TrialDiscourseScope.OTHER,
            reading_order=3,
        ).model_copy(update={"hierarchy_path": ("1",)}),
        _unit(
            "unit:other-section",
            "source:report",
            "other",
            section=("Results",),
            reading_order=4,
        ).model_copy(update={"hierarchy_path": ("2",)}),
        _unit("unit:far-same", "source:report", "far", reading_order=5).model_copy(
            update={"hierarchy_path": ("1",)}
        ),
    )
    index.replace_units(units)
    context = index.read_context(
        units[0].unit_id,
        mode=ReadContextMode.NEIGHBORS,
        neighbor_limit=6,
        scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
    )
    assert [item.unit_id for item in context.neighbors] == [units[1].unit_id, units[2].unit_id]
    assert "document_zone_boundary_crossed" in context.warnings
    assert "trial_discourse_boundary_crossed" in context.warnings
    assert "structural_boundary_reached" in context.warnings
    section = index.read_context(
        units[0].unit_id,
        mode=ReadContextMode.SECTION,
        scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
    )
    assert [item.unit_id for item in section.neighbors] == [units[1].unit_id, units[2].unit_id]
    assert "document_zone_boundary_crossed" in section.warnings
    assert "trial_discourse_boundary_crossed" in section.warnings
    assert "structural_boundary_reached" in section.warnings


def test_other_trial_parser_alias_is_excluded() -> None:
    assert RunEngine._canonical_discourse("other-trial", text="") is TrialDiscourseScope.OTHER
    assert RunEngine._canonical_discourse("other trial", text="") is TrialDiscourseScope.OTHER


def test_section_read_disables_expansion_without_structure(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    target = _unit("unit:unstructured", "source:report", "target").model_copy(
        update={"section_path": ()}
    )
    other = _unit("unit:structured", "source:report", "other", section=("Results",))
    index.replace_units((target, other))
    context = index.read_context(
        target.unit_id,
        mode=ReadContextMode.SECTION,
        scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
    )
    assert context.neighbors == ()
    assert context.continuation_cursor is None
    assert "structural_boundary_reached" in context.warnings


def test_section_cursor_advances_past_oversized_neighbors(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    target = _unit("unit:target", "source:report", "target", reading_order=1)
    oversized = _unit(
        "unit:oversized",
        "source:report",
        "allocation " + ("x" * 20_000),
        reading_order=2,
    )
    index.replace_units((target, oversized))
    first = index.read_context(
        target.unit_id,
        mode=ReadContextMode.SECTION,
        neighbor_limit=1,
        character_target=100,
        scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
    )
    assert first.neighbors == ()
    assert first.continuation_cursor is None
    assert "oversized_neighbor_skipped" in first.warnings


def test_generic_and_other_result_units_remain_visible_for_review(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    generic = _unit(
        "unit:generic",
        "source:report",
        "allocation context",
        result_id=None,
        domain_id=None,
    ).model_copy(
        update={
            "applicability": EvidenceApplicability.UNRESOLVED,
            "applicable_result_ids": ("result:a", "result:b"),
        }
    )
    result_a = _unit("unit:a", "source:report", "allocation result a", result_id="result:a")
    result_b = _unit("unit:b", "source:report", "allocation result b", result_id="result:b")
    index.replace_units((generic, result_a, result_b))
    page = index.search(
        SearchQuery(terms=("allocation",)),
        scope=EvidenceScope(
            trial_id="trial:active",
            result_id="result:b",
            allow_unclassified=True,
            include_uncertain=True,
        ),
    )
    hit_ids = {hit.unit.unit_id for hit in page.hits}
    assert hit_ids == {"unit:generic", "unit:a", "unit:b"}
    generic_hit = next(hit for hit in page.hits if hit.unit.unit_id == "unit:generic")
    assert generic_hit.unit.applicability is EvidenceApplicability.UNRESOLVED
    assert "result_scope_unresolved_units" in page.scope_warnings


def test_context_uses_stored_reading_order_with_unit_id_tie_breaker(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = (
        _unit("unit:z-target", "source:report", "target", reading_order=20),
        _unit("unit:a-before", "source:report", "before", reading_order=10),
        _unit("unit:y-after", "source:report", "after", reading_order=30),
    )
    index.replace_units(units)
    context = index.read_context(
        "unit:z-target",
        mode=ReadContextMode.SECTION,
        scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
    )
    assert [item.unit_id for item in context.neighbors] == ["unit:a-before", "unit:y-after"]


def test_read_and_search_share_identical_row_conversion(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    unit = _unit("unit:parity", "source:report", "allocation", reading_order=7)
    index.replace_units((unit,))
    hit_unit = index.search(SearchQuery(terms=("allocation",))).hits[0].unit
    read_unit = index.read_unit(unit.unit_id)
    assert hit_unit == read_unit == unit


def test_table_row_context_round_trips_with_headers_and_caption(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    unit = _unit("unit:table-row", "source:report", "Treatment | 0.8").model_copy(
        update={
            "kind": CanonicalUnitKind.TABLE_ROW,
            "table_headers": ("Arm", "Risk ratio"),
            "caption": "Mortality at 30 days",
        }
    )
    index.replace_units((unit,))
    assert index.read_unit(unit.unit_id) == unit


def test_index_initial_evidence_preserves_parser_provenance_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    class MetadataParser:
        name = "stub"
        version = "metadata"

        def parse(self, data, *, ocr_enabled, target_pages=None):
            return ParserResult(
                pages=(
                    PageExtraction(
                        page_number=1,
                        width=612,
                        height=792,
                        text="allocation was concealed",
                        section_path=("Methods", "Allocation"),
                        hierarchy_path=("2", "2.1"),
                        document_zone="methods",
                        discourse_scope="active",
                        text_items=(
                            PageTextItem(
                                text="allocation was concealed",
                                x=10,
                                y=20,
                                width=200,
                                height=12,
                                unit_kind="paragraph",
                                section_path=("Methods", "Allocation"),
                                hierarchy_path=("2", "2.1"),
                                reading_order=9,
                                document_zone="methods",
                                discourse_scope="active",
                                domain_id="domain:randomization",
                                question_ids=("sq:randomization:sequence",),
                            ),
                            PageTextItem(
                                text="allocation was concealed",
                                x=10,
                                y=40,
                                width=200,
                                height=12,
                                unit_kind="paragraph",
                                section_path=("Methods", "Allocation"),
                                hierarchy_path=("2", "2.1"),
                                reading_order=10,
                                document_zone="methods",
                                discourse_scope="active",
                                domain_id="domain:randomization",
                                question_ids=("sq:randomization:sequence",),
                            ),
                        ),
                    ),
                ),
                raw_output=data,
            )

    parsed_metadata = MetadataParser().parse(b"same-bytes", ocr_enabled=False)
    changed_metadata = parsed_metadata.model_copy(
        update={
            "pages": (
                parsed_metadata.pages[0].model_copy(
                    update={
                        "text_items": (
                            parsed_metadata.pages[0]
                            .text_items[0]
                            .model_copy(update={"domain_id": "domain:other"}),
                        )
                    },
                ),
            )
        }
    )
    assert _normalized_parse_output(
        parsed_metadata, source_id="source:trial-a-1"
    ) != _normalized_parse_output(changed_metadata, source_id="source:trial-a-1")

    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"metadata report")
    (tmp_path / "rob2.yaml").write_text(
        """
schema_version: 1
acquisition:
  clinicaltrials_gov: false
outcome_targets:
  - id: mortality
    label: mortality
    construct: mortality
    timepoint: 30 days
results:
  - result:
      result_id: result:trial-a-mortality
      trial_id: trial:trial-a
      randomization_id: randomization:trial-a
      comparison:
        experimental_arm_id: arm:treatment
        comparator_arm_id: arm:control
      effect_of_interest: assignment
      outcome_construct: Mortality
      measurement_instrument: Vital status
      time_point: 30 days
      analysis_population: Intention to treat
      analysis_model: Risk ratio
      effect_measure: RR
      source_locator: source:trial-a-1#result
    estimate:
      value: 0.8
    provenance_note: source:trial-a-1#result
""",
        encoding="utf-8",
    )
    engine = RunEngine(parser=MetadataParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None
    candidate = next(
        item
        for item in prepared.proposal.result_candidates
        if item.result_id == "result:trial-a-mortality"
    )
    review_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert review_work is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=review_work.work_token,
            idempotency_key="idempotency:metadata-index-review",
            selections=tuple(
                RunProposalSelection(
                    trial_id=source_candidate.trial_id,
                    source_id=source_candidate.source_id,
                    accepted=True,
                )
                for source_candidate in prepared.proposal.source_role_candidates
            ),
        )
    )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:metadata-index",
            selections=(
                RunProposalSelection(
                    trial_id=candidate.trial_id,
                    outcome_target_id=candidate.outcome_target_id,
                    result_id=candidate.result_id,
                    result_candidate_id=candidate.candidate_id,
                ),
            ),
        )
    )
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    page = index.search(
        SearchQuery(terms=("allocation",)),
        scope=EvidenceScope(
            trial_id="trial:trial-a",
            result_id="result:trial-a-mortality",
            domain_id="domain:randomization",
        ),
    )
    assert len(page.hits) == 1
    unit = page.hits[0].unit
    assert page.hits[0].duplicate_group_id is not None
    assert page.hits[0].duplicate_group_id.startswith("duplicate:")
    assert unit.section_path == ("Methods", "Allocation")
    assert unit.hierarchy_path == ("2", "2.1")
    assert unit.reading_order == 9
    assert unit.document_zone is DocumentZone.METHODS
    assert unit.domain_id == "domain:randomization"
    assert unit.question_ids == ("sq:randomization:sequence",)

    class OrdinaryParser:
        name = "stub"
        version = "ordinary"

        def parse(self, data, *, ocr_enabled, target_pages=None):
            return ParserResult(
                pages=(
                    PageExtraction(
                        page_number=1,
                        width=612,
                        height=792,
                        text="ordinary allocation prose",
                        text_items=(
                            PageTextItem(
                                text="ordinary allocation prose",
                                x=10,
                                y=20,
                                width=200,
                                height=12,
                            ),
                        ),
                    ),
                ),
                raw_output=data,
            )

    source = prepared.proposal.initialization.trials[0].inventory.sources[0]
    source_without_page_artifact = source.model_copy(
        update={
            "parse_records": tuple(
                record.model_copy(update={"page_artifact_hash": None})
                for record in source.parse_records
            )
        }
    )
    trial_without_page_artifact = prepared.proposal.initialization.trials[0].model_copy(
        update={
            "inventory": prepared.proposal.initialization.trials[0].inventory.model_copy(
                update={"sources": (source_without_page_artifact,)}
            )
        }
    )
    ordinary_initialization = prepared.proposal.initialization.model_copy(
        update={"trials": (trial_without_page_artifact,)}
    )
    engine._parser = OrdinaryParser()
    engine._index_initial_evidence(tmp_path, ordinary_initialization)
    ordinary_page = index.search(
        SearchQuery(terms=("allocation",)),
        scope=EvidenceScope(
            trial_id="trial:trial-a",
            result_id="result:trial-a-mortality",
            include_uncertain=True,
        ),
    )
    assert len(ordinary_page.hits) == 1
    assert ordinary_page.hits[0].unit.document_zone is DocumentZone.MAIN
    assert ordinary_page.hits[0].unit.kind is CanonicalUnitKind.UNCLASSIFIED
    engine._parser = MetadataParser()
    engine._index_initial_evidence(tmp_path, prepared.proposal.initialization)

    confirmed = engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:metadata-index-confirm",
            confirmed_by=Actor(
                kind=ActorKind.HUMAN,
                actor_id="actor:issue100",
                display_name="Issue 100",
            ),
        )
    )
    # Source-role review already resolved pre-confirmation (#119); the next
    # work item after confirmation is the first real preparation step.
    continued = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id))
    evidence_work = continued.work_item
    assert evidence_work is not None, (
        continued.run_state,
        continued.directive,
        continued.next_action,
        confirmed.run_state,
        continued.progress.blockers if continued.progress else None,
    )
    token_payload = evidence_work.work_token.model_dump(mode="json")
    monkeypatch.setattr(
        "rob2_kit.interfaces.mcp.server.RunEngine",
        lambda **_kwargs: engine,
    )
    server = create_server()

    async def invoke_read():
        return await server.call_tool(
            "read_evidence",
                {
                    "run_id": prepared.run_id,
                    "location_handle": page.hits[0].location_handle,
                "work_token": token_payload,
                "sq_id": "sq:randomization:sequence",
                "result_id": evidence_work.result_id,
                "mode": "unit",
            },
        )

    read_result = anyio.run(invoke_read)
    assert read_result.is_error is False
    assert read_result.structured_content is not None
    assert read_result.structured_content["unit"]["unit_id"] == unit.unit_id

    outside = unit.model_copy(
        update={
            "unit_id": "unit:outside-domain",
            "text": "outside-domain allocation was concealed",
            "domain_id": "domain:other",
            "duplicate_group_id": None,
        }
    )
    index.replace_units((unit, outside))
    refreshed = index.search(SearchQuery(terms=("allocation",)))
    handles = {hit.unit.unit_id: hit.location_handle for hit in refreshed.hits}

    async def invoke_boundary():
        return await server.call_tool(
            "read_evidence",
            {
                "run_id": prepared.run_id,
                "location_handle": handles[outside.unit_id],
                "work_token": token_payload,
                "sq_id": "sq:randomization:sequence",
                "result_id": evidence_work.result_id,
            },
        )

    boundary_result = anyio.run(invoke_boundary)
    assert boundary_result.is_error is False
    assert boundary_result.structured_content is not None
    assert boundary_result.structured_content["condition"] == "completed"
    assert boundary_result.structured_content["unit"]["unit_id"] == outside.unit_id

    wrong_token = dict(token_payload, domain_id="domain:other")

    async def invoke_wrong_scope():
        return await server.call_tool(
            "read_evidence",
            {
                "run_id": prepared.run_id,
                "location_handle": handles[unit.unit_id],
                "work_token": wrong_token,
                "sq_id": "sq:randomization:sequence",
                "result_id": evidence_work.result_id,
            },
        )

    wrong_scope_result = anyio.run(invoke_wrong_scope)
    assert wrong_scope_result.is_error is False
    assert wrong_scope_result.structured_content is not None
    assert wrong_scope_result.structured_content["condition"] == "retrieval_error"
    assert wrong_scope_result.structured_content["error"]["code"] == "stale_work_token"


def test_section_continuation_is_snapshot_and_unit_bound(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(
        _unit(f"unit:{number}", "source:report", f"text {number}") for number in range(1, 5)
    )
    index.replace_units(units)
    first = index.read_context(
        units[0].unit_id,
        mode=ReadContextMode.SECTION,
        neighbor_limit=1,
        scope=EvidenceScope(trial_id="trial:active"),
    )
    assert first.continuation_cursor is not None
    second = index.read_context(
        units[0].unit_id,
        mode=ReadContextMode.SECTION,
        neighbor_limit=1,
        cursor=first.continuation_cursor,
        scope=EvidenceScope(trial_id="trial:active"),
    )
    assert [item.unit_id for item in second.neighbors] == [units[2].unit_id]
    with pytest.raises(ValueError, match="different unit"):
        index.read_context(
            units[1].unit_id,
            mode=ReadContextMode.SECTION,
            cursor=first.continuation_cursor,
            scope=EvidenceScope(trial_id="trial:active"),
        )


def test_projection_is_versioned_and_remains_non_citable(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    unit = _unit("unit:projection", "source:report", "allocation")
    index.replace_units((unit,))
    hit = index.search(SearchQuery(terms=("allocation",))).hits[0]
    assert hit.projection.projection_version == "1.0.0"
    assert hit.projection.citable is False
    assert hit.projection.canonical_unit_id == hit.unit.unit_id
    assert canonical_hash(hit.unit.model_dump(mode="json"))


def test_public_retrieval_requests_require_a_work_token() -> None:
    with pytest.raises(ValidationError, match="work_token"):
        SearchEvidenceRequest.model_validate(
            {"run_id": "run:test", "query": {"terms": ["allocation"]}}
        )
    token = {
        "token": "token:test",
        "run_id": "run:test",
        "work_item_id": "work-item:test",
        "operation": "submit_domain_evidence",
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }
    with pytest.raises(ValidationError, match="policy"):
        SearchEvidenceRequest.model_validate(
            {
                "run_id": "run:test",
                "query": {"terms": ["allocation"]},
                "work_token": token,
                "policy": {"page_hit_target": 1},
            }
        )
    with pytest.raises(ValidationError, match="neighbor_limit"):
        ReadEvidenceRequest.model_validate(
            {
                "run_id": "run:test",
                "unit_id": "unit:test",
                "work_token": token,
                "neighbor_limit": 1,
            }
        )


def test_parser_extraction_preserves_structure_and_discourse_metadata() -> None:
    page = PageExtraction(
        page_number=1,
        width=612,
        height=792,
        text="Methods",
        section_path=("Methods", "Allocation"),
        hierarchy_path=("2", "2.1"),
        document_zone="methods",
        discourse_scope="active",
        text_items=(
            PageTextItem(
                text="Allocation was concealed.",
                x=10,
                y=20,
                width=200,
                height=12,
                unit_kind="paragraph",
                section_path=("Methods", "Allocation"),
                hierarchy_path=("2", "2.1"),
                reading_order=4,
                document_zone="methods",
                discourse_scope="active",
            ),
        ),
    )
    assert page.text_items[0].unit_kind == "paragraph"
    assert page.text_items[0].section_path == ("Methods", "Allocation")
    assert page.document_zone == "methods"
    assert _optional_metadata(None) is None
    assert _optional_metadata("  methods  ") == "methods"
    with pytest.raises(ValidationError, match="work_token"):
        ReadEvidenceRequest.model_validate({"run_id": "run:test", "unit_id": "unit:test"})


def test_zone_inference_requires_a_heading_not_a_prose_substring() -> None:
    assert (
        RunEngine._canonical_zone(
            None,
            page_text="This paragraph references previous work.",
        )
        is DocumentZone.UNKNOWN
    )
    assert RunEngine._canonical_zone(None, page_text="References\n") is DocumentZone.BIBLIOGRAPHY
    assert (
        RunEngine._canonical_zone(None, page_text="# Methods\nAllocation was concealed.")
        is DocumentZone.METHODS
    )
    assert (
        RunEngine._canonical_zone(None, page_text="Allocation was concealed.")
        is DocumentZone.UNKNOWN
    )


def test_search_cursor_is_bound_to_evidence_scope(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(_unit(f"unit:{number}", "source:report", "allocation") for number in range(1, 4))
    index.replace_units(units)
    first = index.search(
        SearchQuery(terms=("allocation",)),
        policy=SearchPolicy(page_hit_target=1),
        scope=EvidenceScope(trial_id="trial:active", work_token_id="work-token:one"),
    )
    assert first.next_cursor is not None
    with pytest.raises(ValueError, match="Evidence scope"):
        index.search(
            SearchQuery(terms=("allocation",)),
            policy=SearchPolicy(page_hit_target=1),
            cursor=first.next_cursor,
            scope=EvidenceScope(trial_id="trial:active", work_token_id="work-token:two"),
        )


def test_mcp_retrieval_routes_advertise_token_scope_and_read_modes() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    search = tools["search_evidence"].input_schema["properties"]
    read = tools["read_evidence"].input_schema["properties"]
    assert "work_token" in search
    assert "work_token" in read
    assert read["mode"]["$ref"].endswith("ReadContextMode")
    assert "WorkToken" in str(search["work_token"])


def test_mcp_tools_list_exposes_bounded_closed_search_query_schema() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    search_tool = tools["search_evidence"]
    query_schema = search_tool.input_schema["$defs"]["SearchQueryEnvelope"]
    properties = query_schema["properties"]

    assert query_schema["additionalProperties"] is False
    assert properties["terms"]["maxItems"] == 32
    assert properties["terms"]["examples"] == [["allocation"]]
    assert properties["kinds"]["items"]["$ref"].endswith("CanonicalUnitKind")
    assert properties["source_roles"]["items"]["$ref"].endswith("SourceRole")
    assert properties["document_zones"]["items"]["$ref"].endswith("DocumentZone")
    assert properties["kinds"]["description"]
    assert properties["source_roles"]["description"]
    assert properties["document_zones"]["description"]

    with pytest.raises(ValidationError):
        SearchQueryEnvelope.model_validate({"kinds": ["not-a-canonical-kind"]})
    with pytest.raises(ValidationError):
        SearchQueryEnvelope.model_validate({"document_zones": ["not-a-zone"]})


def test_search_query_and_transport_envelope_have_schema_parity() -> None:
    engine_schema = SearchQuery.model_json_schema()
    envelope_schema = SearchQueryEnvelope.model_json_schema()

    assert engine_schema["additionalProperties"] is False
    assert envelope_schema["additionalProperties"] is False
    assert engine_schema["properties"] == envelope_schema["properties"]


def test_mcp_search_semantic_query_errors_are_structured(monkeypatch) -> None:
    class FakeEngine:
        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr("rob2_kit.interfaces.mcp.server.RunEngine", FakeEngine)
    server = create_server()
    token = {
        "token": "token:mcp-search",
        "run_id": "run:mcp",
        "work_item_id": "work-item:mcp",
        "operation": RunOperation.SUBMIT_DOMAIN_EVIDENCE.value,
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }

    async def invoke():
        return await server.call_tool(
            "search_evidence",
            {
                "run_id": "run:mcp",
                "sq_id": "sq:randomization",
                "query": {"terms": ["allocation OR concealment"]},
                "work_token": token,
            },
        )

    result = anyio.run(invoke)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "invalid_request"


def test_mcp_retrieval_operational_failures_are_structured(monkeypatch) -> None:
    class LockedEngine:
        def __init__(self, **_kwargs):
            pass

        def search_evidence(self, _request):
            raise sqlite3.OperationalError("database is locked")

        def read_evidence(self, _request):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("rob2_kit.interfaces.mcp.server.RunEngine", LockedEngine)
    server = create_server()
    token = {
        "token": "token:mcp-locked",
        "run_id": "run:mcp",
        "work_item_id": "work-item:mcp",
        "operation": RunOperation.SUBMIT_DOMAIN_EVIDENCE.value,
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }

    async def invoke():
        return await server.call_tool(
            "search_evidence",
            {
                "run_id": "run:mcp",
                "sq_id": "sq:randomization",
                "query": {"terms": ["allocation"]},
                "work_token": token,
            },
        )

    result = anyio.run(invoke)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "retrieval_operational"


def test_mcp_read_evidence_executes_typed_route_deterministically(monkeypatch) -> None:
    unit = _unit("unit:mcp", "source:report", "allocation was concealed")
    context = EvidenceContext(
        snapshot_hash=HASH,
        unit=unit,
        character_count=len(unit.text),
        character_target=16_000,
        neighbor_limit=0,
        omitted_neighbor_count=0,
        mode=ReadContextMode.UNIT,
        section_path=unit.section_path,
    )
    captured = {}

    class FakeEngine:
        def __init__(self, **_kwargs):
            pass

        def read_evidence(self, request):
            captured["request"] = request
            return ReadEvidenceResponse(
                operation_id="operation:read-evidence",
                ledger_cursor="ledger:1",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.COMPLETED,
                committed=False,
                run_id=request.run_id,
                unit=unit,
                context=context,
            )

    monkeypatch.setattr("rob2_kit.interfaces.mcp.server.RunEngine", FakeEngine)
    server = create_server()
    token = {
        "token": "token:mcp-read",
        "run_id": "run:mcp",
        "work_item_id": "work-item:mcp",
        "operation": RunOperation.SUBMIT_DOMAIN_EVIDENCE.value,
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }

    async def invoke():
        return await server.call_tool(
            "read_evidence",
            {
                "run_id": "run:mcp",
                "location_handle": "location:mcp",
                "work_token": token,
                "sq_id": "sq:randomization",
                "mode": "unit",
            },
        )

    result = anyio.run(invoke)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["run_id"] == "run:mcp"
    assert result.structured_content["unit"]["unit_id"] == unit.unit_id
    assert result.structured_content["context"]["mode"] == "unit"
    assert captured["request"].work_token.token == token["token"]


def test_visual_handoff_requires_matching_domain_and_sq_on_same_source_page(
    monkeypatch, tmp_path: Path
) -> None:
    unit = _unit(
        "unit:visual-handoff",
        "source:report",
        "allocation was concealed",
        domain_id="domain:randomization",
        question_ids=("sq:randomization",),
    )
    context = EvidenceContext(
        snapshot_hash=HASH,
        unit=unit,
        character_count=len(unit.text),
        character_target=16_000,
        neighbor_limit=0,
        omitted_neighbor_count=0,
        mode=ReadContextMode.UNIT,
        section_path=unit.section_path,
    )

    def candidate(
        candidate_id: str,
        *,
        domain_id: str,
        sq_id: str,
        question_ids: tuple[str, ...],
    ) -> VisualCandidate:
        return VisualCandidate(
            candidate_id=candidate_id,
            source_id="source:report",
            source_artifact_hash=HASH,
            sq_id=sq_id,
            domain_id=domain_id,
            question_ids=question_ids,
            page=1,
            kind=VisualCandidateKind.TABLE,
            nomination_basis=VisualNominationBasis.RETRIEVED_REFERENCE,
            relevance_reason="The active SQ depends on the reported denominator.",
            initial_crop=CropBox(left=1, top=1, right=10, bottom=10),
            context_inside_crop=True,
        )

    candidates = (
        candidate(
            "visual:wrong-domain",
            domain_id="domain:other",
            sq_id="sq:randomization",
            question_ids=("sq:randomization",),
        ),
        candidate(
            "visual:wrong-sq",
            domain_id="domain:randomization",
            sq_id="sq:allocation",
            question_ids=("sq:allocation",),
        ),
        candidate(
            "visual:matching-domain-sq",
            domain_id="domain:randomization",
            sq_id="sq:randomization",
            question_ids=("sq:randomization",),
        ),
    )

    class FakeIndex:
        def __init__(self, _path):
            pass

        def read_location(self, *_args, **_kwargs):
            return EvidenceRead(
                snapshot_hash=HASH,
                unit=unit,
                text=unit.text,
                start=0,
                end=len(unit.text),
                character_target=16_000,
            )

        def read_context(self, *_args, **_kwargs):
            return context

    monkeypatch.setattr("rob2_kit.application.run_engine.EvidenceSearchIndex", FakeIndex)
    engine = RunEngine()

    class FakeLedger:
        def events(self):
            return ()

    ledger = FakeLedger()
    scope = EvidenceScope(
        result_id="result:active",
        domain_id="domain:randomization",
        question_id="sq:randomization",
    )
    engine._bound_ledger = lambda _run_id: ledger
    engine._required_root = lambda: tmp_path
    engine._retrieval_scope = lambda *_args, **_kwargs: scope
    engine._visual_candidates = lambda *_args, **_kwargs: candidates
    token = {
        "token": "token:visual-handoff",
        "run_id": "run:visual-handoff",
        "work_item_id": "work-item:visual-handoff",
        "operation": RunOperation.SUBMIT_DOMAIN_EVIDENCE.value,
        "dependency_fingerprint": HASH,
        "result_id": "result:active",
        "domain_id": "domain:randomization",
    }
    response = engine.read_evidence(
        ReadEvidenceRequest(
            run_id="run:visual-handoff",
            location_handle="location:visual-handoff",
            work_token=token,
            result_id="result:active",
            sq_id="sq:randomization",
        )
    )

    assert response.visual_inspection is not None
    assert response.visual_inspection.candidate_id == "visual:matching-domain-sq"
    assert response.visual_inspection.next_arguments.candidate_id == "visual:matching-domain-sq"
