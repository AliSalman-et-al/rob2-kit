"""Contract checks for the isolated ordered v2 Evidence-read batch seam."""

from __future__ import annotations

import pytest

from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceReadBatchItem,
    EvidenceReadBatchRequest,
    EvidenceReadBatchScope,
    EvidenceReadItemCondition,
    EvidenceReadPolicy,
    EvidenceSearchIndex,
    ReadContextMode,
    SearchQuery,
)


def _index(tmp_path):
    index = EvidenceSearchIndex(tmp_path / "read.sqlite3")
    snapshot = index.replace_units(
        (
            CanonicalEvidenceUnit(
                unit_id="unit:report-1",
                source_id="source:report",
                source_artifact_hash=canonical_hash({"source": 1}),
                parse_id="parse:report",
                page=1,
                kind=CanonicalUnitKind.PARAGRAPH,
                text="Allocation " + "source-authored text " * 150,
                fragment_ids=("fragment:report-1",),
            ),
        )
    )
    handle = index.search_v2(SearchQuery(terms=("allocation",))).candidates[0].location_handle
    return index, snapshot, handle


def test_v2_batch_packs_ordered_prefix_and_reports_item_conditions(tmp_path) -> None:
    index, snapshot, handle = _index(tmp_path)
    policy = EvidenceReadPolicy(item_ceiling=1, per_view_character_target=100)
    request = EvidenceReadBatchRequest(
        scope=EvidenceReadBatchScope(
            result_id="result:one", domain_id="domain:one", snapshot_hash=snapshot
        ),
        items=(
            EvidenceReadBatchItem(location_handle=handle, question_ids=("sq:one",)),
            EvidenceReadBatchItem(location_handle="loc:not-issued", question_ids=("sq:two",)),
        ),
    )
    first = index.read_batch_v2(request, policy=policy)
    assert len(first.outcomes) == 1
    assert first.outcomes[0].view is not None
    assert first.outcomes[0].view.continuation is not None
    assert first.outcomes[0].view.omitted_character_count > 0
    reviewed = index.resolve_read_view_receipt(first.outcomes[0].view.read_view_receipt)
    fragment = first.outcomes[0].view.fragments[0]
    assert reviewed.fragments[0].span_start == fragment.start
    assert reviewed.fragments[0].span_end == fragment.end
    assert reviewed.fragments[0].content_hash == fragment.text_hash
    assert reviewed.question_ids == ("sq:one",)
    assert reviewed.read_policy_id == policy.policy_id
    assert reviewed.read_policy_hash == canonical_hash(policy)
    assert first.serialized_response_bytes == len(canonical_json_bytes(first))
    assert first.continuation is not None
    second = index.read_batch_v2(
        request.model_copy(update={"continuation": first.continuation}), policy=policy
    )
    assert second.outcomes[0].condition is EvidenceReadItemCondition.STALE


def test_v2_batch_rejects_duplicate_handles_atomically(tmp_path) -> None:
    index, snapshot, handle = _index(tmp_path)
    with pytest.raises(ValueError, match="duplicate location handles"):
        EvidenceReadBatchRequest(
            scope=EvidenceReadBatchScope(
                result_id="result:one", domain_id="domain:one", snapshot_hash=snapshot
            ),
            items=(
                EvidenceReadBatchItem(location_handle=handle, question_ids=("sq:one",)),
                EvidenceReadBatchItem(location_handle=handle, question_ids=("sq:one",)),
            ),
        )


def test_oversized_section_target_terminates_without_restarting_its_context(tmp_path) -> None:
    index, snapshot, handle = _index(tmp_path)
    request = EvidenceReadBatchRequest(
        scope=EvidenceReadBatchScope(
            result_id="result:one", domain_id="domain:one", snapshot_hash=snapshot
        ),
        items=(
            EvidenceReadBatchItem(
                location_handle=handle,
                mode=ReadContextMode.SECTION,
                question_ids=("sq:one",),
            ),
        ),
    )
    policy = EvidenceReadPolicy(per_view_character_target=100)
    view = index.read_batch_v2(request, policy=policy).outcomes[0].view
    windows: list[str] = []
    for _ in range(32):
        assert view is not None
        windows.extend(fragment.text for fragment in view.fragments)
        if view.continuation is None:
            break
        view = (
            index.read_batch_v2(
                request.model_copy(
                    update={
                        "items": (
                            request.items[0].model_copy(
                                update={"continuation": view.continuation}
                            ),
                        )
                    }
                ),
                policy=policy,
            )
            .outcomes[0]
            .view
        )
    else:
        pytest.fail("oversized section target restarted instead of terminating")
    assert "".join(windows) == index.read_unit("unit:report-1").text


def test_v2_context_batch_keeps_distinct_fragments_and_resumes_section(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "context.sqlite3")
    units = tuple(
        CanonicalEvidenceUnit(
            unit_id=f"unit:context-{number}",
            source_id="source:context",
            source_artifact_hash=canonical_hash({"source": "context"}),
            parse_id="parse:context",
            page=1,
            kind=CanonicalUnitKind.PARAGRAPH,
            text=f"Allocation source-authored context {number}.",
            section_path=("Methods",),
            hierarchy_path=("Methods",),
            fragment_ids=(f"fragment:context-{number}",),
        )
        for number in range(10)
    )
    snapshot = index.replace_units(units)
    handle = index.search_v2(SearchQuery(terms=("allocation",))).candidates[0].location_handle
    request = EvidenceReadBatchRequest(
        scope=EvidenceReadBatchScope(
            result_id="result:context", domain_id="domain:context", snapshot_hash=snapshot
        ),
        items=(
            EvidenceReadBatchItem(
                location_handle=handle,
                mode=ReadContextMode.SECTION,
                question_ids=("sq:context",),
            ),
        ),
    )
    policy = EvidenceReadPolicy(per_view_character_target=500)
    first = index.read_batch_v2(request, policy=policy).outcomes[0].view
    assert first is not None
    assert len(first.fragments) > 1
    assert first.canonical_unit_id is None
    assert all(
        fragment.text.startswith("Allocation source-authored") for fragment in first.fragments
    )
    reviewed = index.resolve_read_view_receipt(first.read_view_receipt)
    assert tuple(fragment.canonical_unit_id for fragment in first.fragments) == tuple(
        fragment.unit_id for fragment in reviewed.fragments
    )
    assert first.continuation is not None
    assert first.omitted_fragment_count > 0
    resumed = (
        index.read_batch_v2(
            request.model_copy(
                update={
                    "items": (
                        request.items[0].model_copy(update={"continuation": first.continuation}),
                    )
                }
            ),
            policy=policy,
        )
        .outcomes[0]
        .view
    )
    assert resumed is not None
    assert resumed.fragments[0].canonical_unit_id == first.fragments[0].canonical_unit_id


def test_section_continuation_does_not_skip_an_oversized_following_fragment(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "section-oversized.sqlite3")
    units = (
        CanonicalEvidenceUnit(
            unit_id="unit:target",
            source_id="source:section",
            source_artifact_hash=canonical_hash({"source": "section"}),
            parse_id="parse:section",
            page=1,
            kind=CanonicalUnitKind.PARAGRAPH,
            text="Allocation target.",
            section_path=("Methods",),
            hierarchy_path=("Methods",),
            fragment_ids=("fragment:target",),
        ),
        CanonicalEvidenceUnit(
            unit_id="unit:oversized",
            source_id="source:section",
            source_artifact_hash=canonical_hash({"source": "section"}),
            parse_id="parse:section",
            page=1,
            kind=CanonicalUnitKind.PARAGRAPH,
            text="Allocation " + "source-authored " * 80,
            section_path=("Methods",),
            hierarchy_path=("Methods",),
            fragment_ids=("fragment:oversized",),
        ),
        CanonicalEvidenceUnit(
            unit_id="unit:tail",
            source_id="source:section",
            source_artifact_hash=canonical_hash({"source": "section"}),
            parse_id="parse:section",
            page=1,
            kind=CanonicalUnitKind.PARAGRAPH,
            text="Tail evidence must be reached after the oversized unit.",
            section_path=("Methods",),
            hierarchy_path=("Methods",),
            fragment_ids=("fragment:tail",),
        ),
    )
    index.replace_units(units)
    first = index.read_context(
        "unit:target", mode=ReadContextMode.SECTION, character_target=100
    )
    assert first.continuation_cursor is not None
    deferred = index.read_context(
        "unit:target",
        mode=ReadContextMode.SECTION,
        character_target=100,
        cursor=first.continuation_cursor,
    )
    assert deferred.unit.unit_id == "unit:oversized"
    assert deferred.continuation_cursor is not None

    snapshot = index._snapshot()
    handle = next(
        candidate.location_handle
        for candidate in index.search_v2(SearchQuery(terms=("allocation",))).candidates
        if candidate.canonical_unit_id == "unit:target"
    )
    request = EvidenceReadBatchRequest(
        scope=EvidenceReadBatchScope(
            result_id="result:section", domain_id="domain:section", snapshot_hash=snapshot
        ),
        items=(
            EvidenceReadBatchItem(
                location_handle=handle,
                mode=ReadContextMode.SECTION,
                question_ids=("sq:section",),
            ),
        ),
    )
    policy = EvidenceReadPolicy(per_view_character_target=100)
    current = index.read_batch_v2(request, policy=policy).outcomes[0].view
    oversized_windows: list[tuple[int, int, str]] = []
    tail_windows: list[str] = []
    for _ in range(32):
        assert current is not None
        assert all(
            len(fragment.text) <= policy.per_view_character_target
            for fragment in current.fragments
        )
        oversized_windows.extend(
            (fragment.start, fragment.end, fragment.text)
            for fragment in current.fragments
            if fragment.canonical_unit_id == "unit:oversized"
        )
        tail_windows.extend(
            fragment.text
            for fragment in current.fragments
            if fragment.canonical_unit_id == "unit:tail"
        )
        if current.continuation is None:
            break
        current = (
            index.read_batch_v2(
                request.model_copy(
                    update={
                        "items": (
                            request.items[0].model_copy(
                                update={"continuation": current.continuation}
                            ),
                        )
                    }
                ),
                policy=policy,
            )
            .outcomes[0]
            .view
        )
    else:
        pytest.fail("section continuation did not terminate")
    assert oversized_windows == sorted(oversized_windows)
    assert "".join(text for _, _, text in oversized_windows) == units[1].text
    assert tail_windows == [units[2].text]
