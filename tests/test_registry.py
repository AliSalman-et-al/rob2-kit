from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import httpx
import pymupdf
import pytest

from rob2_kit.ingestion import ingest_batch
from rob2_kit.registry import (
    CapturedRegistryRecord,
    RegistryNotCaptured,
    RegistryStatus,
    TrialFacts,
    capture_registry_source,
    http_request,
    match_registry,
    nct_candidates,
    read_captured_registry,
)
from rob2_kit.search import search_sources
from rob2_kit.sources import SourceInput, TrialInput, read_pages, sha256_bytes

_FIXTURES = Path(__file__).parent / "fixtures" / "registry"
_TITLE = "Example randomized trial"


def _payload(nct_id: str, *, allocation: str = "RANDOMIZED") -> dict[str, object]:
    payload = json.loads((_FIXTURES / "direct-match.json").read_text())
    ident = payload["protocolSection"]["identificationModule"]
    ident["nctId"] = nct_id
    payload["protocolSection"]["designModule"]["designInfo"]["allocation"] = allocation
    return payload


def _facts() -> TrialFacts:
    return TrialFacts(title=_TITLE, randomized=True, enrollment=10, interventions=("Drug A",))


def _module(payload: dict[str, object], name: str) -> dict[str, object]:
    protocol = cast(dict[str, object], payload["protocolSection"])
    return cast(dict[str, object], protocol[name])


def _pdf(path: Path) -> None:
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()


def test_supplied_identifier_requires_returned_identity_and_no_fact_contradiction() -> None:
    payload = _payload("NCT00000001")
    assert (
        match_registry(_facts(), lambda _: payload, supplied_nct="nct00000001").status
        is RegistryStatus.MATCHED
    )
    assert (
        match_registry(
            _facts(), lambda _: _payload("NCT00000002"), supplied_nct="NCT00000001"
        ).status
        is RegistryStatus.NOT_FOUND
    )
    mismatch = json.loads((_FIXTURES / "mismatch.json").read_text())
    assert (
        match_registry(_facts(), lambda _: mismatch, supplied_nct="NCT00000001").status
        is RegistryStatus.NOT_FOUND
    )
    with pytest.raises(ValueError, match="invalid NCT"):
        match_registry(_facts(), lambda _: payload, supplied_nct="wrong")


def test_allocation_is_tristate_and_unknown_does_not_corroborate_false() -> None:
    nonrandom = _payload("NCT00000001", allocation="NON_RANDOMIZED")
    unknown = _payload("NCT00000001", allocation="OTHER")
    facts = TrialFacts(randomized=False)
    assert (
        match_registry(facts, lambda _: nonrandom, supplied_nct="NCT00000001").status
        is RegistryStatus.MATCHED
    )
    assert (
        match_registry(facts, lambda _: unknown, supplied_nct="NCT00000001").status
        is RegistryStatus.NOT_FOUND
    )


def test_discovery_fetches_exact_candidates_first_and_ambiguity_ignores_rank() -> None:
    first = _payload("NCT00000001")
    second = _payload("NCT00000002")
    calls: list[str] = []

    def request(url: str) -> Mapping[str, object]:
        calls.append(url)
        if url.endswith("NCT00000001"):
            return first
        if url.endswith("NCT00000002"):
            return second
        return json.loads((_FIXTURES / "ambiguous.json").read_text())

    result = match_registry(
        _facts(), request, main_article_text="NCT00000001 NCT00000001 NCT00000002", title_limit=2
    )
    assert nct_candidates("NCT00000001 and NCT00000001") == ("NCT00000001",)
    assert result.status is RegistryStatus.AMBIGUOUS
    assert calls[:2] == [
        "https://clinicaltrials.gov/api/v2/studies/NCT00000001",
        "https://clinicaltrials.gov/api/v2/studies/NCT00000002",
    ]
    assert "pageSize=2" in calls[2]
    assert "confidence" not in result.model_dump()


def test_title_only_or_weak_substring_never_matches() -> None:
    payload = _payload("NCT00000001")
    assert (
        match_registry(TrialFacts(title="Example"), lambda _: {"studies": [payload]}).status
        is RegistryStatus.NOT_FOUND
    )
    assert (
        match_registry(
            TrialFacts(title=_TITLE, randomized=True), lambda _: {"studies": [payload]}
        ).status
        is RegistryStatus.NOT_FOUND
    )
    assert (
        match_registry(_facts(), lambda _: {"studies": [payload]}).status is RegistryStatus.MATCHED
    )


def test_not_found_unavailable_and_programmer_errors_are_distinct() -> None:
    not_found = json.loads((_FIXTURES / "not-found.json").read_text())
    assert (
        match_registry(TrialFacts(title=_TITLE), lambda _: not_found).status
        is RegistryStatus.NOT_FOUND
    )
    assert (
        match_registry(
            TrialFacts(title=_TITLE), lambda _: (_ for _ in ()).throw(TimeoutError())
        ).status
        is RegistryStatus.UNAVAILABLE
    )
    with pytest.raises(RuntimeError, match="bug"):
        match_registry(
            TrialFacts(title=_TITLE), lambda _: (_ for _ in ()).throw(RuntimeError("bug"))
        )
    malformed = _payload("NCT00000001")
    _module(malformed, "identificationModule")["nctId"] = "not-an-nct"
    assert (
        match_registry(_facts(), lambda _: malformed, supplied_nct="NCT00000001").status
        is RegistryStatus.UNAVAILABLE
    )
    malformed = _payload("NCT00000001")
    groups = cast(list[object], _module(malformed, "armsInterventionsModule")["armGroups"])
    cast(dict[str, object], groups[0])["interventionNames"] = "Drug A"
    assert (
        match_registry(_facts(), lambda _: malformed, supplied_nct="NCT00000001").status
        is RegistryStatus.UNAVAILABLE
    )


def test_http_404_allows_title_search_and_provider_bytes_are_immutable() -> None:
    payload = _payload("NCT00000002")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("NCT00000001"):
            return httpx.Response(404, request=request)
        return httpx.Response(200, json={"studies": [payload]}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = match_registry(
            _facts(), http_request(client), main_article_text="NCT00000001", title_limit=1
        )
    protocol = cast(dict[str, object], payload["protocolSection"])
    ident = cast(dict[str, object], protocol["identificationModule"])
    ident["officialTitle"] = "mutated"
    assert result.status is RegistryStatus.MATCHED
    assert result.candidates[0].provider_json == result.provider_json
    assert b"mutated" not in (result.provider_json or b"")


def test_registry_capture_retry_isolation_and_reingest_preserves_generated_source(
    tmp_path: Path,
) -> None:
    _pdf(tmp_path / "main.pdf")
    inputs = (
        TrialInput(
            id="one",
            label="One",
            sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
        ),
        TrialInput(
            id="two",
            label="Two",
            sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
        ),
    )
    original = ingest_batch(tmp_path, inputs)
    match = match_registry(_facts(), lambda _: _payload("NCT00000001"), supplied_nct="NCT00000001")
    first = capture_registry_source(str(tmp_path), "one", match)
    assert capture_registry_source(str(tmp_path), "one", match) == first
    changed = match_registry(
        _facts(), lambda _: _payload("NCT00000001"), supplied_nct="NCT00000001"
    ).model_copy(update={"provider_json": b'{"changed":true}'})
    with pytest.raises(ValueError, match="existing registry source conflicts"):
        capture_registry_source(str(tmp_path), "one", changed)
    assert (tmp_path / first.captured_path).read_bytes() == match.provider_json
    second = capture_registry_source(str(tmp_path), "two", match)
    reingested = ingest_batch(tmp_path, inputs)
    assert reingested.trials[0].sources == original.trials[0].sources
    assert (tmp_path / first.captured_path).read_bytes() == match.provider_json
    assert first.sha256 == sha256_bytes(match.provider_json or b"")
    assert Path(first.captured_path).stem == first.id
    assert Path(second.captured_path).stem == second.id
    assert read_pages(tmp_path, first, (1,)).pages[0].text == (match.provider_json or b"").decode()
    assert search_sources(tmp_path, "one", (first,), "Example", 0, 10)


def test_reingest_fails_closed_for_registry_manifest_or_extra_corruption(tmp_path: Path) -> None:
    _pdf(tmp_path / "main.pdf")
    inputs = (
        TrialInput(
            id="one",
            label="One",
            sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
        ),
    )
    ingest_batch(tmp_path, inputs)
    match = match_registry(_facts(), lambda _: _payload("NCT00000001"), supplied_nct="NCT00000001")
    source = capture_registry_source(str(tmp_path), "one", match)
    directory = tmp_path / ".rob2-kit" / "sources" / "one"
    manifest = directory / "registry-sources.json"
    manifest_bytes = manifest.read_bytes()
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="registry source manifest"):
        ingest_batch(tmp_path, inputs)
    manifest.write_bytes(manifest_bytes)
    (directory / source.captured_path.rsplit("/", 1)[-1]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="registry source manifest"):
        ingest_batch(tmp_path, inputs)
    (directory / source.captured_path.rsplit("/", 1)[-1]).write_bytes(match.provider_json or b"")
    (directory / "orphan.json").write_text("{}")
    with pytest.raises(ValueError, match="incomplete or conflicts"):
        ingest_batch(tmp_path, inputs)


def test_registry_read_rejects_forged_manifest_path_and_changed_bytes(tmp_path: Path) -> None:
    _pdf(tmp_path / "main.pdf")
    inputs = (
        TrialInput(
            id="one",
            label="One",
            sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
        ),
    )
    ingest_batch(tmp_path, inputs)
    match = match_registry(_facts(), lambda _: _payload("NCT00000001"), supplied_nct="NCT00000001")
    source = capture_registry_source(str(tmp_path), "one", match)
    directory = tmp_path / ".rob2-kit" / "sources" / "one"
    manifest = directory / "registry-sources.json"
    payload = json.loads(manifest.read_text())
    payload["sources"][0]["captured_path"] = "../one/" + Path(source.captured_path).name
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="registry source manifest"):
        read_captured_registry(str(tmp_path), "one")
    manifest.write_text(
        json.dumps(
            {"schema": "rob2-kit.registry-sources.v1", "sources": [source.model_dump(mode="json")]}
        )
    )
    (tmp_path / source.captured_path).write_bytes(b"{}")
    with pytest.raises(ValueError, match="captured bytes"):
        read_captured_registry(str(tmp_path), "one")


def test_registry_manifest_rejects_altered_metadata_and_links(tmp_path: Path) -> None:
    _pdf(tmp_path / "main.pdf")
    inputs = (
        TrialInput(
            id="one",
            label="One",
            sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
        ),
    )
    ingest_batch(tmp_path, inputs)
    match = match_registry(_facts(), lambda _: _payload("NCT00000001"), supplied_nct="NCT00000001")
    source = capture_registry_source(str(tmp_path), "one", match)
    directory = tmp_path / ".rob2-kit" / "sources" / "one"
    manifest = directory / "registry-sources.json"
    original = manifest.read_text()

    for field, value in (
        ("label", "forged"),
        ("media_type", "text/plain"),
        ("page_count", 2),
        ("id", "source_forged"),
    ):
        payload = json.loads(original)
        payload["sources"][0][field] = value
        manifest.write_text(json.dumps(payload))
        with pytest.raises(ValueError, match="registry source manifest"):
            read_captured_registry(str(tmp_path), "one")

    manifest.write_text(original)
    source_path = tmp_path / source.captured_path
    target = tmp_path / "registry-target.json"
    target.write_bytes(match.provider_json or b"")
    source_path.unlink()
    try:
        os.symlink(target, source_path)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    with pytest.raises(ValueError, match="registry source manifest"):
        read_captured_registry(str(tmp_path), "one")


def test_registry_capture_rolls_back_after_manifest_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rob2_kit.ingestion.service as service

    _pdf(tmp_path / "main.pdf")
    inputs = (
        TrialInput(
            id="one",
            label="One",
            sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
        ),
    )
    original = ingest_batch(tmp_path, inputs)
    match = match_registry(_facts(), lambda _: _payload("NCT00000001"), supplied_nct="NCT00000001")

    def fail(_: Path, __: Path) -> None:
        raise OSError("manifest failure")

    monkeypatch.setattr(service, "_publish_registry_manifest", fail)
    with pytest.raises(OSError, match="manifest failure"):
        capture_registry_source(str(tmp_path), "one", match)
    directory = tmp_path / ".rob2-kit" / "sources" / "one"
    assert not (directory / "registry-sources.json").exists()
    assert not list(directory.glob("source_*.json"))
    assert ingest_batch(tmp_path, inputs).trials[0].sources == original.trials[0].sources
    monkeypatch.undo()
    assert capture_registry_source(str(tmp_path), "one", match).trial_id == "one"


def test_captured_registry_variants_require_coherent_data() -> None:
    with pytest.raises(ValueError):
        CapturedRegistryRecord.model_validate(cast(Any, {"trial_id": "one", "status": "captured"}))
    with pytest.raises(ValueError):
        RegistryNotCaptured.model_validate(
            cast(Any, {"trial_id": "one", "status": "not_captured", "record_json": "{}"})
        )
