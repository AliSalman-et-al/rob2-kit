"""ClinicalTrials.gov v2 matching and immutable registry-source capture."""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Mapping
from enum import StrEnum
from functools import wraps
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.ingestion.service import (
    capture_source_bytes,
    registry_source,
)
from rob2_kit.sources import Source, SourceRole
from rob2_kit.storage import (
    ensure_contract_version,
    read_only_transaction,
    workspace_mutation_lock,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegistryStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class TrialFacts(_Strict):
    title: str | None = None
    randomized: bool | None = None
    enrollment: int | None = None
    interventions: tuple[str, ...] = ()


class Candidate(_Strict):
    nct_id: str
    title: str | None = None
    randomized: bool | None = None
    enrollment: int | None = None
    interventions: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    start_date: str | None = None
    completion_date: str | None = None
    provider_json: bytes


class RegistryMatch(_Strict):
    status: RegistryStatus
    candidates: tuple[Candidate, ...] = ()
    reasons: tuple[str, ...] = ()
    provider_json: bytes | None = None


class CapturedRegistryRecord(_Strict):
    trial_id: str
    status: Literal["captured"]
    source: Source
    record_json: str


class RegistryNotCaptured(_Strict):
    trial_id: str
    status: Literal["not_captured"]


CapturedRegistry = CapturedRegistryRecord | RegistryNotCaptured


class RegistryCandidateRecord(_Strict):
    trial_id: str
    match: RegistryMatch
    captured_source: Source | None = None
    projection_pages: tuple[str, ...] = Field(default=(), exclude=True)


def _candidate_path(workspace: str | Path, trial_id: str) -> Path:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", trial_id) is None:
        raise ValueError("invalid trial identifier")
    root = Path(workspace).resolve(strict=True)
    if root.is_symlink() or _reparse(root):
        raise ValueError("workspace is redirected")
    internal = root / ".rob2-kit"
    if internal.exists() and (internal.is_symlink() or _reparse(internal)):
        raise ValueError("internal workspace directory is redirected")
    parent = internal / "registry-candidates"
    if parent.exists() and (parent.is_symlink() or _reparse(parent)):
        raise ValueError("registry candidate directory is redirected")
    if not parent.is_relative_to(root):
        raise ValueError("registry candidate path escapes workspace")
    return parent / f"{trial_id}.json"


def _reparse(path: Path) -> bool:
    return bool(
        getattr(os.lstat(path), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _candidate_bytes(record: RegistryCandidateRecord) -> bytes:
    return json.dumps(
        record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _locked_registry_capture(function):
    @wraps(function)
    def locked(workspace, trial_id, match):
        with workspace_mutation_lock(workspace):
            return function(workspace, trial_id, match)

    return locked


@_locked_registry_capture
def record_registry_match(
    workspace: str | Path, trial_id: str, match: RegistryMatch
) -> RegistryCandidateRecord:
    ensure_contract_version(workspace)
    with read_only_transaction(workspace) as connection:
        if connection is not None and (
            connection.execute(
                "SELECT 1 FROM runtime_meta WHERE name='active_proposal_version'"
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM records WHERE name='active_batch' OR name LIKE 'terminal_trial:%' "
                "OR name LIKE 'batch_summary:%' LIMIT 1"
            ).fetchone()
        ):
            raise ValueError("registry capture is frozen after Proposal creation")
    prior = read_registry_match(workspace, trial_id)
    if prior is not None:
        if prior.match == match:
            return prior
        raise ValueError("registry candidate conflicts with existing attempt")
    captured = (
        capture_registry_source(str(workspace), trial_id, match)
        if match.status is RegistryStatus.MATCHED
        else None
    )
    record = RegistryCandidateRecord(
        trial_id=trial_id,
        match=match,
        captured_source=captured,
        projection_pages=(
            ()
            if captured is None or match.provider_json is None
            else (match.provider_json.decode("utf-8"),)
        ),
    )
    path = _candidate_path(workspace, trial_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or _reparse(path.parent):
        raise ValueError("registry candidate directory is redirected")
    payload = _candidate_bytes(record)
    if path.exists():
        if path.is_symlink() or _reparse(path):
            raise ValueError("registry candidate path is redirected")
        if path.read_bytes() == payload:
            return record
        raise ValueError("registry candidate conflicts with existing attempt")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() == payload:
                return record
            raise ValueError("registry candidate conflicts with existing attempt")
    finally:
        if temporary.exists():
            temporary.unlink()
    return record


def read_registry_match(workspace: str | Path, trial_id: str) -> RegistryCandidateRecord | None:
    path = _candidate_path(workspace, trial_id)
    if not path.exists():
        return None
    if path.is_symlink() or _reparse(path):
        raise ValueError("registry candidate path is redirected")
    raw = path.read_bytes()
    record = RegistryCandidateRecord.model_validate_json(raw)
    if _candidate_bytes(record) != raw or record.trial_id != trial_id:
        raise ValueError("registry candidate is not canonical or does not bind Trial")
    return record


NCT = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


class _ProviderNotFound(Exception):
    pass


class _ProviderUnavailable(Exception):
    pass


class _ProviderDataError(Exception):
    pass


def normalize_nct(value: str) -> str:
    match = NCT.fullmatch(value.strip())
    if match is None:
        raise ValueError("invalid NCT identifier")
    return match.group().upper()


def nct_candidates(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group().upper() for match in NCT.finditer(text)))


def http_request(client: httpx.Client) -> Callable[[str], Mapping[str, object]]:
    """Adapt an injected HTTPX client without hiding non-provider programming errors."""

    def request(url: str) -> Mapping[str, object]:
        try:
            response = client.get(url)
            if response.status_code == 404:
                raise _ProviderNotFound
            response.raise_for_status()
            payload = response.json()
        except _ProviderNotFound:
            raise
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            raise _ProviderUnavailable from error
        if not isinstance(payload, Mapping):
            raise _ProviderUnavailable
        return payload

    return request


def match_registry(
    facts: TrialFacts,
    request: Callable[[str], Mapping[str, object]],
    *,
    supplied_nct: str | None = None,
    main_article_text: str = "",
    title_limit: int = 5,
) -> RegistryMatch:
    """Match categorically: identifiers establish identity; facts rule out contradictions."""
    if title_limit < 1:
        raise ValueError("title_limit must be positive")
    requested = normalize_nct(supplied_nct) if supplied_nct is not None else None
    article_ids = nct_candidates(main_article_text)
    try:
        if requested is not None:
            candidate = _fetch_candidate(request, f"{_STUDIES_URL}/{requested}")
            if candidate.nct_id != requested:
                return RegistryMatch(
                    status=RegistryStatus.NOT_FOUND,
                    candidates=(candidate,),
                    reasons=(
                        "provider record NCT identifier differs from the supplied identifier",
                    ),
                )
            return _resolve_identifier(facts, (candidate,), "supplied NCT identifier")

        candidates = _fetch_article_candidates(article_ids, request)
        if facts.title is not None:
            query = urlencode(
                {"query.term": facts.title, "countTotal": "true", "pageSize": title_limit}
            )
            candidates = _unique(
                candidates + _search_candidates(request, f"{_STUDIES_URL}?{query}", title_limit)
            )
        return _resolve_discovery(facts, candidates, set(article_ids))
    except _ProviderNotFound:
        return RegistryMatch(
            status=RegistryStatus.NOT_FOUND, reasons=("registry record not found",)
        )
    except (_ProviderUnavailable, _ProviderDataError, OSError, TimeoutError):
        return RegistryMatch(
            status=RegistryStatus.UNAVAILABLE, reasons=("ClinicalTrials.gov is unavailable",)
        )


def capture_registry_source(workspace: str, trial_id: str, match: RegistryMatch) -> Source:
    if match.status is not RegistryStatus.MATCHED or match.provider_json is None:
        raise ValueError("only a matched registry record can be captured")
    return capture_source_bytes(
        workspace,
        trial_id,
        SourceRole.REGISTRY,
        "ClinicalTrials.gov registry record",
        match.provider_json,
    )


def read_captured_registry(workspace: str, trial_id: str) -> CapturedRegistry:
    """Read validated captured registry JSON without retaining process state."""
    source = registry_source(workspace, trial_id)
    if source is None:
        return RegistryNotCaptured(trial_id=trial_id, status="not_captured")
    root = Path(workspace).resolve(strict=True)
    manifest = root / ".rob2-kit" / "sources" / trial_id / "registry-sources.json"
    payload = json.loads(manifest.read_bytes())
    from rob2_kit.text_projection import TextProjectionIdentity, VerifiedProjection

    identity = TextProjectionIdentity.model_validate(payload["projections"][0])
    text = VerifiedProjection(root).pages(source, identity)[0]
    if not isinstance(json.loads(text), dict):
        raise ValueError("captured registry record is not an object")
    return CapturedRegistryRecord(
        trial_id=trial_id, status="captured", source=source, record_json=text
    )


def _fetch_candidate(request: Callable[[str], Mapping[str, object]], url: str) -> Candidate:
    try:
        payload = request(url)
    except (_ProviderNotFound, _ProviderUnavailable, OSError, TimeoutError):
        raise
    return _candidate(payload)


def _fetch_article_candidates(
    article_ids: tuple[str, ...], request: Callable[[str], Mapping[str, object]]
) -> tuple[Candidate, ...]:
    candidates: list[Candidate] = []
    for identifier in article_ids:
        try:
            candidate = _fetch_candidate(request, f"{_STUDIES_URL}/{identifier}")
        except _ProviderNotFound:
            continue
        if candidate.nct_id == identifier:
            candidates.append(candidate)
    return tuple(candidates)


def _search_candidates(
    request: Callable[[str], Mapping[str, object]], url: str, limit: int
) -> tuple[Candidate, ...]:
    payload = _fetch_payload(request, url)
    studies = payload.get("studies")
    if not isinstance(studies, list):
        raise _ProviderDataError("provider search response missing studies")
    if not all(isinstance(item, Mapping) for item in studies[:limit]):
        raise _ProviderDataError("provider search study is invalid")
    return tuple(_candidate(item) for item in studies[:limit])


def _fetch_payload(
    request: Callable[[str], Mapping[str, object]], url: str
) -> Mapping[str, object]:
    try:
        return request(url)
    except (_ProviderNotFound, _ProviderUnavailable, OSError, TimeoutError):
        raise


def _resolve_identifier(
    facts: TrialFacts, candidates: tuple[Candidate, ...], label: str
) -> RegistryMatch:
    plausible = tuple(
        candidate for candidate in candidates if not _contradictions(facts, candidate)
    )
    if len(plausible) == 1:
        selected = plausible[0]
        return RegistryMatch(
            status=RegistryStatus.MATCHED,
            candidates=candidates,
            reasons=(f"{label} agrees with returned NCT and supplied facts",),
            provider_json=selected.provider_json,
        )
    return RegistryMatch(
        status=RegistryStatus.NOT_FOUND,
        candidates=candidates,
        reasons=(f"{label} materially contradicts supplied trial facts",),
    )


def _resolve_discovery(
    facts: TrialFacts, candidates: tuple[Candidate, ...], article_ids: set[str]
) -> RegistryMatch:
    identifier_matches = tuple(
        candidate
        for candidate in candidates
        if candidate.nct_id in article_ids and not _contradictions(facts, candidate)
    )
    if identifier_matches:
        return _matched_or_ambiguous(
            identifier_matches, candidates, "exact main-article NCT identifier"
        )
    title_matches = tuple(
        candidate for candidate in candidates if _title_search_corroborates(facts, candidate)
    )
    if title_matches:
        return _matched_or_ambiguous(
            title_matches, candidates, "title search and independent design facts"
        )
    return RegistryMatch(
        status=RegistryStatus.NOT_FOUND,
        candidates=candidates,
        reasons=("no candidate met the categorical corroboration rules",),
    )


def _matched_or_ambiguous(
    plausible: tuple[Candidate, ...], candidates: tuple[Candidate, ...], reason: str
) -> RegistryMatch:
    if len(plausible) == 1:
        selected = plausible[0]
        return RegistryMatch(
            status=RegistryStatus.MATCHED,
            candidates=candidates,
            reasons=(f"one candidate corroborated by {reason}",),
            provider_json=selected.provider_json,
        )
    return RegistryMatch(
        status=RegistryStatus.AMBIGUOUS,
        candidates=candidates,
        reasons=(f"multiple candidates corroborated by {reason}",),
    )


def _candidate(payload: Mapping[str, object]) -> Candidate:
    protocol = payload.get("protocolSection", payload)
    if not isinstance(protocol, Mapping):
        raise _ProviderDataError("invalid protocol section")
    ident = _module(protocol, "identificationModule")
    design = _module(protocol, "designModule")
    arms = _module(protocol, "armsInterventionsModule")
    status = _module(protocol, "statusModule")
    conditions = _module(protocol, "conditionsModule")
    nct_id = ident.get("nctId")
    if not isinstance(nct_id, str):
        raise _ProviderDataError("missing NCT identifier")
    allocation = _module(design, "designInfo").get("allocation")
    randomized = (
        True if allocation == "RANDOMIZED" else False if allocation == "NON_RANDOMIZED" else None
    )
    enrollment = _module(design, "enrollmentInfo").get("count")
    arm_groups = arms.get("armGroups", [])
    if not isinstance(arm_groups, list):
        raise _ProviderDataError("arm groups are invalid")
    interventions: list[str] = []
    for arm in arm_groups:
        if not isinstance(arm, Mapping):
            raise _ProviderDataError("arm group is invalid")
        names = arm.get("interventionNames", [])
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise _ProviderDataError("intervention names are invalid")
        interventions.extend(names)
    listed_conditions = conditions.get("conditions", [])
    if not isinstance(listed_conditions, list) or not all(
        isinstance(item, str) for item in listed_conditions
    ):
        raise _ProviderDataError("conditions are invalid")
    return Candidate(
        nct_id=_provider_nct(nct_id),
        title=_string(ident.get("officialTitle")) or _string(ident.get("briefTitle")),
        randomized=randomized,
        enrollment=enrollment
        if isinstance(enrollment, int) and not isinstance(enrollment, bool)
        else None,
        interventions=tuple(interventions),
        conditions=tuple(listed_conditions),
        start_date=_date(status, "startDateStruct"),
        completion_date=_date(status, "completionDateStruct"),
        provider_json=_provider_json_bytes(payload),
    )


def _module(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    result = value.get(key, {})
    if not isinstance(result, Mapping):
        raise _ProviderDataError(f"{key} is invalid")
    return result


def _date(module: Mapping[str, object], key: str) -> str | None:
    value = _module(module, key).get("date")
    return value if isinstance(value, str) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _provider_nct(value: str) -> str:
    try:
        return normalize_nct(value)
    except ValueError as error:
        raise _ProviderDataError("provider NCT identifier is invalid") from error


def _contradictions(facts: TrialFacts, candidate: Candidate) -> tuple[str, ...]:
    contradictions: list[str] = []
    if facts.title is not None and (
        candidate.title is None or not _title_equal(facts.title, candidate.title)
    ):
        contradictions.append("title")
    if facts.randomized is not None and candidate.randomized is not facts.randomized:
        contradictions.append("allocation")
    if facts.enrollment is not None and candidate.enrollment != facts.enrollment:
        contradictions.append("enrollment")
    observed = {_normalise(value) for value in candidate.interventions}
    if facts.interventions and not all(
        _normalise(value) in observed for value in facts.interventions
    ):
        contradictions.append("interventions")
    return tuple(contradictions)


def _title_search_corroborates(facts: TrialFacts, candidate: Candidate) -> bool:
    if (
        facts.title is None
        or candidate.title is None
        or not _title_equal(facts.title, candidate.title)
    ):
        return False
    if _contradictions(facts, candidate):
        return False
    design_matches = sum(
        (
            facts.randomized is not None and candidate.randomized is facts.randomized,
            facts.enrollment is not None and candidate.enrollment == facts.enrollment,
            bool(facts.interventions)
            and all(
                _normalise(value) in {_normalise(item) for item in candidate.interventions}
                for value in facts.interventions
            ),
        )
    )
    return design_matches >= 2


def _title_equal(left: str, right: str) -> bool:
    return _normalise(left) == _normalise(right)


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold()))


def _unique(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        if candidate.nct_id not in seen:
            seen.add(candidate.nct_id)
            unique.append(candidate)
    return tuple(unique)


def _provider_json_bytes(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    except (TypeError, ValueError) as error:
        raise _ProviderDataError("provider record is not JSON") from error
