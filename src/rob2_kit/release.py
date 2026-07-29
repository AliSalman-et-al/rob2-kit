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
    guidance_pack: str


def build_host_adapters(root: Path, *, package_version: str) -> ReleaseManifest:
    canonical = root / "skills" / "rob2-assess" / "SKILL.md"
    skill_hash = _hash(canonical)
    launcher = f"uvx --python 3.13 --from rob2-kit=={package_version} rob2-mcp"
    for host in ("codex", "claude"):
        destination = root / "adapters" / host
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(canonical, destination / "SKILL.md")
        (destination / "launcher.txt").write_text(launcher + "\n", encoding="utf-8")
        (destination / "adapter.json").write_text(
            json.dumps(
                {
                    "host": host,
                    "skill": "rob2-assess",
                    "skill_hash": skill_hash,
                    "trigger_description": (
                        "Prepare an evidence-grounded RoB 2 assessment and hand it "
                        "to a human reviewer."
                    ),
                    "launcher": launcher,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (destination / "activation-fixtures.json").write_text(
            json.dumps(
                {
                    "activates": [
                        "Assess risk of bias with RoB 2",
                        "Resume this RoB 2 assessment",
                    ],
                    "does_not_activate": ["Perform the human sign-off"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
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
        guidance_pack="rob2-parallel-assignment-en-2019.1",
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
    if _hash(canonical) != manifest.canonical_skill_hash:
        raise ValueError("canonical skill hash diverges from release manifest")
    for host in ("codex", "claude"):
        if (root / "adapters" / host / "SKILL.md").read_bytes() != canonical.read_bytes():
            raise ValueError(f"{host} adapter diverges from canonical skill")
        if (root / "adapters" / host / "launcher.txt").read_text().strip() != manifest.launcher:
            raise ValueError(f"{host} launcher diverges from release manifest")
        descriptor = json.loads(
            (root / "adapters" / host / "adapter.json").read_text(encoding="utf-8")
        )
        if descriptor["skill_hash"] != manifest.canonical_skill_hash:
            raise ValueError(f"{host} descriptor has a divergent skill hash")
        if descriptor["launcher"] != manifest.launcher:
            raise ValueError(f"{host} descriptor has a divergent launcher")


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path.cwd()
    manifest = build_host_adapters(root, package_version="0.1.0")
    print(manifest.model_dump_json())
