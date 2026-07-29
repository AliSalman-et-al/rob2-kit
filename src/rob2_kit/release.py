"""Generate and verify cross-host skill adapters."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from rob2_kit.application.gateway import CONTRACT_VERSION


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    package: str
    package_version: str
    canonical_skill_hash: str
    application_contract: str
    launcher: str
    codex_adapter_version: str
    claude_adapter_version: str
    logic_pack: str
    logic_pack_hash: str
    guidance_pack: str
    guidance_pack_hash: str


def build_host_adapters(root: Path, *, package_version: str) -> ReleaseManifest:
    canonical = root / "skills" / "rob2-assess" / "SKILL.md"
    activation_fixtures = (
        root / "skills" / "rob2-assess" / "activation-fixtures.json"
    )
    skill_hash = _hash(canonical)
    launcher = f"uvx --python 3.13 --from rob2-kit=={package_version} rob2-mcp"
    for host in ("codex", "claude"):
        descriptor = _descriptor(host, skill_hash, launcher)
        destination = root / "adapters" / host
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(canonical, destination / "SKILL.md")
        (destination / "launcher.txt").write_text(launcher + "\n", encoding="utf-8")
        (destination / "adapter.json").write_text(
            json.dumps(descriptor, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        shutil.copyfile(
            activation_fixtures,
            destination / "activation-fixtures.json",
        )
    manifest = ReleaseManifest(
        package="rob2-kit",
        package_version=package_version,
        canonical_skill_hash=skill_hash,
        application_contract=CONTRACT_VERSION,
        launcher=launcher,
        codex_adapter_version="1",
        claude_adapter_version="1",
        logic_pack="rob2-parallel-assignment-2019.1",
        logic_pack_hash=_hash(
            root / "packs" / "logic" / "rob2-parallel-assignment-2019.1.yaml"
        ),
        guidance_pack="rob2-parallel-assignment-en-2019.1",
        guidance_pack_hash=_hash(
            root
            / "packs"
            / "guidance"
            / "rob2-parallel-assignment-en-2019.1.yaml"
        ),
    )
    (root / "adapters" / "release-manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_host_adapters(root: Path) -> None:
    manifest = ReleaseManifest.model_validate_json(
        (root / "adapters" / "release-manifest.json").read_text(encoding="utf-8")
    )
    canonical = root / "skills" / "rob2-assess" / "SKILL.md"
    activation_fixtures = (
        root / "skills" / "rob2-assess" / "activation-fixtures.json"
    )
    if _hash(canonical) != manifest.canonical_skill_hash:
        raise ValueError("canonical skill hash diverges from release manifest")
    pack_paths = {
        manifest.logic_pack_hash: (
            root / "packs" / "logic" / f"{manifest.logic_pack}.yaml"
        ),
        manifest.guidance_pack_hash: (
            root / "packs" / "guidance" / f"{manifest.guidance_pack}.yaml"
        ),
    }
    if any(_hash(path) != expected for expected, path in pack_paths.items()):
        raise ValueError("pinned pack hash diverges from release manifest")
    for host in ("codex", "claude"):
        if (root / "adapters" / host / "SKILL.md").read_bytes() != canonical.read_bytes():
            raise ValueError(f"{host} adapter diverges from canonical skill")
        if (root / "adapters" / host / "launcher.txt").read_text().strip() != manifest.launcher:
            raise ValueError(f"{host} launcher diverges from release manifest")
        descriptor = json.loads(
            (root / "adapters" / host / "adapter.json").read_text(encoding="utf-8")
        )
        if descriptor != _descriptor(
            host, manifest.canonical_skill_hash, manifest.launcher
        ):
            raise ValueError(f"{host} descriptor diverges from its generation template")
        if descriptor["adapter_version"] != getattr(
            manifest, f"{host}_adapter_version"
        ):
            raise ValueError(f"{host} adapter version diverges from release manifest")
        if (
            root / "adapters" / host / "activation-fixtures.json"
        ).read_bytes() != activation_fixtures.read_bytes():
            raise ValueError(f"{host} activation fixtures diverge from canonical fixtures")


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _descriptor(host: str, skill_hash: str, launcher: str) -> dict[str, str]:
    template_path = Path(__file__).with_name("templates") / f"{host}-adapter.json"
    descriptor = json.loads(template_path.read_text(encoding="utf-8"))
    descriptor.update(
        {
            "skill_hash": skill_hash,
            "trigger_description": (
                "Prepare an evidence-grounded RoB 2 assessment and hand it "
                "to a human reviewer."
            ),
            "launcher": launcher,
        }
    )
    return descriptor


def main() -> None:
    root = Path.cwd()
    manifest = build_host_adapters(root, package_version="0.1.0")
    print(manifest.model_dump_json())
