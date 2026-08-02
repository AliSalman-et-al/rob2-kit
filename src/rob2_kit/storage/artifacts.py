"""Exact-byte, content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from rob2_kit.domain.revisions import ContentHash


class ArtifactStoreError(RuntimeError):
    """Base class for artifact-store failures."""


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when an artifact is absent."""


class ArtifactCorruptionError(ArtifactStoreError):
    """Raised when stored bytes no longer match their address."""


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_hash: ContentHash
    size: int
    media_type: str
    path: Path


class ArtifactStore:
    """Store immutable bytes under their SHA-256 digest."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, media_type: str) -> Artifact:
        if media_type == "application/json":
            try:
                parsed = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("JSON artifacts must contain valid UTF-8 JSON") from error
            content = json.dumps(
                parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        content_hash = _content_hash(content)
        path = self.path_for(content_hash)
        if path.exists():
            existing = path.read_bytes()
            if _content_hash(existing) != content_hash:
                raise ArtifactCorruptionError(f"artifact {content_hash} is corrupted")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return Artifact(
            content_hash=content_hash,
            size=len(content),
            media_type=media_type,
            path=path,
        )

    def read(self, content_hash: str) -> bytes:
        path = self.path_for(content_hash)
        try:
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactNotFoundError(f"artifact {content_hash} was not found") from error
        if _content_hash(content) != content_hash:
            raise ArtifactCorruptionError(f"artifact {content_hash} is corrupted")
        return content

    def path_for(self, content_hash: str) -> Path:
        algorithm, separator, digest = content_hash.partition(":")
        if algorithm != "sha256" or not separator or len(digest) != 64:
            raise ValueError("content hash must be a sha256 digest")
        return self.root / digest[:2] / digest[2:]


def _content_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
