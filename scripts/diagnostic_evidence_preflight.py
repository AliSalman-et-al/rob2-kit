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

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


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


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    research_question: StrictStr = Field(min_length=1)
    input_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    required_windows: tuple[SourceWindow, ...] = Field(min_length=1)
    supplied_windows: tuple[SuppliedWindow, ...] = Field(min_length=1)


def check_manifest(manifest_path: Path, input_path: Path) -> dict[str, Any]:
    """Fail closed for omitted required ranges or changed frozen input/manifest data."""
    manifest_bytes = manifest_path.read_bytes()
    manifest = EvidenceManifest.model_validate_json(manifest_bytes)
    prompt = input_path.read_bytes()
    if hashlib.sha256(prompt).hexdigest() != manifest.input_sha256:
        raise ValueError("frozen diagnostic input hash mismatch")
    for window in (*manifest.required_windows, *manifest.supplied_windows):
        if window.end_line < window.start_line:
            raise ValueError("invalid source line range")
    for supplied in manifest.supplied_windows:
        start, end = supplied.input_start_byte, supplied.input_end_byte
        if not start < end <= len(prompt):
            raise ValueError("supplied source bytes outside frozen input")
        if hashlib.sha256(prompt[start:end]).hexdigest() != supplied.text_sha256:
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
    return {
        "passed": True,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "input_sha256": manifest.input_sha256,
        "required_window_count": len(manifest.required_windows),
        "supplied_window_count": len(manifest.supplied_windows),
        "scope": "declared research-design coverage only; no semantic sufficiency claim",
    }


def launch_checked(
    command: list[str],
    *,
    manifest_path: Path,
    input_path: Path,
    receipt_path: Path,
    expected_manifest_sha256: str,
    **popen_options: Any,
) -> subprocess.Popen:
    """The only launch point: check frozen coverage before creating the child process.

    A diagnostic runner still owns authorization, model/tool settings and usage guards.
    Manifest declarations require independent research-design review; this function
    cannot discover an omitted requirement or verify that a quotation supports a claim.
    """
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != expected_manifest_sha256:
        raise ValueError("preregistered evidence manifest hash mismatch")
    receipt = check_manifest(manifest_path, input_path)
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return subprocess.Popen(command, **popen_options)
