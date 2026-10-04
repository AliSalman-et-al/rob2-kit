"""Stage one cited public PDF in a fresh prospective dossier, never an active Batch."""

import hashlib
import ipaddress
import json
import re
import shutil
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from ._state import _manifest, _state
from .evidence import _find_source, read_pages
from .intake import _trial_directory

# Exact, provider-controlled hosts. Expanding this list requires access-policy review;
# caller-owned public hosts are deliberately outside this bounded acquisition path.
PUBLIC_DOCUMENT_HOSTS = frozenset(
    {
        "cdn.clinicaltrials.gov",
        "journals.plos.org",
        "pmc.ncbi.nlm.nih.gov",
    }
)
MAX_BYTES = 20 * 1024 * 1024


class CompanionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    trial_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    page: int = Field(ge=1)
    citation: str = Field(min_length=1)
    linkage_rationale: str = Field(min_length=1)
    requested_role: str = Field(pattern=r"^(protocol|sap)$")
    locator_kind: str = Field(pattern=r"^(url|doi)$")
    locator: str = Field(min_length=1)
    registry_id: str | None = Field(default=None, pattern=r"^NCT\d{8}$")


def _validate_url(url: str, hosts: frozenset[str]) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("unsupported_or_forbidden_public_url")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("nonpublic_destination")


def _fetch(
    client: httpx.Client, url: str, hosts: frozenset[str], limit: int, chain: list[str]
) -> bytes:
    for _ in range(4):
        _validate_url(url, hosts)
        client.cookies.clear()
        chain.append(url)
        with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise ValueError("redirect_without_destination")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").casefold() != "identity":
                raise ValueError("unsupported_content_encoding")
            chunks = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise ValueError("document_size_limit")
            return bytes(chunks)
    raise ValueError("redirect_limit")


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
                raw = _fetch(
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
            content = _fetch(
                client, url, PUBLIC_DOCUMENT_HOSTS, MAX_BYTES, report["redirect_chain"]
            )
        if not content.startswith(b"%PDF-"):
            raise ValueError("not_pdf_content")
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            if pdf.is_encrypted or not pdf.page_count:
                raise ValueError("encrypted_or_empty_pdf")
            ids = sorted(
                set(re.findall(r"\bNCT\d{8}\b", "\n".join(page.get_text() for page in pdf)))
            )
            report["page_count"] = pdf.page_count
            report["pdf_metadata"] = pdf.metadata
        relation = "unverified"
        if reference.registry_id and ids:
            relation = (
                "registry_identifier_observed"
                if ids == [reference.registry_id]
                else "conflicting_or_multiple_registry_identifiers"
            )
        report.update(
            retrieved_at=datetime.now(UTC).isoformat(),
            status="captured",
            trial_relation=relation,
            observed_registry_ids=ids,
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


def stage_companion(
    workspace: str | Path, destination: str | Path, reference: CompanionReference
) -> dict:
    """Copy input only into a fresh workspace; require new intake and human review."""
    if reference.locator_kind == "url":
        parsed = urlsplit(reference.locator)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credential URLs are forbidden")
    root = Path(workspace).resolve()
    target = Path(destination).resolve()
    if target.exists() or target.is_symlink() or target == root or root in target.parents:
        raise ValueError("destination must be a fresh workspace outside the original")
    source = _find_source(root, reference.trial_id, reference.source_id)
    page = read_pages(root, reference.trial_id, reference.source_id, [reference.page])["pages"][0]
    if reference.citation not in page["text"]:
        raise ValueError("citation must occur in the supplied Source page text")
    locator_found = reference.locator in reference.citation
    if (
        reference.locator_kind == "url"
        and source["role"] == "registry"
        and urlsplit(reference.locator).hostname == "cdn.clinicaltrials.gov"
    ):
        filename = Path(urlsplit(reference.locator).path).name
        nct = reference.registry_id
        locator_found = bool(
            nct
            and re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", filename)
            and reference.locator
            == (f"https://cdn.clinicaltrials.gov/large-docs/{nct[-2:]}/{nct}/{filename}")
            and filename in reference.citation
        )
    if not locator_found:
        raise ValueError("locator must be explicitly present in the cited reference")
    trials = _state(root).get("batch", {}).get("trials", [])
    trial = next((t for t in trials if t["id"] == reference.trial_id), None)
    if trial is None:
        raise ValueError("unknown captured Trial")
    directory = _trial_directory(root, trial["label"])
    # Never follow caller-controlled links while copying an evidence dossier.
    if (root / "input").is_symlink() or any(p.is_symlink() for p in (root / "input").rglob("*")):
        raise ValueError("input symlinks are unsupported for prospective staging")
    config = _manifest(directory)
    if "sources" in config and not isinstance(config["sources"], list):
        raise ValueError("sources manifest must use an array for prospective staging")
    content, report = _acquire(reference)
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
    version = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:16]
    shutil.copytree(root / "input", target / "input")
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
