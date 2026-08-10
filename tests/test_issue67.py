from __future__ import annotations

from pathlib import Path

from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.domain.sources import CoverageState
from rob2_kit.evidence import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    VisualCandidateDisposition,
    VisualCandidateDispositionKind,
    build_visual_citation,
    materialize_evidence_claim,
)
from rob2_kit.ingestion import PageExtraction, ParserResult, initialize_project
from rob2_kit.storage import ArtifactStore

ACTOR = Actor(
    kind=ActorKind.SYSTEM,
    actor_id="actor:issue-67-tests",
    display_name="Issue 67 tests",
)


def _page(number: int, text: str, *reasons: str) -> PageExtraction:
    return PageExtraction(
        page_number=number,
        width=612,
        height=792,
        text=text,
        reasons=reasons,
    )


class _Parser:
    name = "issue-67-parser"
    version = "1"

    def __init__(
        self,
        initial: tuple[PageExtraction, ...],
        recovered: tuple[PageExtraction, ...],
        *,
        initial_by_data: dict[bytes, tuple[PageExtraction, ...]] | None = None,
    ):
        self.initial = initial
        self.recovered = recovered
        self.initial_by_data = initial_by_data or {}
        self.calls: list[tuple[bool, tuple[int, ...] | None]] = []

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult:
        self.calls.append((ocr_enabled, target_pages))
        pages = self.recovered if ocr_enabled else self.initial_by_data.get(data, self.initial)
        return ParserResult(pages=pages, raw_output=data + bytes([len(self.calls)]))


def test_parse_record_and_coverage_bind_before_after_parser_revisions(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    parser = _Parser(
        (
            _page(1, "text", "future-reason"),
            _page(2, "", "no-text"),
        ),
        (_page(2, "recovered"),),
    )

    initialized = initialize_project(tmp_path, actor=ACTOR, parser=parser)
    source = initialized.trials[0].inventory.sources[0]

    assert parser.calls == [(False, None), (True, (2,))]
    assert len(source.parse_records) == 2
    initial, recovery = source.parse_records
    assert initial.artifact_hash == source.artifact_hash
    assert initial.output_artifact_hash is not None
    assert recovery.output_artifact_hash is not None
    output_store = ArtifactStore(tmp_path / ".rob2" / "artifacts")
    assert output_store.read(initial.output_artifact_hash) == b"report\x01"
    assert initial.page_count == 2
    assert initial.page_numbers == (1, 2)
    assert dict(initial.configuration)["ocr_enabled"] == "false"
    assert source.coverage[0].parse_id == initial.parse_id
    assert source.coverage[0].artifact_hash == source.artifact_hash
    assert source.coverage[0].recovery_parse_id is None
    assert source.coverage[0].before_state is CoverageState.TEXT_USABLE
    assert source.coverage[1].recovery_parse_id == recovery.parse_id
    assert source.coverage[1].before_state is CoverageState.RECOVERY_REQUIRED
    assert source.coverage[1].state is CoverageState.TEXT_USABLE
    assert "unknown-reason:future-reason" in source.coverage[0].diagnostics


def test_supporting_recovery_is_limited_to_declared_decision_pages(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    supplement_dir = trial / "supplements"
    supplement_dir.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    (supplement_dir / "scan.pdf").write_bytes(b"scan")
    (trial / "trial.yaml").write_text(
        "schema_version: 1\n"
        "documents:\n"
        "  - path: supplements/scan.pdf\n"
        "    role: supplement\n"
        "    decision_relevant_pages: [2]\n",
        encoding="utf-8",
    )
    parser = _Parser(
        (_page(1, "report"),),
        (_page(2, "recovered"),),
        initial_by_data={b"scan": (_page(1, "", "scanned"), _page(2, "", "scanned"))},
    )

    initialized = initialize_project(tmp_path, actor=ACTOR, parser=parser)

    assert parser.calls == [(False, None), (False, None), (True, (2,))]
    scan = next(
        source
        for source in initialized.trials[0].inventory.sources
        if source.relative_path == "supplements/scan.pdf"
    )
    assert scan.coverage[0].state is CoverageState.RECOVERY_REQUIRED
    assert scan.coverage[1].state is CoverageState.TEXT_USABLE


def test_whole_primary_ocr_requires_representative_scanned_pages(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    parser = _Parser(
        (
            _page(1, "", "scanned"),
            _page(2, "", "scanned"),
            _page(3, "", "scanned"),
        ),
        (
            _page(1, "one"),
            _page(2, "two"),
            _page(3, "three"),
        ),
    )

    initialize_project(tmp_path, actor=ACTOR, parser=parser)

    assert parser.calls == [(False, None), (True, (1, 2, 3))]


def test_spatial_canonical_span_produces_deterministic_visual_citation() -> None:
    unit = CanonicalEvidenceUnit(
        unit_id="unit:report-p1-b1",
        source_id="source:report",
        source_artifact_hash="sha256:" + "a" * 64,
        parse_id="parse:report-initial",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text="42 of 51 randomized participants were analysed.",
        spatial=(72.0, 100.0, 420.0, 130.0),
    )

    first = build_visual_citation(unit, span_start=0, span_end=10)
    second = build_visual_citation(unit, span_start=0, span_end=10)

    assert first == second
    assert first.agent_inspected is False
    assert first.quoted_text_hash.startswith("sha256:")
    assert first.render.crop == first.boxes[0]

    claim = materialize_evidence_claim(
        claim_id="claim:report-p1-b1",
        unit=unit,
        span_start=0,
        span_end=10,
        claim_type="claim-type:denominator",
    )
    assert build_visual_citation(claim, span_start=0, span_end=10) == first

    offset_claim = materialize_evidence_claim(
        claim_id="claim:report-p1-b1-offset",
        unit=unit,
        span_start=7,
        span_end=17,
        claim_type="claim-type:denominator",
    )
    offset_citation = build_visual_citation(
        offset_claim,
        span_start=7,
        span_end=17,
    )
    assert offset_citation.span_start == 7
    assert offset_citation.span_end == 17
    assert offset_citation.quoted_text_hash == offset_claim.quoted_text_hash


def test_liteparse_screenshot_returns_hash_bound_png(monkeypatch) -> None:
    class Screenshot:
        page_num = 1
        width = 1224
        height = 1584
        image_bytes = b"\x89PNG issue-67"

    class FakeLiteParse:
        def __init__(self, **kwargs):
            assert kwargs["dpi"] == 144.0
            assert kwargs["render_form_fields"] is False

        def screenshot(self, path, *, page_numbers):
            assert path.exists()
            assert page_numbers == [1]
            return [Screenshot()]

    monkeypatch.setattr("liteparse.LiteParse", FakeLiteParse)
    from rob2_kit.ingestion import LiteParseAdapter

    render = LiteParseAdapter().screenshot(b"%PDF", page_numbers=(1,), dpi=144)[0]

    assert render.image_hash.startswith("sha256:")
    assert render.pixel_width == 1224
    assert render.media_type == "image/png"


def test_visual_disposition_rejects_unscoped_metadata() -> None:
    try:
        VisualCandidateDisposition(
            candidate_id="visual:one",
            kind=VisualCandidateDispositionKind.INSPECTED_IRRELEVANT,
            limitation="not allowed",
        )
    except ValueError as error:
        assert "only ambiguous" in str(error)
    else:
        raise AssertionError("non-ambiguous visual dispositions must not carry limitations")
