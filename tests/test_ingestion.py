from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import yaml

from rob2_kit.application.preparation import TrialFailureReason
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.domain.sources import (
    CoverageState,
    SourceAvailability,
    SourceCriticality,
    SourceProcessing,
    SourceRole,
    SourceUse,
)
from rob2_kit.ingestion import (
    BoundedZipError,
    LiteParseAdapter,
    PageExtraction,
    ParserResult,
    SourceParseError,
    initialize_project,
    read_bounded_zip,
)

ACTOR = Actor(kind=ActorKind.SYSTEM, actor_id="actor:test", display_name="Test system")


@dataclass
class StubParser:
    pages: dict[str, tuple[PageExtraction, ...]]
    failures: set[str] = field(default_factory=set)
    calls: list[tuple[str, bool, tuple[int, ...] | None]] = field(default_factory=list)

    name: str = "stubparse"
    version: str = "1.0"

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult:
        key = data.decode()
        self.calls.append((key, ocr_enabled, target_pages))
        if key in self.failures:
            raise SourceParseError(f"cannot parse {key}")
        pages = self.pages[key]
        if target_pages is not None:
            pages = tuple(page for page in pages if page.page_number in target_pages)
        if ocr_enabled:
            pages = tuple(
                PageExtraction(
                    page_number=page.page_number,
                    width=page.width,
                    height=page.height,
                    text=f"recovered page {page.page_number}",
                    reasons=(),
                )
                for page in pages
            )
        return ParserResult(pages=pages, raw_output=b"canonical parser output")


def page(
    number: int,
    text: str,
    *reasons: str,
) -> PageExtraction:
    return PageExtraction(
        page_number=number,
        width=612,
        height=792,
        text=text,
        reasons=reasons,
    )


def test_initialization_discovers_classifies_and_deduplicates_supplied_sources(
    tmp_path: Path,
) -> None:
    project = tmp_path / "review"
    trial = project / "input" / "trial-a"
    supplements = trial / "supplements"
    supplements.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    (supplements / "protocol.pdf").write_bytes(b"shared")
    (supplements / "sap-copy.pdf").write_bytes(b"shared")
    (supplements / "notes.docx").write_bytes(b"unsupported")
    (trial / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "documents": [
                    {"path": "report.pdf", "roles": ["primary_report"]},
                    {
                        "path": "supplements/protocol.pdf",
                        "roles": ["protocol", "statistical_analysis_plan"],
                        "components": [
                            {"pages": [1, 2], "roles": ["protocol"]},
                            {"pages": [3, 4], "roles": ["statistical_analysis_plan"]},
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    parser = StubParser(
        {
            "report": (page(1, "Trial report"),),
            "shared": (page(1, "Protocol"), page(2, "Methods")),
        }
    )

    result = initialize_project(project, actor=ACTOR, parser=parser)

    assert (project / "output").is_dir()
    assert (project / ".rob2" / "artifacts").is_dir()
    assert result.manifest.project_name == "review"
    initialized = result.trials[0]
    assert initialized.status == "inventory_ready"
    assert len(initialized.inventory.sources) == 4

    report = next(
        source for source in initialized.inventory.sources if source.title == "report.pdf"
    )
    protocol = next(
        source for source in initialized.inventory.sources if source.title == "protocol.pdf"
    )
    copy = next(
        source for source in initialized.inventory.sources if source.title == "sap-copy.pdf"
    )
    unsupported = next(
        source for source in initialized.inventory.sources if source.title == "notes.docx"
    )

    assert report.roles == (SourceRole.PRIMARY_REPORT,)
    assert report.criticality is SourceCriticality.REQUIRED
    assert report.availability is SourceAvailability.ACQUIRED
    assert report.processing is SourceProcessing.USABLE
    assert report.use is SourceUse.NOT_SEARCHED
    assert protocol.roles == (SourceRole.PROTOCOL, SourceRole.STATISTICAL_ANALYSIS_PLAN)
    assert protocol.artifact_hash == copy.artifact_hash
    assert len(protocol.components) == 2
    assert unsupported.availability is SourceAvailability.ACQUIRED
    assert unsupported.processing is SourceProcessing.FAILED
    assert unsupported.failure_category == "unsupported_format"
    assert len(result.acquisition_receipts) == 4


def test_project_configuration_declares_multiple_exact_results_per_trial(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "outcome_targets": [
                    {"id": "mortality-30d", "label": "Mortality at 30 days"},
                    {"id": "readmission-90d", "label": "Readmission at 90 days"},
                ],
                "results": [
                    {
                        "result": {
                            "result_id": "result:trial-a-mortality-30d",
                            "trial_id": "trial:trial-a",
                            "randomization_id": "randomization:trial-a",
                            "comparison": {
                                "experimental_arm_id": "arm:treatment",
                                "comparator_arm_id": "arm:control",
                            },
                            "effect_of_interest": "assignment",
                            "outcome_construct": "Mortality",
                            "measurement_instrument": "Vital status",
                            "time_point": "30 days",
                            "analysis_population": "Intention to treat",
                            "analysis_model": "Risk ratio, unadjusted",
                            "effect_measure": "RR",
                            "source_locator": "report.pdf p. 8 table 2",
                        },
                        "estimate": {"value": "0.82"},
                        "provenance_note": "Protocol-defined primary result.",
                    },
                    {
                        "result": {
                            "result_id": "result:trial-a-readmission-90d",
                            "trial_id": "trial:trial-a",
                            "randomization_id": "randomization:trial-a",
                            "comparison": {
                                "experimental_arm_id": "arm:treatment",
                                "comparator_arm_id": "arm:control",
                            },
                            "effect_of_interest": "assignment",
                            "outcome_construct": "Readmission",
                            "measurement_instrument": "Hospital record",
                            "time_point": "90 days",
                            "analysis_population": "Intention to treat",
                            "analysis_model": "Risk ratio, unadjusted",
                            "effect_measure": "RR",
                            "source_locator": "report.pdf p. 9 table 3",
                        },
                        "estimate": {"value": "0.91"},
                        "provenance_note": "Protocol-defined secondary result.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    initialized = initialize_project(
        tmp_path,
        actor=ACTOR,
        parser=StubParser({"report": (page(1, "Report"),)}),
    )

    assert initialized.manifest.outcome_targets == (
        "mortality-30d",
        "readmission-90d",
    )
    assert [item.result.result_id for item in initialized.result_specs] == [
        "result:trial-a-mortality-30d",
        "result:trial-a-readmission-90d",
    ]
    assert initialized.result_specs[0].result.source_locator == "report.pdf p. 8 table 2"


def test_multiple_primary_candidates_are_nonblocking_and_trial_yaml_disambiguates(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "a.pdf").write_bytes(b"a")
    (trial / "b.pdf").write_bytes(b"b")
    parser = StubParser({"a": (page(1, "A"),), "b": (page(1, "B"),)})

    ambiguous = initialize_project(tmp_path, actor=ACTOR, parser=parser)

    inventory = ambiguous.trials[0].inventory
    assert (
        sum(
            SourceRole.PRIMARY_REPORT in source.roles
            and source.criticality is SourceCriticality.REQUIRED
            for source in inventory.sources
        )
        == 1
    )
    assert any(finding.kind == "primary_report_ambiguous" for finding in ambiguous.review_findings)

    (trial / "trial.yaml").write_text(
        "schema_version: 1\ndocuments:\n  - path: b.pdf\n    role: primary_report\n",
        encoding="utf-8",
    )
    explicit = initialize_project(tmp_path, actor=ACTOR, parser=parser)

    primary = next(
        source
        for source in explicit.trials[0].inventory.sources
        if source.criticality is SourceCriticality.REQUIRED
    )
    assert primary.title == "b.pdf"
    assert not any(
        finding.kind == "primary_report_ambiguous" for finding in explicit.review_findings
    )


def test_liteparse_coverage_uses_one_targeted_recovery_and_preserves_diagnostics(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    parser = StubParser(
        {
            "report": (
                page(1, "Usable born-digital text", "multi-column"),
                page(2, "", "no-text", "future-reason"),
                page(3, "", "intentionally-blank"),
                page(4, "\ufffd\ufffd broken", "garbled"),
            )
        }
    )

    result = initialize_project(tmp_path, actor=ACTOR, parser=parser)

    source = result.trials[0].inventory.sources[0]
    states = tuple(item.state for item in source.coverage)
    assert states == (
        CoverageState.TEXT_USABLE,
        CoverageState.TEXT_USABLE,
        CoverageState.INTENTIONALLY_BLANK,
        CoverageState.COVERAGE_LIMITED,
    )
    assert parser.calls == [
        ("report", False, None),
        ("report", True, (2,)),
    ]
    assert len(source.parse_records) == 2
    assert source.parse_records[0].ocr_enabled is False
    assert source.parse_records[1].ocr_enabled is True
    assert source.parse_records[1].target_pages == (2,)
    assert "future-reason" in source.coverage[1].diagnostics


def test_supporting_pdf_recovery_waits_for_decision_relevance(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    supplements = trial / "supplements"
    supplements.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    (supplements / "scan.pdf").write_bytes(b"scan")
    parser = StubParser(
        {
            "report": (page(1, "Report"),),
            "scan": (page(1, "", "scanned"),),
        }
    )

    result = initialize_project(tmp_path, actor=ACTOR, parser=parser)

    scan = next(
        source for source in result.trials[0].inventory.sources if source.title == "scan.pdf"
    )
    assert scan.coverage[0].state is CoverageState.RECOVERY_REQUIRED
    assert ("scan", True, (1,)) not in parser.calls


def test_required_primary_with_no_recoverable_page_is_trial_failed(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")

    class UnrecoverableParser(StubParser):
        def parse(
            self,
            data: bytes,
            *,
            ocr_enabled: bool,
            target_pages: tuple[int, ...] | None = None,
        ) -> ParserResult:
            self.calls.append((data.decode(), ocr_enabled, target_pages))
            return ParserResult(
                pages=(page(1, "", "scanned"),),
                raw_output=b"empty parse",
            )

    result = initialize_project(
        tmp_path,
        actor=ACTOR,
        parser=UnrecoverableParser({}),
    )

    assert result.trials[0].status == "trial_failed"


def test_unexpected_parser_bug_is_not_converted_to_source_failure(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")

    class BrokenAdapter(StubParser):
        def parse(
            self,
            data: bytes,
            *,
            ocr_enabled: bool,
            target_pages: tuple[int, ...] | None = None,
        ) -> ParserResult:
            raise AssertionError("adapter invariant failed")

    with pytest.raises(AssertionError, match="invariant"):
        initialize_project(tmp_path, actor=ACTOR, parser=BrokenAdapter({}))


def test_missing_primary_fails_only_its_trial_and_batch_continues(tmp_path: Path) -> None:
    missing_supplements = tmp_path / "input" / "missing" / "supplements"
    missing_supplements.mkdir(parents=True)
    (missing_supplements / "protocol.pdf").write_bytes(b"protocol")
    valid = tmp_path / "input" / "valid"
    valid.mkdir(parents=True)
    (valid / "report.pdf").write_bytes(b"report")
    parser = StubParser(
        {
            "protocol": (page(1, "Protocol"),),
            "report": (page(1, "Report"),),
        }
    )

    result = initialize_project(tmp_path, actor=ACTOR, parser=parser)

    assert [trial.status for trial in result.trials] == ["trial_failed", "inventory_ready"]
    missing = result.trials[0].inventory.sources[0]
    assert missing.availability is SourceAvailability.UNAVAILABLE
    assert missing.processing is SourceProcessing.NOT_ATTEMPTED


def test_optional_acquisition_failure_has_receipt_and_is_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    supplements = trial / "supplements"
    supplements.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    broken_path = supplements / "broken.pdf"
    broken_path.write_bytes(b"broken")
    original_read_bytes = Path.read_bytes

    def selective_read(path: Path) -> bytes:
        if path == broken_path:
            raise PermissionError("access denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", selective_read)

    result = initialize_project(
        tmp_path,
        actor=ACTOR,
        parser=StubParser({"report": (page(1, "Report"),)}),
    )

    assert result.trials[0].status == "inventory_ready"
    broken = next(
        source for source in result.trials[0].inventory.sources if source.title == "broken.pdf"
    )
    assert broken.availability is SourceAvailability.ACQUISITION_FAILED
    assert broken.processing is SourceProcessing.NOT_ATTEMPTED
    receipt = next(
        item for item in result.acquisition_receipts if item.source_id == broken.source_id
    )
    assert receipt.outcome.value == "failed"


def test_required_primary_failure_is_trial_failed_but_optional_failure_is_nonfatal(
    tmp_path: Path,
) -> None:
    required_trial = tmp_path / "required" / "input" / "trial-a"
    required_trial.mkdir(parents=True)
    (required_trial / "report.pdf").write_bytes(b"corrupt")
    required = initialize_project(
        tmp_path / "required",
        actor=ACTOR,
        parser=StubParser({}, failures={"corrupt"}),
    )

    assert required.trials[0].status == "trial_failed"
    failure = required.trials[0].failure
    assert failure is not None
    assert failure.reason is TrialFailureReason.REQUIRED_PRIMARY_UNRECOVERABLE

    optional_trial = tmp_path / "optional" / "input" / "trial-a"
    supplements = optional_trial / "supplements"
    supplements.mkdir(parents=True)
    (optional_trial / "report.pdf").write_bytes(b"report")
    (supplements / "broken.pdf").write_bytes(b"broken")
    optional = initialize_project(
        tmp_path / "optional",
        actor=ACTOR,
        parser=StubParser(
            {"report": (page(1, "Report"),)},
            failures={"broken"},
        ),
    )

    assert optional.trials[0].status == "inventory_ready"
    broken = next(
        source for source in optional.trials[0].inventory.sources if source.title == "broken.pdf"
    )
    assert broken.processing is SourceProcessing.FAILED
    assert any(
        finding.kind == "optional_source_processing_failed" for finding in optional.review_findings
    )


def test_bounded_zip_accepts_safe_pdf_members_and_rejects_container_attacks() -> None:
    safe = BytesIO()
    with ZipFile(safe, "w", ZIP_DEFLATED) as archive:
        archive.writestr("protocol.pdf", b"protocol")
        archive.writestr("nested/sap.pdf", b"sap")

    members = read_bounded_zip(safe.getvalue(), max_members=2, max_expanded_bytes=11)

    assert members == {"nested/sap.pdf": b"sap", "protocol.pdf": b"protocol"}

    traversal = BytesIO()
    with ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.pdf", b"bad")
    with pytest.raises(BoundedZipError, match="unsafe"):
        read_bounded_zip(traversal.getvalue())

    with pytest.raises(BoundedZipError, match="expanded-size"):
        read_bounded_zip(safe.getvalue(), max_expanded_bytes=10)
    with pytest.raises(BoundedZipError, match="member-count"):
        read_bounded_zip(safe.getvalue(), max_members=1)


def test_liteparse_adapter_pins_ocr_complexity_and_target_page_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options: list[dict[str, object]] = []

    class Complexity:
        reasons = ["no-text", "unknown-signal"]

    class ParsedPage:
        page_num = 3
        width = 612.0
        height = 792.0
        text = ""
        complexity = Complexity()

    class Result:
        pages = [ParsedPage()]

    class FakeLiteParse:
        def __init__(self, **kwargs: object) -> None:
            options.append(kwargs)

        def parse(self, data: bytes) -> Result:
            assert data == b"%PDF"
            return Result()

    monkeypatch.setattr("liteparse.LiteParse", FakeLiteParse)

    parsed = LiteParseAdapter().parse(b"%PDF", ocr_enabled=True, target_pages=(3,))

    assert options == [
        {
            "ocr_enabled": True,
            "include_complexity": True,
            "target_pages": "3",
            "quiet": True,
        }
    ]
    assert parsed.pages[0].page_number == 3
    assert parsed.pages[0].reasons == ("no-text", "unknown-signal")
