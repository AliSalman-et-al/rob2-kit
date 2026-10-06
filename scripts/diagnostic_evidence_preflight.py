"""Private research-design coverage check before supplied-evidence diagnostic launch.

This checks explicit investigator-declared source windows, never semantic relevance.
The manifest is not model input and must not add answers or scientific production gates.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator


class SourceWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_identity: StrictStr = Field(min_length=1)
    page: StrictInt = Field(gt=0)
    start_line: StrictInt = Field(gt=0)
    end_line: StrictInt = Field(gt=0)


class SuppliedWindow(SourceWindow):
    input_start_byte: StrictInt = Field(ge=0)
    input_end_byte: StrictInt = Field(gt=0)
    text_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class ImageFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_identity: StrictStr = Field(min_length=1)
    page: StrictInt = Field(gt=0)
    png_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)


class SuppliedImageFrame(ImageFrame):
    input_start_byte: StrictInt = Field(ge=0)
    input_end_byte: StrictInt = Field(gt=0)


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    research_question: StrictStr = Field(min_length=1)
    input_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_bundle_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    required_windows: tuple[SourceWindow, ...] = ()
    supplied_windows: tuple[SuppliedWindow, ...] = ()
    required_images: tuple[ImageFrame, ...] = ()
    supplied_images: tuple[SuppliedImageFrame, ...] = ()

    @model_validator(mode="after")
    def require_evidence(self) -> EvidenceManifest:
        if not self.required_windows and not self.required_images:
            raise ValueError("diagnostic requires text windows or image frames")
        return self


def check_manifest(
    manifest_path: Path, input_path: Path, *, evidence_bundle_path: Path | None = None
) -> dict[str, Any]:
    """Check frozen prompt and evidence coverage, not model reading.

    Native diagnostics may keep complete tool-readable evidence in a separately
    hashed bundle rather than paste it into the generic prompt. The runner must
    verify that the corresponding frozen Sources remain available through MCP.
    """
    manifest_bytes = manifest_path.read_bytes()
    manifest = EvidenceManifest.model_validate_json(manifest_bytes)
    prompt = input_path.read_bytes()
    if hashlib.sha256(prompt).hexdigest() != manifest.input_sha256:
        raise ValueError("frozen diagnostic input hash mismatch")
    evidence = prompt
    if (evidence_bundle_path is None) != (manifest.evidence_bundle_sha256 is None):
        raise ValueError("separate evidence bundle requires both path and declared hash")
    if evidence_bundle_path is not None:
        evidence = evidence_bundle_path.read_bytes()
        if hashlib.sha256(evidence).hexdigest() != manifest.evidence_bundle_sha256:
            raise ValueError("frozen evidence bundle hash mismatch")
    for window in (*manifest.required_windows, *manifest.supplied_windows):
        if window.end_line < window.start_line:
            raise ValueError("invalid source line range")
    for supplied in manifest.supplied_windows:
        start, end = supplied.input_start_byte, supplied.input_end_byte
        if not start < end <= len(evidence):
            raise ValueError("supplied source bytes outside frozen input")
        if hashlib.sha256(evidence[start:end]).hexdigest() != supplied.text_sha256:
            raise ValueError("supplied passage hash mismatch")
    for required in manifest.required_windows:
        spans = sorted(
            (s.start_line, s.end_line)
            for s in manifest.supplied_windows
            if s.source_identity == required.source_identity and s.page == required.page
        )
        cursor = required.start_line
        for start, end in spans:
            if start > cursor:
                break
            if end >= cursor:
                cursor = end + 1
        if cursor <= required.end_line:
            raise ValueError(
                f"required diagnostic evidence omitted: {required.source_identity} "
                f"page {required.page} lines {required.start_line}-{required.end_line}"
            )
    for supplied in manifest.supplied_images:
        start, end = supplied.input_start_byte, supplied.input_end_byte
        if not start < end <= len(evidence):
            raise ValueError("supplied image bytes outside frozen input")
        png = evidence[start:end]
        if hashlib.sha256(png).hexdigest() != supplied.png_sha256:
            raise ValueError("supplied image hash mismatch")
        if (
            png[:8] != b"\x89PNG\r\n\x1a\n"
            or png[12:16] != b"IHDR"
            or (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big"))
            != (supplied.width, supplied.height)
        ):
            raise ValueError("supplied image is not the declared PNG frame")
    for required in manifest.required_images:
        if not any(
            all(getattr(supplied, key) == value for key, value in required.model_dump().items())
            for supplied in manifest.supplied_images
        ):
            raise ValueError("required diagnostic image omitted")
    return {
        "passed": True,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "input_sha256": manifest.input_sha256,
        "evidence_bundle_sha256": manifest.evidence_bundle_sha256,
        "required_window_count": len(manifest.required_windows),
        "supplied_window_count": len(manifest.supplied_windows),
        "required_image_count": len(manifest.required_images),
        "supplied_image_count": len(manifest.supplied_images),
        "scope": "declared research-design coverage only; no semantic sufficiency claim",
    }


def launch_checked(
    command: list[str],
    *,
    manifest_path: Path,
    input_path: Path,
    receipt_path: Path,
    expected_manifest_sha256: str,
    evidence_bundle_path: Path | None = None,
    **popen_options: Any,
) -> subprocess.Popen:
    """The only launch point: check frozen coverage before creating the child process.

    A diagnostic runner still owns authorization, model/tool settings and usage guards.
    Manifest declarations require independent research-design review; this function
    cannot discover an omitted requirement or verify that a quotation supports a claim.
    """
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != expected_manifest_sha256:
        raise ValueError("preregistered evidence manifest hash mismatch")
    receipt = check_manifest(manifest_path, input_path, evidence_bundle_path=evidence_bundle_path)
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return subprocess.Popen(command, **popen_options)


def check_instruction_delivery(
    instructions_path: Path, required_documents: tuple[Path, ...]
) -> dict[str, Any]:
    """Verify explicit required documents are in the actual model instruction file.

    A local skill/reference file is not accessible merely because it exists.
    Tools-only native diagnostics must deliver needed reference content through
    their instruction file or another verified model-visible channel. This
    check covers caller-declared requirements, not a complete dependency graph.
    """
    content = instructions_path.read_bytes()
    if not required_documents:
        raise ValueError("instruction check requires explicit documents")
    documents = []
    for path in required_documents:
        body = path.read_bytes()
        if not body or body not in content:
            raise ValueError(f"required instruction document not delivered: {path.name}")
        documents.append({"name": path.name, "sha256": hashlib.sha256(body).hexdigest()})
    return {
        "passed": True,
        "instructions_sha256": hashlib.sha256(content).hexdigest(),
        "required_documents": documents,
        "scope": "explicit instruction delivery; no complete dependency or comprehension claim",
    }
