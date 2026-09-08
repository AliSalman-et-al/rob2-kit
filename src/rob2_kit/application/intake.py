import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pymupdf

from ..models import canonical_json_bytes
from ..workflow_models import (
    CapturedBatch,
    CapturedTrial,
    ExpectedRevision,
    ReviewAcknowledgment,
    TrialDeclaration,
)
from ._state import (
    _PAGE_PROJECTION_VERSION,
    _commit_records,
    _db,
    _ensure,
    _identity,
    _link_like,
    _manifest,
    _pages,
    _projection_hash,
    _read,
    _reserved_role,
    _result,
    _root,
    _search_derivative,
    _source_id,
    _state,
    _supported,
    internal_path,
)
from .contracts import WorkflowConflict
from .status import _continuation


@dataclass(frozen=True, slots=True)
class _RegistryCapture:
    outcome: dict[str, Any]
    content: bytes | None = None


def _registry_record(nct: object) -> _RegistryCapture:
    """Normalize the registry boundary into one closed, persisted outcome."""
    # Manifest data may identify the requested registry record, but it cannot
    # supply a provider outcome.  In particular, ``kind=matched`` and a
    # hand-written title are not evidence of a ClinicalTrials.gov match.
    if not isinstance(nct, str) or not re.fullmatch(r"NCT\d{8}", nct):
        return _RegistryCapture(
            {
                "kind": "not_found",
                "query": str(nct or "undeclared"),
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )

    # A syntactically valid identifier is only a query.  It is not evidence
    # that the requested trial exists, much less that its title matches this
    # dossier.  Resolve it through the provider and fail closed when the
    # provider cannot supply a complete record.
    return _fetch_registry_record(nct)


def _fetch_registry_record(nct: str) -> _RegistryCapture:
    """Fetch one exact ClinicalTrials.gov record using a fixed request shape."""

    url = f"https://clinicaltrials.gov/api/v2/studies/{nct}"
    retrieved = datetime.now(UTC).isoformat()
    try:
        response = httpx.get(
            url,
            headers={"Accept": "application/json"},
            follow_redirects=False,
            timeout=5.0,
        )
    except httpx.HTTPError as error:
        return _RegistryCapture(
            {
                "kind": "unavailable",
                "query": nct,
                "reason": f"ClinicalTrials.gov request failed: {type(error).__name__}",
                "retrieved_at": retrieved,
            }
        )
    if response.status_code == 404:
        return _RegistryCapture({"kind": "not_found", "query": nct, "retrieved_at": retrieved})
    if response.status_code < 200 or response.status_code >= 300:
        return _RegistryCapture(
            {
                "kind": "unavailable",
                "query": nct,
                "reason": f"ClinicalTrials.gov returned HTTP {response.status_code}",
                "retrieved_at": retrieved,
            }
        )
    try:
        payload = response.json()
    except ValueError:
        return _RegistryCapture(
            {
                "kind": "unavailable",
                "query": nct,
                "reason": "ClinicalTrials.gov returned invalid JSON",
                "retrieved_at": retrieved,
            }
        )
    if not isinstance(payload, dict):
        return _RegistryCapture(
            {
                "kind": "unavailable",
                "query": nct,
                "reason": "ClinicalTrials.gov returned an invalid record",
                "retrieved_at": retrieved,
            }
        )
    protocol = payload.get("protocolSection")
    identification = protocol.get("identificationModule") if isinstance(protocol, dict) else None
    registry_id = identification.get("nctId") if isinstance(identification, dict) else None
    title = identification.get("officialTitle") if isinstance(identification, dict) else None
    if not isinstance(title, str) or not title.strip():
        title = identification.get("briefTitle") if isinstance(identification, dict) else None
    if not isinstance(registry_id, str) or not registry_id.strip() or not isinstance(title, str):
        return _RegistryCapture(
            {
                "kind": "unavailable",
                "query": nct,
                "reason": "ClinicalTrials.gov record is missing identity or title",
                "retrieved_at": retrieved,
            }
        )
    if registry_id.upper() != nct:
        return _RegistryCapture(
            {
                "kind": "contradiction",
                "registry_id": registry_id,
                "facts": [f"ClinicalTrials.gov returned {registry_id} for requested {nct}"],
                "retrieved_at": retrieved,
            }
        )
    # Keep the captured provider record deterministic but readable.  Compact
    # API JSON is often one enormous physical line, which is unusable as an
    # MCP line-addressed page.  The canonical JSON projection remains fully
    # auditable because its Source hash is computed from these exact bytes.
    readable_content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    )
    return _RegistryCapture(
        {
            "kind": "matched",
            "registry_id": nct,
            "title": title,
            "url": f"https://clinicaltrials.gov/study/{nct}",
            "retrieved_at": retrieved,
        },
        readable_content,
    )


def _manifest_registry_identifier(config: dict[str, Any]) -> str | None:
    """Return one manifest identifier, rejecting competing spellings."""

    registry = config.get("registry")
    declarations: list[tuple[str, object]] = []
    for key in ("nct", "nct_id"):
        if key in config:
            declarations.append((key, config[key]))
    if isinstance(registry, dict):
        unsupported = sorted(set(registry) - {"nct", "nct_id", "registry_id"})
        if unsupported:
            raise ValueError("sources.toml registry may contain only an authoritative identifier")
        for key in ("nct", "nct_id", "registry_id"):
            if key in registry:
                declarations.append((f"registry.{key}", registry[key]))
    elif registry is not None:
        raise ValueError("sources.toml registry must be a table")
    if len(declarations) > 1:
        names = ", ".join(name for name, _value in declarations)
        raise ValueError(f"ambiguous registry identifier declarations: {names}")
    return None if not declarations else str(declarations[0][1])


def _is_contained_source(directory: Path, path: Path) -> bool:
    """Accept only ordinary files reached without symlinks or junctions."""
    try:
        relative = path.relative_to(directory)
        resolved_directory = directory.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except (OSError, ValueError):
        return False
    current = directory
    for part in relative.parts:
        current = current / part
        if _link_like(current):
            return False
    return resolved_path.is_relative_to(resolved_directory)


def _trial_directory(root: Path, label: str) -> Path:
    """Resolve one declared Trial to its server-owned ``input/<name>`` dossier."""
    input_root = root / "input"
    if not input_root.is_dir() or _link_like(input_root):
        raise ValueError("input directory is not available")
    candidates = [
        path
        for path in input_root.iterdir()
        if path.is_dir() and not _link_like(path) and not path.name.startswith(".")
    ]
    for path in candidates:
        if path.name == label:
            return path
    raise ValueError(f"trial directory is not available: input/{label}")


_TRIAL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def _trial_directories(root: Path) -> list[Path]:
    """Return the researcher-owned Trial dossiers in deterministic order."""
    input_root = root / "input"
    if not input_root.is_dir() or _link_like(input_root):
        raise ValueError("input directory is not available")
    return sorted(
        (
            path
            for path in input_root.iterdir()
            if path.is_dir() and not path.name.startswith(".") and not _link_like(path)
        ),
        key=lambda path: (
            unicodedata.normalize("NFKC", path.name).casefold(),
            unicodedata.normalize("NFKC", path.name),
            path.name,
        ),
    )


def _trial_id_from_directory(label: str) -> str:
    """Derive a stable, readable Trial ID, with a hash for unrepresentable names."""
    normalized = unicodedata.normalize("NFKD", label).casefold().strip()
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    if _TRIAL_ID_PATTERN.fullmatch(slug or ""):
        return slug
    digest = hashlib.sha256(unicodedata.normalize("NFKC", label).encode("utf-8")).hexdigest()
    return f"trial-{digest[:16]}"


def prepare_batch_for_outcome(
    workspace: str | Path,
    requested_outcome: str,
    expected_revision: ExpectedRevision,
    trial_labels: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Discover selected Trial dossiers and prepare one Batch for one outcome."""
    if not isinstance(requested_outcome, str) or not requested_outcome.strip():
        raise ValueError("requested_outcome must contain non-whitespace content")
    root = _root(workspace)
    _ensure(root)
    directories = _trial_directories(root)
    if trial_labels is not None:
        if not trial_labels:
            raise ValueError("trial_labels must contain at least one directory label")
        if any(not isinstance(label, str) or not label.strip() for label in trial_labels):
            raise ValueError("trial_labels must contain non-blank directory labels")
        if len(set(trial_labels)) != len(trial_labels):
            raise ValueError("trial_labels must not contain duplicate directory labels")
        available = {directory.name: directory for directory in directories}
        unknown = next((label for label in trial_labels if label not in available), None)
        if unknown is not None:
            raise ValueError(f"unknown trial label: input/{unknown}")
        requested = set(trial_labels)
        directories = [directory for directory in directories if directory.name in requested]
    if not directories:
        raise ValueError("input directory contains no Trial directories")
    declarations: list[TrialDeclaration] = []
    seen_ids: set[str] = set()
    for directory in directories:
        trial_id = _trial_id_from_directory(directory.name)
        if trial_id in seen_ids:
            raise ValueError(
                f"Trial directory names produce a duplicate Trial ID: input/{directory.name}"
            )
        seen_ids.add(trial_id)
        declarations.append(
            TrialDeclaration(
                id=trial_id,
                label=directory.name,
                requested_outcome=requested_outcome,
            )
        )
    return prepare_batch(root, declarations, expected_revision)


def prepare_batch(
    workspace: str | Path,
    trials: list[TrialDeclaration] | tuple[TrialDeclaration, ...],
    expected_revision: ExpectedRevision,
) -> dict[str, Any]:
    normalized_trials: list[dict[str, Any]] = []
    for item in trials:
        normalized_trials.append(item.model_dump(mode="json"))
    declaration_identity = _identity({"trials": normalized_trials})
    root = _root(workspace)
    _ensure(root)
    current = _state(root)
    existing_batch = current.get("batch")
    existing_declaration_identity = current.get("declaration_identity")
    if isinstance(existing_batch, dict) and isinstance(existing_declaration_identity, str):
        if declaration_identity == existing_declaration_identity:
            return _result("success", current, batch=existing_batch, retry=True)
        if expected_revision != current.get("revision", 0):
            raise WorkflowConflict(expected_revision, int(current.get("revision", 0)))
        raise ValueError("prepare_batch declarations differ from the existing batch")
    if expected_revision != current.get("revision", 0):
        raise WorkflowConflict(expected_revision, int(current.get("revision", 0)))
    if isinstance(existing_batch, dict):
        raise ValueError("intake state is missing declaration identity")
    if current.get("phase") != "empty":
        raise ValueError("prepare_batch is not the current operation")
    # This recipe version is canonical workspace metadata rather than a
    # disposable derivative flag.  It survives deletion/rebuild of the
    # derivative database and lets a later code version reject old page
    # coordinates instead of silently changing their meaning.
    with _db(root, "canonical.sqlite3") as connection:
        connection.execute(
            "INSERT OR REPLACE INTO meta(name,value) VALUES ('page_projection',?)",
            (_PAGE_PROJECTION_VERSION,),
        )
    seen_trial_ids: set[str] = set()
    seen_directories: set[Path] = set()
    resolved_trials: list[tuple[dict[str, Any], Path]] = []
    for raw_trial in normalized_trials:
        trial_id = raw_trial["id"]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", trial_id) is None:
            raise ValueError("invalid trial identifier")
        if trial_id in seen_trial_ids:
            raise ValueError("duplicate trial identifier")
        seen_trial_ids.add(trial_id)
        directory = _trial_directory(root, str(raw_trial["label"]))
        if directory in seen_directories:
            raise ValueError(f"duplicate trial directory: input/{directory.name}")
        seen_directories.add(directory)
        resolved_trials.append((raw_trial, directory))

    captured: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    source_root = internal_path(root, "sources")
    source_root.mkdir(exist_ok=True)
    for raw_trial, directory in resolved_trials:
        trial_id = raw_trial["id"]
        manifest_path = directory / "sources.toml"
        if (manifest_path.exists() or _link_like(manifest_path)) and not _is_contained_source(
            directory, manifest_path
        ):
            raise ValueError(f"sources.toml is outside the Trial directory: input/{directory.name}")
        config = _manifest(directory)
        omissions = config.get("omissions", [])
        if not isinstance(omissions, list):
            raise ValueError("sources.toml omissions must be a list")
        omission_paths = [
            item if isinstance(item, str) else str(item.get("path", "")) for item in omissions
        ]
        omission_records = [
            item
            if isinstance(item, dict)
            else {"path": item, "reason": "other", "rationale": "omitted by sources.toml"}
            for item in omissions
        ]
        role_map = config.get("roles", {})
        if not isinstance(role_map, dict):
            raise ValueError("sources.toml roles must be a table")
        if isinstance(config.get("sources"), list):
            role_map = {
                str(item.get("path", item.get("file", ""))): item.get("role", "other")
                for item in config["sources"]
                if isinstance(item, dict)
            }
        nct = _manifest_registry_identifier(config)
        records: list[dict[str, Any]] = []
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if (
                not path.is_file()
                or path.name == "sources.toml"
                or not _is_contained_source(directory, path)
            ):
                continue
            relative = path.relative_to(directory).as_posix()
            if any(part.startswith(".") for part in Path(relative).parts):
                continue
            data = path.read_bytes()
            if not _supported(path, data):
                continue
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            source_id = _source_id(trial_id, relative, digest)
            if relative in omission_paths or path.name in omission_paths:
                continue
            try:
                pages = _pages(path, data)
            except (UnicodeDecodeError, ValueError, pymupdf.FileDataError):
                conditions.append(
                    {"code": "unreadable_source", "trial_id": trial_id, "path": relative}
                )
                continue
            target = internal_path(root, "sources", trial_id, f"{source_id}.bin")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            role = str(role_map.get(relative, role_map.get(path.name, _reserved_role(relative))))
            record = {
                "id": source_id,
                "trial_id": trial_id,
                "role": role,
                "label": path.name,
                "logical_path": relative,
                "sha256": digest,
                "media_type": "application/pdf" if data.startswith(b"%PDF-") else "text/plain",
                "page_count": len(pages),
                "origin": "local_dossier",
                "projection_hash": _projection_hash(
                    digest,
                    "application/pdf" if data.startswith(b"%PDF-") else "text/plain",
                    pages,
                ),
            }
            records.append(record)
            with _db(root, "derivative.sqlite3") as derivative:
                derivative.executemany(
                    "INSERT OR REPLACE INTO pages VALUES (?,?,?)",
                    [(source_id, number, text) for number, text in enumerate(pages, 1)],
                )
                derivative.execute("DELETE FROM pages_fts WHERE source_id=?", (source_id,))
                derivative.executemany(
                    "INSERT INTO pages_fts VALUES (?,?,?,?)",
                    [
                        (source_id, number, *_search_derivative(text))
                        for number, text in enumerate(pages, 1)
                    ],
                )
        registry_capture = _registry_record(nct)
        registry_record = registry_capture.outcome
        if registry_capture.content is not None:
            relative = f"registry/{nct}.json"
            data = registry_capture.content
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            source_id = _source_id(trial_id, relative, digest)
            pages = _pages(Path(relative), data)
            media_type = "application/json"
            target = internal_path(root, "sources", trial_id, f"{source_id}.bin")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            records.append(
                {
                    "id": source_id,
                    "trial_id": trial_id,
                    "role": "registry",
                    "label": f"ClinicalTrials.gov {nct}",
                    "logical_path": relative,
                    "sha256": digest,
                    "media_type": media_type,
                    "page_count": len(pages),
                    "origin": "registry",
                    "projection_hash": _projection_hash(digest, media_type, pages),
                }
            )
            with _db(root, "derivative.sqlite3") as derivative:
                derivative.executemany(
                    "INSERT OR REPLACE INTO pages VALUES (?,?,?)",
                    [(source_id, number, text) for number, text in enumerate(pages, 1)],
                )
                derivative.execute("DELETE FROM pages_fts WHERE source_id=?", (source_id,))
                derivative.executemany(
                    "INSERT INTO pages_fts VALUES (?,?,?,?)",
                    [
                        (source_id, number, *_search_derivative(text))
                        for number, text in enumerate(pages, 1)
                    ],
                )
        if nct is not None and (not isinstance(nct, str) or not re.fullmatch(r"NCT\d{8}", nct)):
            conditions.append(
                {"code": "invalid_registry_identifier", "trial_id": trial_id, "value": str(nct)}
            )
        # A plain dossier has no registry claim to review.  A manifest that
        # declares an authoritative NCT or registry outcome does.
        if (nct is not None or "registry" in config) and registry_record.get("kind") != "matched":
            conditions.append(
                {
                    "code": "registry_review",
                    "trial_id": trial_id,
                    "outcome": registry_record,
                }
            )
        if omissions:
            conditions.append(
                {
                    "code": "omission_review",
                    "trial_id": trial_id,
                    "paths": omission_paths,
                    "records": omission_records,
                }
            )
        if not records:
            conditions.append({"code": "no_supported_sources", "trial_id": trial_id})
        captured_trial = {
            "id": trial_id,
            "label": raw_trial["label"],
            "requested_outcome": raw_trial["requested_outcome"],
            "sources": records,
            "registry": registry_record,
            "omissions": omission_records,
        }
        captured.append(CapturedTrial.model_validate(captured_trial).model_dump(mode="json"))
    batch = {"trials": captured, "conditions": conditions}
    batch["identity"] = _identity(batch)
    # Validate the complete canonical Batch before creating any derivative
    # indexes or committing the workflow head.  Intake conditions are kept in
    # the public condition vocabulary; the workflow model validates their
    # typed presence while the persisted fields above remain closed below.
    CapturedBatch.model_validate(
        {
            "trials": batch["trials"],
            "conditions": [
                {
                    "kind": "review_condition",
                    "code": condition["code"],
                    "trial_id": condition.get("trial_id"),
                    "detail": condition["code"],
                }
                for condition in batch["conditions"]
            ],
            "identity": None,
        }
    )
    # Keep an indexed direct resolver for immutable Source handles.  The
    # payload remains derivative navigation state; Canonical retains the
    # captured Source record and bytes.
    with _db(root, "derivative.sqlite3") as derivative:
        derivative.executemany(
            "INSERT OR REPLACE INTO source_index(source_id,batch_id,trial_id,payload) "
            "VALUES (?,?,?,?)",
            [
                (source["id"], batch["identity"], trial["id"], canonical_json_bytes(source))
                for trial in captured
                for source in trial["sources"]
            ],
        )
    state = {
        **current,
        "phase": "proposal",
        "declaration_identity": declaration_identity,
        "batch": batch,
        "trial_dispositions": {t["id"]: "pending" for t in captured},
        "review": None,
        "proposal": None,
        "discard_identity": None,
    }
    records: dict[str, dict[str, Any]] = {"batch": batch}
    state = _commit_records(root, state, expected_revision, records)
    result = _result(
        "success",
        state,
        batch_identity=batch["identity"],
        conditions=conditions,
        trials=captured,
    )
    return result


def discard_workspace(workspace: str | Path) -> dict[str, Any]:
    """Researcher-only reset that preserves finalized artifacts and an audit tombstone."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    if state.get("phase") == "empty" and state.get("discard_identity"):
        tombstone = _read(root, f"discard:{state['discard_identity']}")
        if not isinstance(tombstone, dict):
            raise ValueError("discard tombstone is unavailable")
        _clear_discarded_derivatives(root)
        return _result("success", state, discard=tombstone, retry=True)
    if state.get("phase") == "empty":
        return _result(
            "condition",
            state,
            condition={
                "code": "no_active_batch",
                "detail": "discard requires an active or finalized Batch.",
            },
        )
    artifact = state.get("artifact") if isinstance(state.get("artifact"), dict) else None
    tombstone = {
        "kind": "discard_tombstone",
        "from_phase": state.get("phase"),
        "from_revision": state.get("revision", 0),
        "batch_identity": (state.get("batch") or {}).get("identity"),
        "artifact": artifact,
    }
    tombstone["identity"] = _identity(tombstone)
    empty = {
        "phase": "empty",
        "revision": state.get("revision", 0),
        "trial_dispositions": {},
        "discard_identity": tombstone["identity"],
    }
    committed = _commit_records(
        root,
        empty,
        state.get("revision", 0),
        {f"discard:{tombstone['identity']}": tombstone},
    )
    with _db(root, "canonical.sqlite3") as connection:
        connection.execute(
            "DELETE FROM records WHERE name NOT IN (?, ?)",
            ("state", f"discard:{tombstone['identity']}"),
        )
    _clear_discarded_derivatives(root)
    return _result("success", committed, discard=tombstone)


def _clear_discarded_derivatives(root: Path) -> None:
    sources = internal_path(root, "sources")
    if sources.exists():
        shutil.rmtree(sources)
    sources.mkdir(parents=True, exist_ok=True)
    with _db(root, "derivative.sqlite3") as connection:
        for table in (
            "source_index",
            "pages",
            "evidence_handles",
            "search_receipts",
            "renders",
            "page_reads",
        ):
            connection.execute(f"DELETE FROM {table}")
        connection.execute("DELETE FROM pages_fts")


@dataclass(frozen=True)
class ProposalApprovalContext:
    review: dict[str, Any] | None
    acknowledgment: dict[str, Any] | None


def proposal_approval_context(workspace: str | Path) -> ProposalApprovalContext:
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    review = state.get("review")
    acknowledgment = state.get("proposal_acknowledgment")
    return ProposalApprovalContext(
        review=review if isinstance(review, dict) and review.get("purpose") == "proposal" else None,
        acknowledgment=acknowledgment if isinstance(acknowledgment, dict) else None,
    )


def approve_review(
    workspace: str | Path,
    review_reference: str | None = None,
    *,
    caller: str = "cli",
    method: str = "cli",
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    review = state.get("review")
    if not isinstance(review, dict):
        prior_ack = state.get("proposal_acknowledgment")
        if isinstance(prior_ack, dict):
            acknowledgment = ReviewAcknowledgment.model_validate(prior_ack).model_dump(mode="json")
            if (
                review_reference is not None
                and review_reference != acknowledgment["review_identity"]
            ):
                raise ValueError("the exact displayed Review record must be acknowledged")
            return _result(
                "success",
                state,
                approved=True,
                retry=True,
                acknowledgment=acknowledgment["identity"],
                acknowledgment_record=acknowledgment,
                continuation=_continuation(state),
            )
        return _result("success", state, retry=True)
    if review.get("purpose") != "proposal":
        raise ValueError("only Proposal Review is researcher-authorized")
    if review_reference != review.get("identity"):
        raise ValueError("the exact displayed Review record must be acknowledged")
    acknowledgment = {
        "review_identity": review["identity"],
        "purpose": review["purpose"],
        "caller": caller,
        "method": method,
        "observed_at": datetime.now(UTC).isoformat(),
        "workflow_basis": review["workflow_basis"],
    }
    acknowledgment = ReviewAcknowledgment.model_validate(acknowledgment).model_dump(mode="json")
    if state.get("phase") == "proposal":
        disposition = dict(state.get("trial_dispositions", {}))
        terminals = dict(state.get("terminals", {}))
        terminal_records: dict[str, dict[str, Any]] = {}
        for result in state["proposal"]["payload"]["results"]:
            applicability = result.get("applicability")
            unsupported_design = (
                result.get("kind") == "assessable"
                and isinstance(applicability, dict)
                and applicability.get("status") in {"unsupported", "uncertain"}
            )
            if result.get("kind") == "unavailable" or unsupported_design:
                if unsupported_design:
                    rationale = str(applicability.get("rationale", "")).strip()
                    design = str(applicability.get("design", "unclear"))
                    status = str(applicability.get("status"))
                    reason = (
                        "The captured Trial design is unsupported by the installed "
                        f"parallel-assignment pack ({design})."
                        if status == "unsupported"
                        else "The captured Trial design could not be established for the installed "
                        f"parallel-assignment pack ({design})."
                    )
                    missing_facts = (
                        "A RoB 2 pack supporting the documented Trial design is required."
                        if status == "unsupported"
                        else (
                            "Source information establishing the Trial design and unit of "
                            "randomization is required."
                        ),
                    )
                    if rationale:
                        missing_facts = (f"Applicability rationale: {rationale}", *missing_facts)
                else:
                    reason = "The requested Result is not assessable from the captured Sources."
                    missing_facts = tuple(
                        item.get("fact", "") if isinstance(item, dict) else item
                        for item in result.get("missing_facts", [])
                    )
                terminal = {
                    "trial_id": result["trial_id"],
                    "disposition": "needs_input",
                    "reason": reason,
                    "missing_facts": list(missing_facts),
                }
                terminal["identity"] = _identity(terminal)
                terminals[terminal["identity"]] = terminal
                terminal_records[f"terminal:{terminal['identity']}"] = terminal
                disposition[result["trial_id"]] = "needs_input"
        phase = (
            "ready_to_finalize"
            if not any(value == "pending" for value in disposition.values())
            else "assessment"
        )
        state = {
            **state,
            "trial_dispositions": disposition,
            "phase": phase,
            "review": None,
            "proposal_review": review,
            "proposal_acknowledgment": acknowledgment,
            "terminals": terminals,
            "acknowledgments": [*state.get("acknowledgments", []), acknowledgment],
            "domain_index": {
                trial_id: [] for trial_id, value in disposition.items() if value == "pending"
            },
        }
        approval_revision = state.get("revision", 0)
        if isinstance(approval_revision, bool) or not isinstance(approval_revision, int):
            raise ValueError("workflow state revision is invalid")
        state = _commit_records(
            root,
            state,
            approval_revision,
            {f"acknowledgment:{acknowledgment['identity']}": acknowledgment, **terminal_records},
        )
    return _result(
        "success",
        state,
        approved=True,
        acknowledgment_record=acknowledgment,
        acknowledgment=acknowledgment["identity"],
        continuation=_continuation(state),
    )
