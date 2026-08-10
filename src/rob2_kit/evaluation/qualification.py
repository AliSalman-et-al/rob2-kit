"""Installed-only dependency composition used by the release replay harness.

This module is deliberately small: it is not a second workflow implementation.
It composes ordinary :class:`RunEngine` dependencies so the installed MCP
executable can exercise absence and failure paths without monkeypatching the
checkout that launched the qualifier.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from rob2_kit.application.determinism import QualificationDeterminism
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.ingestion import LiteParseAdapter, PageRender, ParserResult
from rob2_kit.registry import (
    HistoryCapability,
    RegistryAcquisition,
    RegistryAcquisitionStatus,
    RegistryResolution,
)
from rob2_kit.storage import LeaseConflictError, LeaseToken, WorkflowLedger

from .installed_replay import RELEASE_LOCKED_OPTIONAL_FIXTURES


class _ReleaseFixtureParser:
    """Classify the fixed public dossier without changing production parsing."""

    def __init__(self) -> None:
        self._delegate = LiteParseAdapter()
        self.name = self._delegate.name
        self.version = self._delegate.version
        self.configuration = self._delegate.configuration | {
            "release_fixture": "installed-replay-v1"
        }

    def parse(
        self, data: bytes, *, ocr_enabled: bool, target_pages: tuple[int, ...] | None = None
    ) -> ParserResult:
        parsed = self._delegate.parse(data, ocr_enabled=ocr_enabled, target_pages=target_pages)
        pages = tuple(
            page.model_copy(
                update={
                    # The fixed release dossier is a known complete textual
                    # fixture.  LiteParse's sparse-layout heuristic is useful
                    # for unknown uploads but would otherwise turn this
                    # deterministic one-page qualification source into a
                    # coverage-limited surrogate.
                    "reasons": (),
                    "text_items": tuple(
                        item.model_copy(
                            update={
                                # Parser lineage is source structure only;
                                # later reviews bind this neutral fragment to
                                # Result, Domain, and signaling-question scope.
                                "fragment_id": f"fragment:qualification:page:{page.page_number}:item:{item_index}",
                                "unit_kind": "paragraph",
                                "document_zone": "methods",
                            }
                        )
                        for item_index, item in enumerate(page.text_items)
                    )
                }
            )
            for page in parsed.pages
        )
        return parsed.model_copy(update={"pages": pages})

    def screenshot(
        self, data: bytes, *, page_numbers: tuple[int, ...], dpi: int
    ) -> tuple[PageRender, ...]:
        return self._delegate.screenshot(data, page_numbers=page_numbers, dpi=dpi)


class _ReleaseFixtureRegistry:
    """Recorded deterministic no-match response for the public dossier."""

    def acquire(self, **arguments: Any) -> RegistryAcquisition:
        nct_id = arguments.get("declared_nct_id")
        return RegistryAcquisition(
            status=RegistryAcquisitionStatus.UNAVAILABLE,
            resolution=RegistryResolution(nct_id=nct_id, locator="trial.yaml", explicit=True),
            retrieved_at=datetime(2026, 8, 3, tzinfo=UTC),
            history=HistoryCapability(available=True),
            policy_release="policy:source-recovery-1.0.0",
        )


class _UnavailableRegistryCapability:
    """Explicitly prevent RunEngine from constructing its default registry client."""

    def acquire(self, **arguments: Any) -> RegistryAcquisition:
        nct_id = arguments.get("declared_nct_id")
        return RegistryAcquisition(
            status=RegistryAcquisitionStatus.UNAVAILABLE,
            resolution=RegistryResolution(nct_id=nct_id, locator="trial.yaml", explicit=True),
            retrieved_at=datetime(2026, 8, 3, tzinfo=UTC),
            history=HistoryCapability(available=False),
            policy_release="policy:source-recovery-1.0.0",
        )


class _FailingProjector:
    """A real report dependency that fails before publication writes begin."""

    def __init__(self, assessment: Any) -> None:
        self._assessment = assessment

    def bundle_files(self) -> dict[str, bytes]:
        raise OSError("qualification report projector is unavailable")


def _writer_conflict(ledger: WorkflowLedger, now: datetime) -> LeaseToken:
    """Let setup use the ledger, then conflict on the next actual write."""

    # Source-role review now precedes confirmation.  The prepared run is the
    # setup boundary; the following write must exercise the fenced owner path.
    if any(event.operation == "operation:run-prepared" for event in ledger.events()):
        raise LeaseConflictError("qualification writer lease is held by another owner")
    return ledger.acquire_lease(
        "owner:qualification-setup",
        now,
        timedelta(minutes=5),
    )


def qualification_engine_from_environment(
    determinism: QualificationDeterminism | None,
    environ: dict[str, str],
) -> RunEngine:
    """Compose installed dependencies selected by explicit qualification flags.

    The flags are intentionally accepted only by the stdio composition root.
    All resulting outcomes flow through normal RunEngine validation, ledger,
    and publication code; they do not manufacture MCP response envelopes.
    """

    absent = tuple(
        item.strip()
        for item in environ.get("ROB2_QUALIFICATION_ABSENT_FIXTURES", "").split(",")
        if item.strip()
    )
    unknown = set(absent) - set(RELEASE_LOCKED_OPTIONAL_FIXTURES)
    if unknown:
        raise ValueError(f"unknown qualification fixture: {sorted(unknown)!r}")
    fault = environ.get("ROB2_QUALIFICATION_INJECTED_FAULT")
    if fault not in {None, "writer", "report-failure"}:
        raise ValueError(f"unsupported injected qualification fault: {fault!r}")

    projector_factory: Callable[[Any], Any] | None = None
    if fault == "report-failure":
        projector_factory = _FailingProjector
    return RunEngine(
        parser=(
            _ReleaseFixtureParser()
            if environ.get("ROB2_QUALIFICATION_RELEASE_FIXTURE") == "installed-replay-v1"
            else None
        ),
        # The declared NCT identifier forces a registry acquisition attempt.
        # An explicit unavailable adapter prevents RunEngine from lazily
        # constructing its production HTTP client for the absence replay.
        registry_adapter=(
            _UnavailableRegistryCapability()
            if "registry_history" in absent
            else _ReleaseFixtureRegistry()
        ),
        determinism=determinism,
        report_projector_factory=projector_factory,
        lease_acquirer=_writer_conflict if fault == "writer" else None,
    )
