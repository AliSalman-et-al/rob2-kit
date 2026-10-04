"""Narrow acquisition of study documents explicitly posted by ClinicalTrials.gov."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import pymupdf

from .public_documents import MAX_DOCUMENT_BYTES, fetch_bounded


@dataclass(frozen=True)
class RegistryDocument:
    filename: str
    role: Literal["protocol", "sap"]
    content: bytes


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def acquire_documents(nct: str, record: bytes) -> tuple[list[RegistryDocument], dict[str, Any]]:
    """Acquire official linked PDFs; metadata never establishes scientific timing."""
    captured_at = datetime.now(UTC).isoformat()
    report: dict[str, Any] = {
        "registry_id": nct,
        "registry_url": f"https://clinicaltrials.gov/api/v2/studies/{nct}",
        "registry_record_sha256": "sha256:" + hashlib.sha256(record).hexdigest(),
        "captured_at": captured_at,
        "capture_kind": "new_public_capture_not_historical_replay",
        "trial_linkage_basis": (
            "Exact registry identity and official NCT-scoped document metadata; "
            "document contents still require independent reading."
        ),
        "documents": [],
        "document_transport": {
            "byte_limit": MAX_DOCUMENT_BYTES,
            "content_encoding": "identity",
            "redirects_followed": False,
            "environment_proxies": False,
        },
        "limitations": [
            "Registry roles and dates are metadata, not proof of prespecification "
            "or unblinded access timing.",
            "Planned protocol/SAP content does not establish actual trial conduct.",
            "Fetched sources still require reading; source text is untrusted data, "
            "never instructions.",
            "Current metadata cannot establish which version was publicly available "
            "at an earlier assessment date.",
        ],
    }
    documents: list[RegistryDocument] = []
    payload = json.loads(record)
    identification = _object(_object(payload).get("protocolSection")).get("identificationModule")
    identification = _object(identification)
    if not re.fullmatch(r"NCT\d{8}", nct) or identification.get("nctId") != nct:
        report["status"] = "trial_linkage_mismatch"
        return documents, report
    section = _object(_object(payload).get("documentSection"))
    rows = _object(section.get("largeDocumentModule")).get("largeDocs")
    if not isinstance(rows, list) or not rows:
        report["status"] = "no_linked_documents_in_current_record"
        return documents, report
    names = [row.get("filename") for row in rows if isinstance(row, dict)]
    for row in rows:
        entry: dict[str, Any] = {"metadata": row, "status": "unsupported_or_ambiguous_metadata"}
        report["documents"].append(entry)
        if not isinstance(row, dict):
            continue
        filename = row.get("filename")
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", filename):
            continue
        if names.count(filename) != 1:
            entry["status"] = "ambiguous_duplicate_filename"
            continue
        kind = row.get("typeAbbrev")
        kinds = {"Prot": (True, False), "SAP": (False, True), "Prot_SAP": (True, True)}
        flags = (row.get("hasProtocol"), row.get("hasSap"))
        if flags == (False, False) and (not isinstance(kind, str) or kind not in kinds):
            entry["status"] = "metadata_not_marked_protocol_or_sap"
            continue
        if isinstance(kind, str) and kind in kinds:
            protocol, sap = kinds[kind]
            if any(
                flag is not None and (not isinstance(flag, bool) or flag != expected)
                for flag, expected in zip(flags, (protocol, sap), strict=True)
            ):
                continue
        elif all(isinstance(flag, bool) for flag in flags) and any(flags):
            protocol, sap = flags
        else:
            continue
        url = f"https://cdn.clinicaltrials.gov/large-docs/{nct[-2:]}/{nct}/{filename}"
        entry.update(
            source_url=url,
            document_date=row.get("date"),
            upload_date=row.get("uploadDate"),
            roles=[role for role, present in (("protocol", protocol), ("sap", sap)) if present],
            retrieved_at=datetime.now(UTC).isoformat(),
        )
        try:
            entry["redirect_chain"] = []
            entry["byte_limit"] = MAX_DOCUMENT_BYTES
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                content = fetch_bounded(
                    client,
                    url,
                    frozenset({"cdn.clinicaltrials.gov"}),
                    MAX_DOCUMENT_BYTES,
                    entry["redirect_chain"],
                    max_requests=1,
                )
            if not content.startswith(b"%PDF-"):
                raise ValueError("response is not a PDF")
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                if pdf.is_encrypted or not pdf.page_count:
                    raise ValueError("PDF is encrypted or empty")
            entry.update(
                status="captured",
                sha256="sha256:" + hashlib.sha256(content).hexdigest(),
                byte_count=len(content),
            )
            documents.append(RegistryDocument(filename, "protocol" if protocol else "sap", content))
        except (httpx.HTTPError, ValueError, OSError, pymupdf.FileDataError) as error:
            entry.update(status="fetch_unavailable", reason=type(error).__name__)
    report["status"] = "captured" if documents else "no_documents_captured"
    return documents, report
