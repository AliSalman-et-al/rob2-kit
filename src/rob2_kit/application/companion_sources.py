"""Bounded cited-public-document acquisition, staging and explicit Source admission."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit

import httpx
import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from ..models import canonical_json_bytes
from ..workflow_models import CapturedTrial
from ._state import (
    _commit_records,
    _db,
    _identity,
    _link_like,
    _manifest,
    _pages,
    _projection_hash,
    _read,
    _result,
    _root,
    _search_derivative,
    _source_id,
    _state,
    internal_path,
)
from .contracts import WorkflowConflict
from .evidence import _find_source, _source_navigation_action, read_pages
from .intake import _manifest_registry_identifier, _manifest_registry_replay, _trial_directory
from .public_documents import MAX_DOCUMENT_BYTES, PUBLIC_DOCUMENT_HOSTS, fetch_bounded
from .source_handles import resolve_source_handle, source_handle

MAX_BYTES = MAX_DOCUMENT_BYTES


def _open_trial(root: Path, trial_id: str, expected_revision: int) -> tuple[dict, dict]:
    state = _state(root)
    if state.get("revision", 0) != expected_revision:
        raise WorkflowConflict(expected_revision, int(state.get("revision", 0)))
    if state.get("phase") != "assessment":
        raise ValueError("companion admission requires an approved open assessment")
    trial = next((t for t in state["batch"]["trials"] if t["id"] == trial_id), None)
    if (
        trial is None
        or state.get("trial_dispositions", {}).get(trial_id)
        not in {
            "pending",
            "reviewable",
        }
        or trial_id in state.get("trial_closures", {})
    ):
        raise ValueError("companion admission requires a named open Trial")
    return state, trial


@contextmanager
def _acquisition_lock(root: Path):
    """One bounded acquisition at a time; OS release also covers process death."""
    with internal_path(root, "companion-acquisition.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError(
                    "companion acquisition in progress; recover get_status after completion"
                ) from error
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError(
                    "companion acquisition in progress; recover get_status after completion"
                ) from error
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def captured_companions(root: Path, state: dict) -> list[dict]:
    sources = {
        s["id"]: s for t in (state.get("batch") or {}).get("trials", []) for s in t["sources"]
    }
    with _db(root, "canonical.sqlite3") as connection:
        identities = [
            row[0]
            for row in connection.execute(
                "SELECT identity FROM canonical_records WHERE kind='companion_candidate' "
                "ORDER BY rowid"
            )
        ]
    candidates = []
    for identity in identities:
        candidate = _read(root, f"companion_candidate:{identity}")
        if not isinstance(candidate, dict):
            continue
        parent = sources.get(candidate["reference"]["source_id"])
        if parent is not None and parent["sha256"] == candidate["parent_source_sha256"]:
            candidates.append(candidate)
    return candidates


def acquire_companion_source(
    workspace: str | Path, reference: CompanionReference, expected_revision: int
) -> dict:
    root = _root(workspace)
    _open_trial(root, reference.trial_id, expected_revision)
    with _acquisition_lock(root):
        return _acquire_companion_locked(root, reference, expected_revision)


def _acquire_companion_locked(
    workspace: str | Path,
    reference: CompanionReference,
    expected_revision: int,
) -> dict:
    """Bounded acquisition stages immutable bytes, never assessment Sources or answers."""
    root = _root(workspace)
    state, trial = _open_trial(root, reference.trial_id, expected_revision)
    reference = _canonical_reference(root, reference)
    source, _ = _validated_reference(root, reference)
    for candidate in captured_companions(root, state):
        if candidate["reference"] != reference.model_dump():
            continue
        if any(
            a["candidate"]["identity"] == candidate["identity"]
            for a in state.get("source_admissions", [])
        ):
            raise ValueError(
                "companion already admitted; recover get_status and read its Source handles"
            )
        return _result(
            "success",
            state,
            candidate_identity=candidate["identity"],
            capture=candidate["capture"],
            matching_active_source_ids=[
                source_handle(str(active["id"]))
                for active in trial["sources"]
                if active["sha256"] == candidate["capture"].get("sha256")
            ],
            document_staged=True,
            admitted_to_active_batch=False,
            document_read=False,
        )
    content, capture = _acquire(reference)
    if content is None:
        return _result(
            "success",
            state,
            candidate_identity=None,
            capture=capture,
            document_staged=False,
            admitted_to_active_batch=False,
            document_read=False,
        )
    candidate = {
        "trial_id": trial["id"],
        "reference": reference.model_dump(),
        "parent_source_sha256": source["sha256"],
        "capture": capture,
    }
    candidate["identity"] = _identity(candidate)
    folder = internal_path(
        root, "companion_candidates", candidate["identity"].removeprefix("sha256:")
    )
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "candidate.pdf"
    if path.exists() and path.read_bytes() != content:
        raise ValueError("immutable companion candidate bytes differ")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(content)
    state = _commit_records(
        root,
        state,
        expected_revision,
        {
            f"companion_candidate:{candidate['identity']}": candidate,
        },
    )
    return _result(
        "success",
        state,
        candidate_identity=candidate["identity"],
        capture=capture,
        matching_active_source_ids=[
            source_handle(str(active["id"]))
            for active in trial["sources"]
            if active["sha256"] == capture.get("sha256")
        ],
        document_staged=True,
        admitted_to_active_batch=False,
        document_read=False,
    )


def admit_companion_source(
    workspace: str | Path,
    trial_id: str,
    candidate_identity: str,
    expected_revision: int,
) -> dict:
    """Append Sources in place with exact inventory lineage and no scientific rewrite."""
    root = _root(workspace)
    state, trial = _open_trial(root, trial_id, expected_revision)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_identity):
        raise ValueError("invalid companion candidate identity")
    candidate = _read(root, f"companion_candidate:{candidate_identity}")
    if (
        not isinstance(candidate, dict)
        or candidate.get("trial_id") != trial_id
        or (
            candidate.get("identity") != candidate_identity
            or _identity({k: v for k, v in candidate.items() if k != "identity"})
            != candidate_identity
        )
    ):
        raise ValueError("companion candidate is unavailable or belongs to another Trial")
    if any(
        item["candidate"]["identity"] == candidate_identity
        for item in state.get("source_admissions", [])
    ):
        raise ValueError("companion candidate is already admitted")
    reference = CompanionReference.model_validate(candidate["reference"])
    parent, _ = _validated_reference(root, reference)
    if parent["sha256"] != candidate["parent_source_sha256"]:
        raise ValueError("companion candidate parent Source differs")
    data = internal_path(
        root, "companion_candidates", candidate_identity[7:], "candidate.pdf"
    ).read_bytes()
    if "sha256:" + hashlib.sha256(data).hexdigest() != candidate["capture"]["sha256"]:
        raise ValueError("companion candidate bytes are corrupt")
    prefix = "companions/" + candidate_identity[7:]
    added = []
    projections = []
    for relative, content, media in (
        (prefix + "/candidate.pdf", data, "application/pdf"),
        (prefix + "/capture.json", canonical_json_bytes(candidate), "application/json"),
    ):
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        source_id = _source_id(trial_id, relative, digest)
        pages = _pages(Path(relative), content)
        source = {
            "id": source_id,
            "trial_id": trial_id,
            "role": "other",
            "declared_role": "other",
            "label": relative,
            "logical_path": relative,
            "sha256": digest,
            "media_type": media,
            "page_count": len(pages),
            "origin": "cited_public_document",
            "projection_hash": _projection_hash(digest, media, pages),
        }
        path = internal_path(root, "sources", trial_id, f"{source_id}.bin")
        if path.exists() and path.read_bytes() != content:
            raise ValueError("immutable Source bytes differ")
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(content)
        added.append(source)
        projections.append((source_id, pages))
    updated = CapturedTrial.model_validate(
        {
            **{k: v for k, v in trial.items() if k != "identity"},
            "sources": [*trial["sources"], *added],
        }
    ).model_dump(mode="json")
    old_batch = state["batch"]
    batch = {
        "trials": [updated if t["id"] == trial_id else t for t in old_batch["trials"]],
        "conditions": old_batch["conditions"],
    }
    batch["identity"] = _identity(batch)
    admission: dict[str, Any] = {
        "trial_id": trial_id,
        "candidate": candidate,
        "source_ids": [s["id"] for s in added],
        "previous_batch_identity": old_batch["identity"],
        "batch_identity": batch["identity"],
        "trial_inventory_identity": updated["identity"],
    }
    admission["identity"] = _identity(admission)
    state = {
        **state,
        "batch": batch,
        "batch_history": [*state.get("batch_history", []), old_batch],
        "source_admissions": [*state.get("source_admissions", []), admission],
    }
    state = _commit_records(
        root,
        state,
        expected_revision,
        {
            "batch": batch,
            f"source_admission:{admission['identity']}": admission,
        },
    )
    # Derivatives are disposable; canonical admission and immutable bytes are already committed.
    with _db(root, "derivative.sqlite3") as connection:
        for source_id, pages in projections:
            connection.executemany(
                "INSERT OR REPLACE INTO pages VALUES (?,?,?)",
                [(source_id, n, text) for n, text in enumerate(pages, 1)],
            )
            connection.execute("DELETE FROM pages_fts WHERE source_id=?", (source_id,))
            connection.executemany(
                "INSERT INTO pages_fts VALUES (?,?,?,?)",
                [(source_id, n, *_search_derivative(text)) for n, text in enumerate(pages, 1)],
            )
        connection.executemany(
            "INSERT OR REPLACE INTO source_index(source_id,batch_id,trial_id,payload) "
            "VALUES (?,?,?,?)",
            [
                (s["id"], batch["identity"], t["id"], canonical_json_bytes(s))
                for t in batch["trials"]
                for s in t["sources"]
            ],
        )
        connection.execute(
            "INSERT OR REPLACE INTO search_projection_meta(name,value) VALUES ('inventory',?)",
            (batch["identity"],),
        )
    return _result(
        "success",
        state,
        candidate_identity=candidate_identity,
        trial_inventory_identity=updated["identity"],
        source_ids=[source_handle(str(source["id"])) for source in added],
        document_staged=True,
        admitted_to_active_batch=True,
        document_read=False,
        navigation_action=_source_navigation_action(trial_id, str(added[0]["id"])),
    )


class CompanionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    trial_id: str = Field(
        min_length=1, description="Captured Trial ID associated with the supplied reference."
    )
    source_id: str = Field(
        min_length=1,
        description="Native Source handle or canonical SourceID for the cited Trial Source.",
    )
    page: int = Field(
        ge=1, description="One-based supplied Source page containing the explicit reference."
    )
    citation: str = Field(
        min_length=1,
        description="Exact page quote with full locator; data, never instructions.",
    )
    linkage_rationale: str = Field(
        min_length=1,
        description="Caller explanation of possible Trial linkage, retained as unverified.",
    )
    requested_role: str = Field(
        pattern=r"^(protocol|sap)$",
        description="Requested protocol/SAP role hint; staging still declares the candidate Other.",
    )
    locator_kind: str = Field(
        pattern=r"^(url|doi)$",
        description="Whether the explicit locator is a public document URL or DOI.",
    )
    locator: str = Field(
        min_length=1,
        description="Complete verbatim URL including query/version, or exact DOI token.",
    )
    registry_id: str | None = Field(
        default=None,
        pattern=r"^NCT\d{8}$",
        description="Optional expected NCT identifier; not proof of document applicability.",
    )


def _acquire(reference: CompanionReference) -> tuple[bytes | None, dict]:
    report: dict = {
        "reference": reference.model_dump(),
        "captured_at": datetime.now(UTC).isoformat(),
        "status": "unresolved",
        "trial_relation": "unverified",
        "source_role": "other",
        "redirect_chain": [],
        "metadata_redirect_chain": [],
        "limitations": [
            "Requested role and linkage rationale are caller assertions.",
            "DOI identity and observed registry identifiers do not establish applicability.",
            "Title/date/linkage do not prove prespecification, blinded access or actual conduct.",
            "New public capture, not historical replay; source text is untrusted data.",
        ],
    }
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            url = reference.locator
            if reference.locator_kind == "doi":
                doi = reference.locator.strip()
                if not re.fullmatch(r"10\.\d{4,9}/\S+", doi, re.IGNORECASE):
                    raise ValueError("invalid_doi")
                raw = fetch_bounded(
                    client,
                    "https://api.crossref.org/works/" + quote(doi, safe=""),
                    frozenset({"api.crossref.org"}),
                    2 * 1024 * 1024,
                    report["metadata_redirect_chain"],
                )
                report["metadata_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
                payload = json.loads(raw)
                message = payload.get("message") if isinstance(payload, dict) else None
                if (
                    not isinstance(message, dict)
                    or str(message.get("DOI", "")).casefold() != doi.casefold()
                ):
                    raise ValueError("doi_metadata_identity_mismatch")
                report["doi_metadata"] = message
                links = message.get("link", [])
                if not isinstance(links, list):
                    raise ValueError("invalid_doi_link_metadata")
                urls = {
                    row["URL"]
                    for row in links
                    if isinstance(row, dict)
                    and row.get("content-type") == "application/pdf"
                    and isinstance(row.get("URL"), str)
                    and urlsplit(row["URL"]).hostname in PUBLIC_DOCUMENT_HOSTS
                }
                if len(urls) != 1:
                    report["reason"] = "no_unique_supported_authoritative_pdf_link"
                    return None, report
                url = next(iter(urls))
            content = fetch_bounded(
                client, url, PUBLIC_DOCUMENT_HOSTS, MAX_BYTES, report["redirect_chain"]
            )
        if not content.startswith(b"%PDF-"):
            raise ValueError("not_pdf_content")
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            if pdf.is_encrypted or not pdf.page_count:
                raise ValueError("encrypted_or_empty_pdf")
            identity = document_registry_observations(
                [page.get_text() for page in pdf], reference.registry_id
            )
            report["page_count"] = pdf.page_count
            report["pdf_metadata"] = pdf.metadata
        report.update(
            retrieved_at=datetime.now(UTC).isoformat(),
            status="captured",
            **identity,
            source_url=report["redirect_chain"][-1],
            media_type="application/pdf",
            sha256="sha256:" + hashlib.sha256(content).hexdigest(),
            byte_count=len(content),
        )
        return content, report
    except (httpx.HTTPError, ValueError, OSError, pymupdf.FileDataError) as error:
        report.update(
            status="unresolved",
            reason=str(error) if isinstance(error, ValueError) else type(error).__name__,
        )
        return None, report


def document_registry_observations(pages: list[str], expected: str | None) -> dict:
    """Literal observations; a body citation is not a document identity claim."""
    mentions = []
    claims = []
    for number, text in enumerate(pages, 1):
        for match in re.finditer(r"\bNCT\d{8}\b", text):
            mentions.append(
                {
                    "registry_id": match.group(),
                    "page": number,
                    "snippet": text[max(0, match.start() - 160) : match.end() + 160],
                    "interpretation": "unclassified_document_mention",
                }
            )
        # A narrowly labelled front-matter claim is stronger than an incidental
        # mention. Preserve its literal basis; it still cannot prove applicability.
        if number <= 2:
            pattern = (
                r"(?im)^\s*(?:ClinicalTrials.gov Identifiers?|"
                r"Trial registration(?: numbers?)?|Registry IDs?)\s*[:=]\s*([^\n]{1,300})"
            )
            for match in re.finditer(pattern, text):
                for identifier in re.findall(r"\bNCT\d{8}\b", match.group(1)):
                    claims.append(
                        {
                            "registry_id": identifier,
                            "page": number,
                            "snippet": match.group().strip(),
                            "interpretation": "explicit_front_matter_registration_claim",
                        }
                    )
    ids = sorted({item["registry_id"] for item in mentions})
    declared = sorted({item["registry_id"] for item in claims})
    relation = "unverified"
    if expected and len(declared) == 1:
        relation = (
            "document_registration_claim_matches"
            if declared == [expected]
            else "document_registration_claim_differs"
        )
    elif len(declared) > 1:
        relation = "multiple_document_registration_claims"
    elif expected and any(identifier != expected for identifier in ids):
        relation = "other_identifiers_observed"
    return {
        "trial_relation": relation,
        "observed_registry_ids": ids,
        "registry_identifier_mentions": mentions,
        "document_registration_claims": claims,
        "applicability": "unverified",
    }


def _canonical_reference(root: Path, reference: CompanionReference) -> CompanionReference:
    if reference.source_id.startswith("sh_"):
        return reference.model_copy(
            update={
                "source_id": resolve_source_handle(root, reference.trial_id, reference.source_id)
            }
        )
    return reference


def _locator_present(reference: CompanionReference, text: str) -> bool:
    tokens = re.findall(r'https?://[^\s<>"\']+|(?<![A-Za-z0-9])10\.\d{4,9}/[^\s<>"\']+', text)
    if reference.locator_kind == "url":
        return reference.locator in tokens
    for token in tokens:
        parsed = urlsplit(token)
        if (
            parsed.hostname in {"doi.org", "dx.doi.org"}
            and not parsed.query
            and not parsed.fragment
        ):
            token = unquote(parsed.path.lstrip("/"))
        if token.casefold() == reference.locator.casefold():
            return True
        # Citation punctuation is outside the DOI identity. Keep internal punctuation
        # and balanced suffix parentheses; never accept an arbitrary DOI prefix.
        token = token.rstrip(".,;:")
        wrappers = {")": "(", "]": "[", "}": "{"}
        while token and token[-1] in wrappers:
            closing = token[-1]
            if token.count(closing) <= token.count(wrappers[closing]):
                break
            token = token[:-1].rstrip(".,;:")
        if token.casefold() == reference.locator.casefold():
            return True
    return False


def _validated_reference(root: Path, reference: CompanionReference) -> tuple[dict, dict]:
    source = _find_source(root, reference.trial_id, reference.source_id)
    page = read_pages(root, reference.trial_id, reference.source_id, [reference.page])["pages"][0]
    if reference.citation not in page["text"]:
        raise ValueError("citation must occur in the supplied Source page text")
    trials = _state(root).get("batch", {}).get("trials", [])
    trial = next((t for t in trials if t["id"] == reference.trial_id), None)
    if trial is None:
        raise ValueError("unknown captured Trial")
    locator_found = _locator_present(reference, reference.citation) and _locator_present(
        reference, page["text"]
    )
    if (
        reference.locator_kind == "url"
        and source["role"] == "registry"
        and source["origin"] == "registry"
        and urlsplit(reference.locator).hostname == "cdn.clinicaltrials.gov"
    ):
        filename = Path(urlsplit(reference.locator).path).name
        nct = reference.registry_id
        locator_found = bool(
            nct
            and nct == trial["registry"].get("registry_id")
            and re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", filename)
            and reference.locator
            == (f"https://cdn.clinicaltrials.gov/large-docs/{nct[-2:]}/{nct}/{filename}")
            and json.dumps(filename) in reference.citation
            and json.dumps(filename) in page["text"]
        )
    if not locator_found:
        raise ValueError("locator must be explicitly present in the cited reference")
    return source, trial


def _input_transfer(root: Path, trial_id: str) -> dict:
    """Forecast bytes copied and captures omitted, without claiming corpus equivalence."""
    if _link_like(root / "input"):
        raise ValueError("input symlinks or junctions are unsupported")
    inputs = []
    registry_settings = []
    for path in sorted((root / "input").rglob("*")):
        if _link_like(path):
            raise ValueError("input symlinks are unsupported for prospective staging")
        if path.is_file():
            inputs.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    for directory in sorted((root / "input").iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        config = _manifest(directory)
        nct = _manifest_registry_identifier(config)
        if nct:
            replay = _manifest_registry_replay(config)
            acquisition = isinstance(config.get("registry"), dict) and config["registry"].get(
                "acquire_documents", False
            )
            registry_settings.append(
                {
                    "trial_directory": directory.name,
                    "registry_id": nct,
                    "registry_mode": "replay" if replay else "current_fetch",
                    "acquire_current_documents": bool(acquisition),
                }
            )
    sources = []
    for trial in _state(root)["batch"]["trials"]:
        directory = _trial_directory(root, trial["label"])
        by_path = {item["path"]: item["sha256"] for item in inputs}
        config = _manifest(directory)
        replay = _manifest_registry_replay(config)
        for source in trial["sources"]:
            relative = (directory / source["logical_path"]).relative_to(root).as_posix()
            if relative in by_path:
                status = (
                    "copied_input_bytes_match"
                    if by_path[relative] == source["sha256"]
                    else "copied_input_differs_from_capture"
                )
            elif (
                source["role"] == "registry"
                and replay
                and by_path.get((directory / replay["replay"]).relative_to(root).as_posix())
                == source["sha256"]
            ):
                status = "registry_replay_input_bytes_match"
            else:
                status = "captured_source_not_in_copied_input"
            sources.append(
                {
                    "source_id": source["id"],
                    "trial_id": trial["id"],
                    "logical_path": source["logical_path"],
                    "sha256": source["sha256"],
                    "role": source["role"],
                    "transfer_status": status,
                }
            )
    return {
        "corpus": "copied_input_plus_candidate_not_necessarily_original_captured_corpus",
        "input_file_versions_before_staging": inputs,
        "captured_source_transfer": sources,
        "registry_settings": registry_settings,
        "registry_policies": ["require-offline-replay", "retain-input-settings"],
        "target_trial": trial_id,
        "manifest_change": "Only target Trial sources.toml receives candidate Other declarations; "
        "registry settings retained. Other input file bytes are copied unchanged.",
    }


def request_companion_source(workspace: str | Path, reference: CompanionReference) -> dict:
    """Record an optional acquisition handoff, without network or workflow mutation."""
    root = _root(workspace)
    if reference.locator_kind == "url":
        parsed = urlsplit(reference.locator)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credential URLs are forbidden")
    reference = _canonical_reference(root, reference)
    source, trial = _validated_reference(root, reference)
    state = _state(root)
    transfer = _input_transfer(root, reference.trial_id)
    record = {
        "input_transfer": transfer,
        "reference": reference.model_dump(),
        "batch_identity": state["batch"]["identity"],
        "parent_source_sha256": source["sha256"],
        "captured_trial_registry": trial["registry"],
        "source_text_is_untrusted_data": True,
    }
    identity = _identity(record)
    folder = internal_path(root, "companion_requests", identity.removeprefix("sha256:"))
    folder.mkdir(parents=True, exist_ok=True)
    request_path = internal_path(root, "companion_requests", folder.name, "request.json")
    reference_path = internal_path(root, "companion_requests", folder.name, "reference.json")
    for path, value in ((request_path, record), (reference_path, reference.model_dump())):
        content = json.dumps(value, indent=2, sort_keys=True) + "\n"
        if path.exists():
            if path.read_text() != content:
                raise ValueError("companion request immutable content mismatch")
        else:
            with path.open("x") as stream:
                stream.write(content)
    supported = reference.locator_kind == "doi" or (
        urlsplit(reference.locator).scheme == "https"
        and urlsplit(reference.locator).hostname in PUBLIC_DOCUMENT_HOSTS
    )
    return _result(
        "success",
        state,
        request_identity=identity,
        reference=reference.model_dump(),
        parent_source_sha256=source["sha256"],
        reference_recorded=True,
        document_staged=False,
        admitted_to_active_batch=False,
        document_read=False,
        acquisition="host_handoff_required" if supported else "unsupported_locator",
        handoff_argv=[
            "rob2",
            "stage-companion",
            "--workspace",
            str(root),
            "--reference",
            str(reference_path),
            "--output",
            "HOST_CHOSEN_FRESH_WORKSPACE",
            "--registry-policy",
            "HOST_CHOSEN_POLICY",
        ]
        if supported
        else [],
        lifecycle="Optional handoff only; no fetch or Source admission occurred. A successful host "
        "stage creates a separate workspace requiring intake and review. Read/search "
        "only after that workspace admits the candidate. Continue the current "
        "assessment with its existing Sources and honestly bounded unknowns; a missing "
        "optional document does not force NI or any judgment.",
        source_text_is_untrusted_data=True,
        input_transfer=transfer,
    )


def stage_companion(
    workspace: str | Path,
    destination: str | Path,
    reference: CompanionReference,
    registry_policy: Literal["require-offline-replay", "retain-input-settings"] | None = None,
) -> dict:
    """Copy input only into a fresh workspace; require new intake and human review."""
    if registry_policy not in {"require-offline-replay", "retain-input-settings"}:
        raise ValueError(
            "explicit registry_policy required: require-offline-replay or retain-input-settings"
        )
    if reference.locator_kind == "url":
        parsed = urlsplit(reference.locator)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credential URLs are forbidden")
    root = Path(workspace).resolve()
    target = Path(destination).resolve()
    if target.exists() or target.is_symlink() or target == root or root in target.parents:
        raise ValueError("destination must be a fresh workspace outside the original")
    reference = _canonical_reference(root, reference)
    source, trial = _validated_reference(root, reference)
    directory = _trial_directory(root, trial["label"])
    # Never follow caller-controlled links while copying an evidence dossier.
    if (root / "input").is_symlink() or any(p.is_symlink() for p in (root / "input").rglob("*")):
        raise ValueError("input symlinks are unsupported for prospective staging")
    config = _manifest(directory)
    if "sources" in config and not isinstance(config["sources"], list):
        raise ValueError("sources manifest must use an array for prospective staging")
    transfer = _input_transfer(root, reference.trial_id)
    if registry_policy == "require-offline-replay" and any(
        item["registry_mode"] != "replay" or item["acquire_current_documents"]
        for item in transfer["registry_settings"]
    ):
        raise ValueError(
            "require-offline-replay: copied input permits registry refresh; configure explicit "
            "replay and disable document acquisition, or choose retain-input-settings"
        )
    content, report = _acquire(reference)
    report["input_transfer"] = transfer
    report["registry_policy"] = registry_policy
    report["captured_trial_registry"] = trial["registry"]
    expected = trial["registry"].get("registry_id")
    if expected and reference.registry_id and expected != reference.registry_id:
        report["trial_relation"] = "caller_registry_conflicts_with_captured_trial"
    report["parent_reference"] = {
        "source_id": source["id"],
        "sha256": source["sha256"],
        "logical_path": source["logical_path"],
        "page": reference.page,
        "citation": reference.citation,
    }
    report["lifecycle"] = "fresh_prospective_workspace_requires_intake_and_review"
    report["document_staged"] = content is not None
    report["admitted_to_active_batch"] = False
    report["host_document_read"] = False
    version = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:16]
    shutil.copytree(root / "input", target / "input", symlinks=True)
    if any(_link_like(path) for path in (target / "input").rglob("*")):
        raise ValueError("input_link_during_staging: incomplete new workspace preserved")
    for item in transfer["input_file_versions_before_staging"]:
        copied = target / item["path"]
        if (
            _link_like(copied)
            or "sha256:" + hashlib.sha256(copied.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError(
                "input_changed_during_staging: incomplete new workspace preserved; "
                "no candidate admitted"
            )
    candidate = target / directory.relative_to(root) / "companion_candidates" / version
    candidate.mkdir(parents=True)
    if content is not None:
        (candidate / "candidate.pdf").write_bytes(content)
    manifest = target / directory.relative_to(root) / "sources.toml"
    with manifest.open("a") as stream:
        for name in (["candidate.pdf"] if content is not None else []) + ["capture.json"]:
            relative = (candidate / name).relative_to(manifest.parent).as_posix()
            stream.write("\n[[sources]]\npath = " + json.dumps(relative) + '\nrole = "other"\n')
    (candidate / "capture.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return {
        "outcome": report["status"],
        "destination": str(target),
        "candidate_path": str(candidate.relative_to(target)),
        "capture": report,
    }
