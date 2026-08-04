from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.evidence import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    DocumentZone,
    EvidenceScope,
    EvidenceSearchIndex,
    ReadContextMode,
    SearchQuery,
    TrialDiscourseScope,
)
from rob2_kit.interfaces.mcp.server import create_server

HASH = "sha256:" + "a" * 64


def _unit(
    unit_id: str,
    source_id: str,
    text: str,
    *,
    trial_id: str = "trial:active",
    result_id: str = "result:active",
    section: tuple[str, ...] = ("Methods",),
    zone: DocumentZone = DocumentZone.METHODS,
    discourse: TrialDiscourseScope = TrialDiscourseScope.ACTIVE,
    duplicate_group_id: str | None = None,
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
        section_path=section,
        document_zone=zone,
        discourse_scope=discourse,
        duplicate_group_id=duplicate_group_id,
    )


def test_scope_excludes_reference_zones_and_other_trial_discourse(tmp_path: Path) -> None:
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

    assert [hit.unit.unit_id for hit in page.hits] == ["unit:active"]
    assert page.excluded_count == 3
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
        _unit("unit:one", "source:report", "one"),
        _unit("unit:two", "source:report", "two"),
        _unit("unit:other-section", "source:report", "three", section=("Results",)),
    )
    index.replace_units(units)
    scope = EvidenceScope(trial_id="trial:active", result_id="result:active")

    single = index.read_context(units[0].unit_id, mode=ReadContextMode.UNIT, scope=scope)
    section = index.read_context(units[0].unit_id, mode=ReadContextMode.SECTION, scope=scope)

    assert single.neighbors == ()
    assert [item.unit_id for item in section.neighbors] == [units[1].unit_id]
    assert section.mode is ReadContextMode.SECTION
    with pytest.raises(ValueError, match="outside"):
        index.read_unit("unit:other-section", scope=EvidenceScope(trial_id="trial:other"))


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


def test_mcp_retrieval_routes_advertise_token_scope_and_read_modes() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    search = tools["search_evidence"].input_schema["properties"]
    read = tools["read_evidence"].input_schema["properties"]
    assert "work_token" in search
    assert "work_token" in read
    assert read["mode"]["$ref"].endswith("ReadContextMode")
    assert "WorkToken" in str(search["work_token"])
