"""Freeze native diagnostic projections without inventing text for unreadable pages.

This is operator preparation, not model delivery or semantic comprehension.
Pages without extracted text retain a genuine source-bound PNG and render action.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.application._state import _state
from rob2_kit.application.evidence import _find_source, _render_page_png
from rob2_kit.application.source_handles import source_handle
from scripts.diagnostic_evidence_preflight import SuppliedImageFrame, SuppliedWindow


class RenderRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: Literal["render_page"] = "render_page"
    trial_id: str
    source_id: str = Field(pattern=r"^sh_[0-9a-f]{16}$")
    page: int = Field(gt=0)


class EmptyTextPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_identity: str
    page: int = Field(gt=0)
    text_state: Literal["empty_text_projection"] = "empty_text_projection"
    text_sha256: str
    visual_interpretation: Literal["not_asserted"] = "not_asserted"
    recovery: RenderRecovery


@dataclass(frozen=True)
class FrozenNativeEvidence:
    bundle: bytes
    windows: tuple[SuppliedWindow, ...]
    images: tuple[SuppliedImageFrame, ...]
    empty_text_pages: tuple[EmptyTextPage, ...]


def freeze_native_evidence(workspace: Path, trial_id: str) -> FrozenNativeEvidence:
    """Verify captured identities and freeze actual text or pixel coverage.

    No reading/delivery receipt, selected Evidence, or workflow state is written.
    A whitespace-only projection does not establish a physically blank page.
    """
    workspace = workspace.resolve()
    state = _state(workspace)
    trial = next(item for item in state["batch"]["trials"] if item["id"] == trial_id)
    bundle = bytearray()
    windows: list[SuppliedWindow] = []
    images: list[SuppliedImageFrame] = []
    empty: list[EmptyTextPage] = []
    database = workspace / ".rob2-kit" / "derivative.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        for source in trial["sources"]:
            verified = _find_source(workspace, trial_id, source["id"])
            identity = source["id"] + "@" + verified["sha256"]
            for page, text in connection.execute(
                "SELECT page,text FROM pages WHERE source_id=? ORDER BY page", (source["id"],)
            ):
                start = len(bundle)
                if text.strip():
                    body = text.encode()
                    bundle.extend(body)
                    windows.append(
                        SuppliedWindow(
                            source_identity=identity,
                            page=page,
                            start_line=1,
                            end_line=len(text.splitlines()),
                            input_start_byte=start,
                            input_end_byte=len(bundle),
                            text_sha256=hashlib.sha256(body).hexdigest(),
                        )
                    )
                else:
                    if verified["media_type"] != "application/pdf":
                        raise ValueError(
                            "empty text projection has no supported PDF render recovery"
                        )
                    png = _render_page_png(workspace, trial_id, source["id"], page, count=False)
                    bundle.extend(png)
                    images.append(
                        SuppliedImageFrame(
                            source_identity=identity,
                            page=page,
                            png_sha256=hashlib.sha256(png).hexdigest(),
                            width=int.from_bytes(png[16:20], "big"),
                            height=int.from_bytes(png[20:24], "big"),
                            input_start_byte=start,
                            input_end_byte=len(bundle),
                        )
                    )
                    empty.append(
                        EmptyTextPage(
                            source_identity=identity,
                            page=page,
                            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                            recovery=RenderRecovery(
                                trial_id=trial_id, source_id=source_handle(source["id"]), page=page
                            ),
                        )
                    )
                bundle.extend(b"\n")
    return FrozenNativeEvidence(bytes(bundle), tuple(windows), tuple(images), tuple(empty))
