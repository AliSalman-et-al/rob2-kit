"""Parser/index custody regressions retained after the v3 evidence migration (#152)."""

import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import ReadEvidenceResponse, SearchEvidenceResponse
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    SearchQuery,
)
from rob2_kit.ingestion.project import PageTextItem

HASH = "sha256:" + "a" * 64


def _unit(*, text: str = "allocation was concealed") -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id="unit:source-report",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        section_path=("Methods",),
        hierarchy_path=("1",),
        reading_order=1,
        fragment_ids=("fragment:report-1",),
    )


@pytest.mark.parametrize("field", ("trial_id", "result_id", "domain_id", "question_ids"))
def test_parser_and_units_reject_scientific_scope_fields(field: str) -> None:
    payload = {"text": "source text", "x": 1, "y": 1, "width": 10, "height": 10, field: "x"}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PageTextItem.model_validate(payload)
    canonical = _unit().model_dump()
    canonical[field] = "x"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CanonicalEvidenceUnit.model_validate(canonical)


def test_search_query_remains_closed_to_removed_scientific_refinements() -> None:
    for field in ("trial_id", "result_id", "domain_id", "question_id", "source_roles"):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            SearchQuery.model_validate({"terms": ["allocation"], field: "forbidden"})


def test_retrieval_responses_do_not_accept_a_caller_chosen_schema_identity() -> None:
    for response_type in (SearchEvidenceResponse, ReadEvidenceResponse):
        assert "retrieval_schema_version" not in response_type.model_json_schema()["properties"]


def test_failed_physical_replacement_preserves_the_last_usable_index(tmp_path, monkeypatch) -> None:
    path = tmp_path / "crash-safe.sqlite3"
    index = EvidenceSearchIndex(path)
    original = _unit(text="original allocation")
    index.replace_units((original,))
    before = path.read_bytes()

    def fail_replace(_source, _destination):
        raise PermissionError("simulated Windows sharing violation")

    monkeypatch.setattr("rob2_kit.evidence.search.os.replace", fail_replace)
    with pytest.raises(PermissionError, match="sharing violation"):
        index.replace_units((_unit(text="replacement allocation"),))

    assert path.read_bytes() == before
    assert index.read_unit(original.unit_id) == original
    assert not tuple(tmp_path.glob("crash-safe.sqlite3.*.next"))
