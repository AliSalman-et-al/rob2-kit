"""Manifest-backed public synthetic Trial dossier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from rob2_kit.domain.revisions import FrozenModel


class DossierSource(FrozenModel):
    source_id: str = Field(pattern=r"^source:[a-z0-9-]+$")
    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)
    content: str = ""


class DossierOverlay(FrozenModel):
    overlay_id: str = Field(pattern=r"^[a-z0-9-]+$")
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)
    changes: tuple[str, ...] = ()


class Prompt(FrozenModel):
    prompt_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    text: str = Field(min_length=1)
    negative: bool = False


class PublicDossier(FrozenModel):
    schema_version: int = 1
    dossier_id: str = Field(pattern=r"^dossier:[a-z0-9-]+$")
    trial_id: str = Field(pattern=r"^trial:[a-z0-9-]+$")
    trial_name: str = Field(min_length=1)
    sources: tuple[DossierSource, ...]
    domains: dict[str, tuple[str, ...]]
    overlays: dict[str, DossierOverlay]
    prompt_families: dict[str, tuple[str, ...]]
    prompts: tuple[Prompt, ...]

    @field_validator("sources")
    @classmethod
    def require_result_bearing_sources(
        cls, value: tuple[DossierSource, ...]
    ) -> tuple[DossierSource, ...]:
        roles = {source.role for source in value}
        required = {"full_text", "protocol", "sap", "supplement", "registry", "evidence"}
        missing = required - roles
        if missing:
            raise ValueError(
                f"public dossier is missing source roles: {', '.join(sorted(missing))}"
            )
        return value

    @field_validator("domains")
    @classmethod
    def require_all_domains(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        required = {"randomization", "deviations", "missing", "measurement", "selection"}
        missing = required - set(value)
        if missing:
            raise ValueError(f"public dossier is missing Domains: {', '.join(sorted(missing))}")
        if any(not evidence for evidence in value.values()):
            raise ValueError("every Domain must include at least one evidence reference")
        return value


def load_public_dossier(root: Path | None = None) -> PublicDossier:
    """Load and validate the distributable synthetic dossier.

    ``root`` is the repository root in tests.  Source paths are retained as
    fixture-relative paths while their UTF-8 content is loaded for replay.
    """

    repository = (root or Path(__file__).resolve().parents[3]).resolve()
    fixture_root = (repository / "tests" / "public_fixtures" / "dossier").resolve()
    manifest_path = fixture_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load public dossier manifest: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError("public dossier manifest must be a JSON object")

    sources: list[dict[str, Any]] = []
    for item in _entries(manifest, "sources"):
        source = _required_object(item, "source")
        path = _safe_fixture_path(fixture_root, source.get("path"), "source")
        sources.append({**source, "content": _read_public_content(path)})

    overlays: dict[str, DossierOverlay] = {}
    for item in _entries(manifest, "overlays"):
        overlay = DossierOverlay.model_validate(item)
        _safe_fixture_path(fixture_root, overlay.path, "overlay")
        overlays[overlay.overlay_id] = overlay

    prompt_families: dict[str, tuple[str, ...]] = {}
    prompts: list[Prompt] = []
    for family in _entries(manifest, "prompt_families"):
        family_id = _required_string(family, "family_id")
        texts = tuple(_prompt_text(item) for item in family.get("prompts", []))
        if not texts:
            raise ValueError(f"prompt family {family_id!r} has no prompts")
        prompt_families[family_id] = texts
        prompts.extend(
            Prompt(
                prompt_id=f"prompt:{family_id}-{index}",
                family=family_id,
                text=text,
                negative=bool(family.get("negative", False)),
            )
            for index, text in enumerate(texts, start=1)
        )

    raw = {
        **manifest,
        "sources": sources,
        "overlays": overlays,
        "prompt_families": prompt_families,
        "prompts": prompts,
    }
    raw.pop("overlay_index", None)
    raw.pop("prompt_families_manifest", None)
    return PublicDossier.model_validate(raw)


def _entries(manifest: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = manifest.get(key)
    if not isinstance(value, list):
        raise ValueError(f"public dossier {key} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"public dossier {key} entries must be objects")
    return value


def _required_object(item: dict[str, Any], label: str) -> dict[str, Any]:
    if not item:
        raise ValueError(f"{label} entry must not be empty")
    return item


def _required_string(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"dossier entry requires a non-empty {key!r}")
    return value


def _prompt_text(item: Any) -> str:
    if isinstance(item, str) and item.strip():
        return item
    if isinstance(item, dict):
        return _required_string(item, "text")
    raise ValueError("prompt entries must be non-empty strings or objects with text")


def _safe_fixture_path(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError(f"{label} path must be non-empty")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{label} path escapes public fixture root")
    if not path.is_file():
        raise ValueError(f"{label} fixture is missing: {relative}")
    return path


def _read_public_content(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"<binary fixture: {path.name}>"
