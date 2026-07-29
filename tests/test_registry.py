from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from rob2_kit.domain.sources import SourceCriticality
from rob2_kit.registry import (
    ClinicalTrialsGovAdapter,
    RegistryAcquisitionStatus,
    RegistryFindingKind,
    RegistryPolicy,
)
from rob2_kit.storage import ArtifactStore

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (Path(__file__).parent / "http_fixtures" / name).read_bytes()


class ReplayTransport(httpx.BaseTransport):
    def __init__(self, responses: list[tuple[int, bytes, dict[str, str]]]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, content, headers = self.responses.pop(0)
        return httpx.Response(status, content=content, headers=headers, request=request)


def adapter(
    tmp_path: Path,
    responses: list[tuple[int, bytes, dict[str, str]]],
    *,
    policy: RegistryPolicy | None = None,
) -> tuple[ClinicalTrialsGovAdapter, ReplayTransport, ArtifactStore]:
    transport = ReplayTransport(responses)
    store = ArtifactStore(tmp_path / "artifacts")
    client = httpx.Client(transport=transport)
    return (
        ClinicalTrialsGovAdapter(
            client=client,
            artifacts=store,
            policy=policy or RegistryPolicy(),
            clock=lambda: NOW,
        ),
        transport,
        store,
    )


def test_exact_source_nct_id_acquires_raw_record_and_stable_projection(tmp_path: Path) -> None:
    service, transport, store = adapter(
        tmp_path,
        [
            (200, fixture("ctg_version.json"), {"etag": '"version-1"'}),
            (200, fixture("ctg_study.json"), {"etag": '"study-1"'}),
        ],
    )

    result = service.acquire(source_texts=(("report.pdf#page=2", "Registered as nct01234567."),))

    assert result.status is RegistryAcquisitionStatus.ACQUIRED
    assert result.resolution.nct_id == "NCT01234567"
    assert result.resolution.locator == "report.pdf#page=2"
    assert result.dataset_timestamp == datetime(2026, 7, 28, 15, tzinfo=UTC)
    assert result.raw_record_hash is not None
    assert store.read(result.raw_record_hash) == fixture("ctg_study.json")
    assert result.projection is not None
    assert result.projection.nct_id.value == "NCT01234567"
    assert result.projection.nct_id.json_pointer == (
        "/protocolSection/identificationModule/nctId"
    )
    assert result.projection.last_update_posted is not None
    assert result.projection.last_update_posted.json_pointer == (
        "/protocolSection/statusModule/lastUpdatePostDateStruct/date"
    )
    assert result.projection.last_update_posted.value == date(2026, 7, 20)
    assert [request.url.path for request in transport.requests] == [
        "/api/v2/version",
        "/api/v2/studies/NCT01234567",
    ]
    assert result.exchanges[1].response_headers == (("etag", '"study-1"'),)


def test_missing_record_is_deterministic_nonfatal_failure(tmp_path: Path) -> None:
    service, transport, _ = adapter(
        tmp_path,
        [
            (200, fixture("ctg_version.json"), {}),
            (404, b'{"message":"Not found"}', {}),
        ],
    )

    result = service.acquire(declared_nct_id="NCT00000000")

    assert result.status is RegistryAcquisitionStatus.UNAVAILABLE
    assert result.findings[0].kind is RegistryFindingKind.REGISTRY_UNAVAILABLE
    assert len(transport.requests) == 2


def test_fuzzy_search_candidates_never_auto_link(tmp_path: Path) -> None:
    service, transport, _ = adapter(
        tmp_path,
        [(200, fixture("ctg_search.json"), {})],
    )

    result = service.acquire(source_texts=(("report.pdf#page=1", "Beacon hypertension trial"),))

    assert result.status is RegistryAcquisitionStatus.REVIEW_REQUIRED
    assert result.resolution.nct_id is None
    assert result.findings[0].kind is RegistryFindingKind.FUZZY_REGISTRY_CANDIDATES
    assert result.findings[0].candidate_nct_ids == ("NCT01234567", "NCT07654321")
    assert transport.requests[0].url.path == "/api/v2/studies"
    assert dict(transport.requests[0].url.params) == {
        "format": "json",
        "pageSize": "5",
        "query.term": "Beacon hypertension trial",
    }


def test_conflicting_exact_source_identifiers_require_review_without_network(
    tmp_path: Path,
) -> None:
    service, transport, _ = adapter(tmp_path, [])

    result = service.acquire(
        source_texts=(
            ("report.pdf#page=1", "NCT01234567"),
            ("registry-note.txt#line=4", "NCT07654321"),
        )
    )

    assert result.status is RegistryAcquisitionStatus.REVIEW_REQUIRED
    assert result.findings[0].kind is RegistryFindingKind.CONFLICTING_EXACT_IDENTIFIERS
    assert result.findings[0].candidate_nct_ids == ("NCT01234567", "NCT07654321")
    assert transport.requests == []


def test_failed_fuzzy_search_is_an_acquisition_failure_not_an_empty_candidate_set(
    tmp_path: Path,
) -> None:
    service, _, _ = adapter(tmp_path, [(500, b"failed", {})] * 3)

    result = service.acquire(source_texts=(("report.pdf#page=1", "Beacon trial"),))

    assert result.status is RegistryAcquisitionStatus.ACQUISITION_FAILED
    assert result.findings[0].kind is RegistryFindingKind.REGISTRY_ACQUISITION_FAILED


def test_provider_protocol_is_downloaded_only_from_allow_list(tmp_path: Path) -> None:
    study = json.loads(fixture("ctg_study.json"))
    study["documentSection"]["largeDocumentModule"]["largeDocs"].append(
        {
            "typeAbbrev": "Prot",
            "hasProtocol": True,
            "filename": "Protocol.pdf",
            "url": "https://evil.example/Protocol.pdf",
        }
    )
    raw_study = json.dumps(study, separators=(",", ":")).encode()
    service, transport, store = adapter(
        tmp_path,
        [
            (200, fixture("ctg_version.json"), {}),
            (200, raw_study, {}),
            (200, b"%PDF-provider-protocol", {"content-type": "application/pdf"}),
        ],
        policy=RegistryPolicy(fetch_provider_documents=True),
    )

    result = service.acquire(declared_nct_id="NCT01234567")

    assert len(result.documents) == 1
    assert result.documents[0].roles == ("protocol", "statistical_analysis_plan")
    assert store.read(result.documents[0].artifact_hash) == b"%PDF-provider-protocol"
    assert transport.requests[-1].url.host == "cdn.clinicaltrials.gov"
    assert any(
        finding.kind is RegistryFindingKind.BLOCKED_PROVIDER_URL for finding in result.findings
    )


def test_transient_responses_retry_twice_and_then_succeed(tmp_path: Path) -> None:
    service, transport, _ = adapter(
        tmp_path,
        [
            (503, b"busy", {}),
            (429, b"slow down", {}),
            (200, fixture("ctg_version.json"), {}),
            (200, fixture("ctg_study.json"), {}),
        ],
    )

    result = service.acquire(declared_nct_id="NCT01234567")

    assert result.status is RegistryAcquisitionStatus.ACQUIRED
    assert [exchange.attempt for exchange in result.exchanges[:3]] == [1, 2, 3]
    assert len(transport.requests) == 4


def test_deterministic_failure_is_not_retried_and_required_policy_is_explicit(
    tmp_path: Path,
) -> None:
    service, transport, _ = adapter(
        tmp_path,
        [(400, b'{"message":"invalid"}', {})],
        policy=RegistryPolicy(criticality=SourceCriticality.REQUIRED),
    )

    result = service.acquire(declared_nct_id="NCT01234567")

    assert result.status is RegistryAcquisitionStatus.TRIAL_FAILED
    assert result.findings[0].kind is RegistryFindingKind.REGISTRY_ACQUISITION_FAILED
    assert len(transport.requests) == 1


def test_malformed_success_response_degrades_to_typed_failure(tmp_path: Path) -> None:
    service, transport, _ = adapter(tmp_path, [(200, b"not-json", {})])

    result = service.acquire(declared_nct_id="NCT01234567")

    assert result.status is RegistryAcquisitionStatus.ACQUISITION_FAILED
    assert result.findings[0].kind is RegistryFindingKind.REGISTRY_ACQUISITION_FAILED
    assert len(transport.requests) == 1


def test_unavailable_experimental_history_is_capability_probed_and_nonblocking(
    tmp_path: Path,
) -> None:
    service, transport, _ = adapter(
        tmp_path,
        [
            (200, fixture("ctg_version.json"), {}),
            (200, fixture("ctg_study.json"), {}),
            (404, b"unavailable", {}),
        ],
        policy=RegistryPolicy(probe_history=True),
    )

    result = service.acquire(declared_nct_id="NCT01234567")

    assert result.status is RegistryAcquisitionStatus.ACQUIRED
    assert result.history is not None
    assert result.history.available is False
    assert result.history.experimental is True
    assert result.history.outcome_switching_claim is False
    assert transport.requests[-1].url.path == "/api/int/studies/NCT01234567/history"
