"""Allow-listed ClinicalTrials.gov acquisition with complete response custody."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.domain.sources import SourceCriticality, SourceRole
from rob2_kit.storage import ArtifactStore

API_ORIGIN = "https://clinicaltrials.gov"
ALLOWED_DOCUMENT_HOST = "cdn.clinicaltrials.gov"
NCT_PATTERN = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class RegistryAcquisitionStatus(StrEnum):
    ACQUIRED = "acquired"
    UNAVAILABLE = "unavailable"
    REVIEW_REQUIRED = "review_required"
    ACQUISITION_FAILED = "acquisition_failed"
    TRIAL_FAILED = "trial_failed"


class RegistryFindingKind(StrEnum):
    FUZZY_REGISTRY_CANDIDATES = "fuzzy_registry_candidates"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    REGISTRY_ACQUISITION_FAILED = "registry_acquisition_failed"
    BLOCKED_PROVIDER_URL = "blocked_provider_url"
    HISTORY_UNAVAILABLE = "history_unavailable"
    CONFLICTING_EXACT_IDENTIFIERS = "conflicting_exact_identifiers"


class RegistryPolicy(FrozenModel):
    policy_release: Identifier = "policy:source-recovery-1.0.0"
    criticality: SourceCriticality = SourceCriticality.EXPECTED
    fetch_provider_documents: bool = False
    probe_history: bool = False
    max_transient_retries: int = Field(default=2, ge=0, le=2)
    fuzzy_candidate_limit: int = Field(default=5, ge=1, le=20)


class RegistryResolution(FrozenModel):
    nct_id: str | None = Field(default=None, pattern=r"^NCT\d{8}$")
    locator: str | None = None
    explicit: bool = False
    candidate_nct_ids: tuple[str, ...] = ()


class RegistrySourceText(FrozenModel):
    locator: str = Field(min_length=1)
    text: str = Field(min_length=1)


class HttpExchange(FrozenModel):
    method: str
    url: str
    request_parameters: tuple[tuple[str, str], ...]
    attempted_at: datetime
    attempt: int
    status_code: int | None
    response_headers: tuple[tuple[str, str], ...] = ()
    response_hash: ContentHash | None = None
    error_category: str | None = None


class ProjectedValue(FrozenModel):
    value: str
    json_pointer: str


class ProjectedDate(FrozenModel):
    value: date
    json_pointer: str
    kind: str


class RegistryProjection(FrozenModel):
    nct_id: ProjectedValue
    brief_title: ProjectedValue | None = None
    overall_status: ProjectedValue | None = None
    last_update_posted: ProjectedDate | None = None
    version_holder: ProjectedDate | None = None


class ProviderDocument(FrozenModel):
    filename: str
    source_url: str
    roles: tuple[SourceRole, ...]
    artifact_hash: ContentHash
    document_date: date | None = None
    upload_date: datetime | None = None
    metadata_json_pointer: str


class HistoryCapability(FrozenModel):
    experimental: bool = True
    available: bool
    outcome_switching_claim: bool = False
    raw_response_hash: ContentHash | None = None


class RegistryFinding(FrozenModel):
    kind: RegistryFindingKind
    detail: str
    candidate_nct_ids: tuple[str, ...] = ()


class RegistryAcquisition(FrozenModel):
    status: RegistryAcquisitionStatus
    resolution: RegistryResolution
    retrieved_at: datetime
    dataset_timestamp: datetime | None = None
    raw_version_hash: ContentHash | None = None
    raw_record_hash: ContentHash | None = None
    parsed_record_hash: ContentHash | None = None
    projection: RegistryProjection | None = None
    documents: tuple[ProviderDocument, ...] = ()
    history: HistoryCapability | None = None
    exchanges: tuple[HttpExchange, ...] = ()
    findings: tuple[RegistryFinding, ...] = ()
    policy_release: Identifier


class _FetchResult(FrozenModel):
    response: bytes | None
    status_code: int | None
    headers: tuple[tuple[str, str], ...] = ()
    exchanges: tuple[HttpExchange, ...]


class ClinicalTrialsGovAdapter:
    """Acquire only provider-defined resources derived from trusted NCT identifiers."""

    def __init__(
        self,
        *,
        client: httpx.Client,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime],
        policy: RegistryPolicy | None = None,
    ) -> None:
        self._client = client
        self._artifacts = artifacts
        self._clock = clock
        self._policy = policy or RegistryPolicy()

    def acquire(
        self,
        *,
        declared_nct_id: str | None = None,
        source_texts: tuple[RegistrySourceText | tuple[str, str], ...] = (),
    ) -> RegistryAcquisition:
        normalized_sources = tuple(
            item if isinstance(item, RegistrySourceText) else RegistrySourceText(
                locator=item[0], text=item[1]
            )
            for item in source_texts
        )
        retrieved_at = self._utc_now()
        resolution = self._resolve(declared_nct_id, normalized_sources)
        if resolution.nct_id is None:
            return self._search_candidates(resolution, normalized_sources, retrieved_at)

        exchanges: list[HttpExchange] = []
        findings: list[RegistryFinding] = []
        version = self._fetch("/api/v2/version")
        exchanges.extend(version.exchanges)
        if version.response is None:
            return self._failed(resolution, retrieved_at, exchanges, version.status_code)
        try:
            version_data = json.loads(version.response)
            dataset_timestamp = datetime.fromisoformat(
                version_data["dataTimestamp"].replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._failed(resolution, retrieved_at, exchanges, version.status_code)
        raw_version_hash = self._put_raw_json(version.response)

        record = self._fetch(f"/api/v2/studies/{resolution.nct_id}")
        exchanges.extend(record.exchanges)
        if record.status_code == 404:
            findings.append(
                RegistryFinding(
                    kind=RegistryFindingKind.REGISTRY_UNAVAILABLE,
                    detail=f"{resolution.nct_id} was not found in the current registry",
                )
            )
            return RegistryAcquisition(
                status=self._failure_status(unavailable=True),
                resolution=resolution,
                retrieved_at=retrieved_at,
                dataset_timestamp=dataset_timestamp,
                raw_version_hash=raw_version_hash,
                exchanges=tuple(exchanges),
                findings=tuple(findings),
                policy_release=self._policy.policy_release,
            )
        if record.response is None:
            return self._failed(
                resolution,
                retrieved_at,
                exchanges,
                record.status_code,
                dataset_timestamp=dataset_timestamp,
                raw_version_hash=raw_version_hash,
            )

        try:
            parsed = json.loads(record.response)
            projection = _project(parsed)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._failed(
                resolution,
                retrieved_at,
                exchanges,
                record.status_code,
                dataset_timestamp=dataset_timestamp,
                raw_version_hash=raw_version_hash,
            )
        raw_record_hash = self._put_raw_json(record.response)
        if projection.nct_id.value != resolution.nct_id:
            return self._failed(
                resolution,
                retrieved_at,
                exchanges,
                record.status_code,
                dataset_timestamp=dataset_timestamp,
                raw_version_hash=raw_version_hash,
            )
        parsed_record_hash = self._artifacts.put(
            json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            "application/json",
        ).content_hash

        documents: list[ProviderDocument] = []
        if self._policy.fetch_provider_documents:
            self._acquire_documents(parsed, documents, findings, exchanges)

        history = None
        if self._policy.probe_history:
            history_fetch = self._fetch(
                f"/api/int/studies/{resolution.nct_id}/history", retries=0
            )
            exchanges.extend(history_fetch.exchanges)
            if history_fetch.response is None:
                history = HistoryCapability(available=False)
                findings.append(
                    RegistryFinding(
                        kind=RegistryFindingKind.HISTORY_UNAVAILABLE,
                        detail="Experimental registry history capability is unavailable",
                    )
                )
            else:
                history = HistoryCapability(
                    available=True,
                    raw_response_hash=self._put_raw_json(history_fetch.response),
                )

        return RegistryAcquisition(
            status=RegistryAcquisitionStatus.ACQUIRED,
            resolution=resolution,
            retrieved_at=retrieved_at,
            dataset_timestamp=dataset_timestamp,
            raw_version_hash=raw_version_hash,
            raw_record_hash=raw_record_hash,
            parsed_record_hash=parsed_record_hash,
            projection=projection,
            documents=tuple(documents),
            history=history,
            exchanges=tuple(exchanges),
            findings=tuple(findings),
            policy_release=self._policy.policy_release,
        )

    def _resolve(
        self,
        declared_nct_id: str | None,
        source_texts: tuple[RegistrySourceText, ...],
    ) -> RegistryResolution:
        if declared_nct_id is not None:
            normalized = declared_nct_id.upper()
            if NCT_PATTERN.fullmatch(normalized) is None:
                raise ValueError("declared_nct_id must be NCT followed by eight digits")
            return RegistryResolution(nct_id=normalized, locator="project-manifest", explicit=True)
        matches = tuple(
            (source.locator, match.group().upper())
            for source in source_texts
            for match in NCT_PATTERN.finditer(source.text)
        )
        unique_ids = tuple(dict.fromkeys(nct_id for _, nct_id in matches))
        if len(unique_ids) == 1:
            locator = next(locator for locator, nct_id in matches if nct_id == unique_ids[0])
            return RegistryResolution(nct_id=unique_ids[0], locator=locator)
        if len(unique_ids) > 1:
            return RegistryResolution(candidate_nct_ids=unique_ids)
        return RegistryResolution()

    def _search_candidates(
        self,
        resolution: RegistryResolution,
        source_texts: tuple[RegistrySourceText, ...],
        retrieved_at: datetime,
    ) -> RegistryAcquisition:
        if resolution.candidate_nct_ids:
            return RegistryAcquisition(
                status=RegistryAcquisitionStatus.REVIEW_REQUIRED,
                resolution=resolution,
                retrieved_at=retrieved_at,
                findings=(
                    RegistryFinding(
                        kind=RegistryFindingKind.CONFLICTING_EXACT_IDENTIFIERS,
                        detail="Supplied sources contain conflicting exact NCT identifiers",
                        candidate_nct_ids=resolution.candidate_nct_ids,
                    ),
                ),
                policy_release=self._policy.policy_release,
            )
        query = next((source.text.strip() for source in source_texts if source.text.strip()), "")
        if not query:
            return RegistryAcquisition(
                status=RegistryAcquisitionStatus.REVIEW_REQUIRED,
                resolution=resolution,
                retrieved_at=retrieved_at,
                findings=(
                    RegistryFinding(
                        kind=RegistryFindingKind.FUZZY_REGISTRY_CANDIDATES,
                        detail="No exact NCT ID or usable registry search candidate was supplied",
                    ),
                ),
                policy_release=self._policy.policy_release,
            )
        fetched = self._fetch(
            "/api/v2/studies",
            params={
                "format": "json",
                "pageSize": str(self._policy.fuzzy_candidate_limit),
                "query.term": query,
            },
        )
        candidates: tuple[str, ...] = ()
        if fetched.response is None:
            return RegistryAcquisition(
                status=self._failure_status(),
                resolution=resolution,
                retrieved_at=retrieved_at,
                exchanges=fetched.exchanges,
                findings=(
                    RegistryFinding(
                        kind=RegistryFindingKind.REGISTRY_ACQUISITION_FAILED,
                        detail=(
                            "Registry candidate search failed with status "
                            f"{fetched.status_code}"
                        ),
                    ),
                ),
                policy_release=self._policy.policy_release,
            )
        if fetched.response is not None:
            try:
                payload = json.loads(fetched.response)
                candidates = tuple(
                    study["protocolSection"]["identificationModule"]["nctId"]
                    for study in payload.get("studies", ())
                    if NCT_PATTERN.fullmatch(
                        study.get("protocolSection", {})
                        .get("identificationModule", {})
                        .get("nctId", "")
                    )
                )
            except (TypeError, json.JSONDecodeError):
                candidates = ()
        return RegistryAcquisition(
            status=RegistryAcquisitionStatus.REVIEW_REQUIRED,
            resolution=resolution,
            retrieved_at=retrieved_at,
            exchanges=fetched.exchanges,
            findings=(
                RegistryFinding(
                    kind=RegistryFindingKind.FUZZY_REGISTRY_CANDIDATES,
                    detail="Fuzzy registry matches require human review and were not linked",
                    candidate_nct_ids=candidates,
                ),
            ),
            policy_release=self._policy.policy_release,
        )

    def _acquire_documents(
        self,
        parsed: dict[str, Any],
        documents: list[ProviderDocument],
        findings: list[RegistryFinding],
        exchanges: list[HttpExchange],
    ) -> None:
        listed = (
            parsed.get("documentSection", {})
            .get("largeDocumentModule", {})
            .get("largeDocs", ())
        )
        for index, document in enumerate(listed):
            roles = _document_roles(document)
            if not roles:
                continue
            url = document.get("url")
            if not isinstance(url, str) or not _allowed_document_url(url):
                findings.append(
                    RegistryFinding(
                        kind=RegistryFindingKind.BLOCKED_PROVIDER_URL,
                        detail="A structured provider document URL was outside the allow-list",
                    )
                )
                continue
            fetched = self._fetch_absolute(url)
            exchanges.extend(fetched.exchanges)
            if fetched.response is None:
                findings.append(
                    RegistryFinding(
                        kind=RegistryFindingKind.REGISTRY_ACQUISITION_FAILED,
                        detail=(
                            "Provider document could not be acquired: "
                            f"{document.get('filename')}"
                        ),
                    )
                )
                continue
            artifact = self._artifacts.put(fetched.response, "application/pdf")
            documents.append(
                ProviderDocument(
                    filename=str(document.get("filename", "provider-document.pdf")),
                    source_url=url,
                    roles=roles,
                    artifact_hash=artifact.content_hash,
                    document_date=_parse_date(document.get("documentDate")),
                    upload_date=_parse_datetime(document.get("uploadDate")),
                    metadata_json_pointer=(
                        f"/documentSection/largeDocumentModule/largeDocs/{index}"
                    ),
                )
            )

    def _fetch(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        retries: int | None = None,
    ) -> _FetchResult:
        return self._request(
            f"{API_ORIGIN}{path}",
            params=params or {},
            retries=self._policy.max_transient_retries if retries is None else retries,
        )

    def _fetch_absolute(self, url: str) -> _FetchResult:
        if not _allowed_document_url(url):
            raise ValueError("provider document URL is outside the allow-list")
        return self._request(url, params={}, retries=self._policy.max_transient_retries)

    def _request(self, url: str, *, params: dict[str, str], retries: int) -> _FetchResult:
        exchanges: list[HttpExchange] = []
        ordered_params = tuple(sorted(params.items()))
        for attempt in range(1, retries + 2):
            attempted_at = self._utc_now()
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as error:
                exchanges.append(
                    HttpExchange(
                        method="GET",
                        url=url,
                        request_parameters=ordered_params,
                        attempted_at=attempted_at,
                        attempt=attempt,
                        status_code=None,
                        error_category=type(error).__name__,
                    )
                )
                if attempt <= retries:
                    continue
                return _FetchResult(response=None, status_code=None, exchanges=tuple(exchanges))
            raw_hash = self._artifacts.put(
                response.content, "application/vnd.rob2.registry-response"
            ).content_hash
            headers = tuple(
                sorted(
                    (name.lower(), value)
                    for name, value in response.headers.items()
                    if name.lower() in {"content-type", "date", "etag", "last-modified"}
                )
            )
            exchanges.append(
                HttpExchange(
                    method="GET",
                    url=str(response.request.url),
                    request_parameters=ordered_params,
                    attempted_at=attempted_at,
                    attempt=attempt,
                    status_code=response.status_code,
                    response_headers=headers,
                    response_hash=raw_hash,
                )
            )
            if response.status_code in TRANSIENT_STATUS_CODES and attempt <= retries:
                continue
            if response.is_success:
                return _FetchResult(
                    response=response.content,
                    status_code=response.status_code,
                    headers=headers,
                    exchanges=tuple(exchanges),
                )
            return _FetchResult(
                response=None,
                status_code=response.status_code,
                headers=headers,
                exchanges=tuple(exchanges),
            )
        raise AssertionError("bounded retry loop did not return")

    def _failed(
        self,
        resolution: RegistryResolution,
        retrieved_at: datetime,
        exchanges: list[HttpExchange],
        status_code: int | None,
        *,
        dataset_timestamp: datetime | None = None,
        raw_version_hash: ContentHash | None = None,
    ) -> RegistryAcquisition:
        return RegistryAcquisition(
            status=self._failure_status(),
            resolution=resolution,
            retrieved_at=retrieved_at,
            dataset_timestamp=dataset_timestamp,
            raw_version_hash=raw_version_hash,
            exchanges=tuple(exchanges),
            findings=(
                RegistryFinding(
                    kind=RegistryFindingKind.REGISTRY_ACQUISITION_FAILED,
                    detail=f"ClinicalTrials.gov acquisition failed with status {status_code}",
                ),
            ),
            policy_release=self._policy.policy_release,
        )

    def _failure_status(self, *, unavailable: bool = False) -> RegistryAcquisitionStatus:
        if self._policy.criticality is SourceCriticality.REQUIRED:
            return RegistryAcquisitionStatus.TRIAL_FAILED
        if unavailable:
            return RegistryAcquisitionStatus.UNAVAILABLE
        return RegistryAcquisitionStatus.ACQUISITION_FAILED

    def _put_raw_json(self, content: bytes) -> ContentHash:
        json.loads(content)
        return self._artifacts.put(
            content, "application/vnd.rob2.registry-raw+json"
        ).content_hash

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("registry clock must return UTC")
        return value


def _project(study: dict[str, Any]) -> RegistryProjection:
    identification = study["protocolSection"]["identificationModule"]
    status = study.get("protocolSection", {}).get("statusModule", {})
    misc = study.get("derivedSection", {}).get("miscInfoModule", {})
    return RegistryProjection(
        nct_id=ProjectedValue(
            value=identification["nctId"],
            json_pointer="/protocolSection/identificationModule/nctId",
        ),
        brief_title=_optional_projection(
            identification.get("briefTitle"),
            "/protocolSection/identificationModule/briefTitle",
        ),
        overall_status=_optional_projection(
            status.get("overallStatus"),
            "/protocolSection/statusModule/overallStatus",
        ),
        last_update_posted=_optional_projected_date(
            status.get("lastUpdatePostDateStruct", {}).get("date"),
            "/protocolSection/statusModule/lastUpdatePostDateStruct/date",
            "last_update_posted",
        ),
        version_holder=_optional_projected_date(
            misc.get("versionHolder"),
            "/derivedSection/miscInfoModule/versionHolder",
            "api_version_holder",
        ),
    )


def _optional_projection(value: Any, pointer: str) -> ProjectedValue | None:
    return ProjectedValue(value=str(value), json_pointer=pointer) if value is not None else None


def _optional_projected_date(value: Any, pointer: str, kind: str) -> ProjectedDate | None:
    return (
        ProjectedDate(value=date.fromisoformat(str(value)), json_pointer=pointer, kind=kind)
        if value is not None
        else None
    )


def _parse_date(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _document_roles(document: dict[str, Any]) -> tuple[SourceRole, ...]:
    roles: list[SourceRole] = []
    if document.get("hasProtocol") is True:
        roles.append(SourceRole.PROTOCOL)
    if document.get("hasSap") is True:
        roles.append(SourceRole.STATISTICAL_ANALYSIS_PLAN)
    return tuple(roles)


def _allowed_document_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == ALLOWED_DOCUMENT_HOST
        and parsed.port is None
        and parsed.path.startswith("/large-docs/")
        and parsed.query == ""
        and parsed.fragment == ""
    )
