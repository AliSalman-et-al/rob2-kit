"""Build and verify the frozen lean-v1 release contract."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO, cast

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.application.contracts import CONTRACT_VERSION, RUN_OPERATION_NAMES

CANONICAL_SKILL_NAMES = ("rob2-init", "rob2-assess")
SUPPORTED_HOSTS = ("codex", "claude")
LOCK_FILENAME = "rob2.lock"
RELEASE_MANIFEST_FILENAME = "release-manifest.json"
ADAPTER_VERSION = "1"
PYTHON_VERSION = "3.13"


class SkillPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    activation_fixtures_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class AdapterPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    skill_hashes: dict[str, str]


@dataclass(frozen=True)
class CanonicalSkillAssets:
    skill: Path
    fixtures: Path


class ReleaseLock(BaseModel):
    """The exact release and content contract shared by both Harnesses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    package: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    python_version: Literal["3.13"]
    release_status: Literal["draft_only_preview"]
    application_contract: str = Field(min_length=1)
    launcher: str = Field(min_length=1)
    launcher_working_directory: Literal["project_root"]
    dependency_lock_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    skills: dict[str, SkillPin]
    adapters: dict[str, AdapterPin]
    logic_pack: str = Field(min_length=1)
    logic_pack_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    guidance_pack: str = Field(min_length=1)
    guidance_pack_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def build_host_adapters(root: Path, *, package_version: str) -> ReleaseLock:
    """Generate both host adapter trees and write the authoritative release lock."""

    root = root.resolve()
    canonical_skills = _canonical_skill_assets(root)
    launcher = _launcher(package_version)
    skill_pins = _skill_pins(canonical_skills)
    adapters: dict[str, AdapterPin] = {}

    for host in SUPPORTED_HOSTS:
        destination = root / "adapters" / host
        _prepare_adapter_destination(destination)
        generated_skills = destination / "skills"
        for skill_name, paths in canonical_skills.items():
            generated_skill = generated_skills / skill_name
            generated_skill.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(paths.skill, generated_skill / "SKILL.md")
            shutil.copyfile(
                paths.fixtures,
                generated_skill / "activation-fixtures.json",
            )

        descriptor = _descriptor(
            host,
            package_version=package_version,
            launcher=launcher,
            skill_pins=skill_pins,
        )
        (destination / "adapter.json").write_text(
            json.dumps(descriptor, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (destination / "launcher.txt").write_text(launcher + "\n", encoding="utf-8")
        adapters[host] = AdapterPin(
            version=ADAPTER_VERSION,
            content_hash=_tree_hash(destination),
            skill_hashes={
                skill_name: pin.content_hash for skill_name, pin in skill_pins.items()
            },
        )

    manifest = ReleaseLock(
        version=1,
        package="rob2-kit",
        package_version=package_version,
        python_version=PYTHON_VERSION,
        release_status="draft_only_preview",
        application_contract=CONTRACT_VERSION,
        launcher=launcher,
        launcher_working_directory="project_root",
        dependency_lock_hash=_dependency_lock_hash(root),
        skills=skill_pins,
        adapters=adapters,
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
    _write_json(root / LOCK_FILENAME, manifest.model_dump(mode="json", exclude_none=True))
    _write_json(
        root / "adapters" / RELEASE_MANIFEST_FILENAME,
        manifest.model_dump(mode="json", exclude_none=True),
    )
    return manifest


def load_release_lock(root: Path) -> ReleaseLock:
    """Load the release lock and reject malformed or legacy single-skill locks."""

    root = root.resolve()
    lock_path = root / LOCK_FILENAME
    try:
        manifest = ReleaseLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot load release lock {lock_path}: {error}") from error
    _validate_lock_shape(manifest)
    return manifest


def verify_host_adapters(root: Path) -> None:
    """Verify canonical skills, generated adapter trees, packs, and lock hashes."""

    root = root.resolve()
    manifest = load_release_lock(root)
    canonical_skills = _canonical_skill_assets(root)
    skill_pins = _skill_pins(canonical_skills)
    if skill_pins != manifest.skills:
        raise ValueError("canonical skill hashes diverge from release lock")

    dependency_lock = root / "uv.lock"
    if _hash(dependency_lock) != manifest.dependency_lock_hash:
        raise ValueError("frozen dependency lock diverges from release lock")

    pack_paths = {
        manifest.logic_pack_hash: root / "packs" / "logic" / f"{manifest.logic_pack}.yaml",
        manifest.guidance_pack_hash: (
            root / "packs" / "guidance" / f"{manifest.guidance_pack}.yaml"
        ),
    }
    if any(_hash(path) != expected for expected, path in pack_paths.items()):
        raise ValueError("pinned pack hash diverges from release lock")

    for host in SUPPORTED_HOSTS:
        adapter_pin = manifest.adapters.get(host)
        if adapter_pin is None:
            raise ValueError(f"release lock is missing {host} adapter")
        if adapter_pin.version != ADAPTER_VERSION:
            raise ValueError(f"{host} adapter version diverges from release contract")
        destination = root / "adapters" / host
        if any(
            (destination / legacy).exists()
            for legacy in ("SKILL.md", "activation-fixtures.json")
        ):
            raise ValueError(f"{host} adapter retains a legacy single-skill layout")
        adapter_assets = {path.name for path in destination.iterdir()}
        if adapter_assets != {"adapter.json", "launcher.txt", "skills"}:
            raise ValueError(f"{host} adapter has unexpected assets")

        generated_skills = destination / "skills"
        actual_skill_names = {path.name for path in generated_skills.iterdir()}
        if actual_skill_names != set(CANONICAL_SKILL_NAMES):
            raise ValueError(f"{host} adapter skills are not exactly the canonical skills")
        for skill_name, paths in canonical_skills.items():
            generated_skill = generated_skills / skill_name
            actual_files = {path.name for path in generated_skill.iterdir()}
            if actual_files != {"SKILL.md", "activation-fixtures.json"}:
                raise ValueError(f"{host} adapter skill {skill_name} has unexpected assets")
            if (generated_skill / "SKILL.md").read_bytes() != paths.skill.read_bytes():
                raise ValueError(f"{host} adapter skill {skill_name} diverges from canonical")
            if (
                (generated_skill / "activation-fixtures.json").read_bytes()
                != paths.fixtures.read_bytes()
            ):
                raise ValueError(
                    f"{host} adapter fixtures for {skill_name} diverge from canonical"
                )

        expected_descriptor = _descriptor(
            host,
            package_version=manifest.package_version,
            launcher=manifest.launcher,
            skill_pins=manifest.skills,
        )
        try:
            descriptor = json.loads(
                (destination / "adapter.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read {host} adapter descriptor: {error}") from error
        if descriptor != expected_descriptor:
            raise ValueError(f"{host} adapter descriptor diverges from generation template")
        if (destination / "launcher.txt").read_text(encoding="utf-8").strip() != manifest.launcher:
            raise ValueError(f"{host} launcher diverges from release lock")
        if _tree_hash(destination) != adapter_pin.content_hash:
            raise ValueError(f"{host} adapter content diverges from release lock")
        expected_skill_hashes = {
            skill_name: pin.content_hash for skill_name, pin in manifest.skills.items()
        }
        if adapter_pin.skill_hashes != expected_skill_hashes:
            raise ValueError(f"{host} adapter skill hashes diverge from release lock")

    manifest_path = root / "adapters" / RELEASE_MANIFEST_FILENAME
    try:
        mirrored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read mirrored release manifest: {error}") from error
    if mirrored_manifest != manifest.model_dump(mode="json", exclude_none=True):
        raise ValueError("mirrored release manifest diverges from rob2.lock")


def verify_mcp_launchability(
    project_root: Path,
    command: str,
    args: tuple[str, ...],
) -> tuple[str, ...]:
    """Start the locked external stdio launcher and return its tool inventory."""

    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def inspect() -> tuple[str, ...]:
        parameters = StdioServerParameters(
            command=command,
            args=list(args),
            cwd=project_root,
        )
        errlog = cast(TextIO, sys.__stderr__ or sys.stderr)
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                with anyio.fail_after(20):
                    await session.initialize()
                    inventory = await session.list_tools()
                return tuple(tool.name for tool in inventory.tools)

    tools = anyio.run(inspect)
    if tools != RUN_OPERATION_NAMES:
        raise ValueError("the launched MCP server does not expose the locked tool surface")
    return tools


def _canonical_skill_assets(root: Path) -> dict[str, CanonicalSkillAssets]:
    skills_root = root / "skills"
    if not skills_root.is_dir():
        raise ValueError("canonical skills directory is missing")
    actual_skill_names = {path.name for path in skills_root.iterdir()}
    expected_skill_names = set(CANONICAL_SKILL_NAMES)
    if actual_skill_names != expected_skill_names:
        raise ValueError(
            "canonical skills must contain exactly rob2-init and rob2-assess"
        )

    assets: dict[str, CanonicalSkillAssets] = {}
    for skill_name in CANONICAL_SKILL_NAMES:
        skill_root = skills_root / skill_name
        expected_files = {"SKILL.md", "activation-fixtures.json"}
        actual_files = {path.name for path in skill_root.iterdir()}
        if actual_files != expected_files:
            raise ValueError(f"canonical skill {skill_name} has unexpected assets")
        skill_path = skill_root / "SKILL.md"
        fixture_path = skill_root / "activation-fixtures.json"
        if f"name: {skill_name}" not in skill_path.read_text(encoding="utf-8"):
            raise ValueError(f"canonical skill {skill_name} has the wrong front matter name")
        try:
            fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"canonical skill {skill_name} fixtures are invalid: {error}"
            ) from error
        if not isinstance(fixtures, dict) or not all(
            isinstance(fixtures.get(key), list) for key in ("activates", "does_not_activate")
        ):
            raise ValueError(f"canonical skill {skill_name} fixtures are invalid")
        assets[skill_name] = CanonicalSkillAssets(skill=skill_path, fixtures=fixture_path)
    return assets


def _skill_pins(assets: dict[str, CanonicalSkillAssets]) -> dict[str, SkillPin]:
    return {
        skill_name: SkillPin(
            content_hash=_hash(paths.skill),
            activation_fixtures_hash=_hash(paths.fixtures),
        )
        for skill_name, paths in assets.items()
    }


def _validate_lock_shape(manifest: ReleaseLock) -> None:
    if manifest.package != "rob2-kit":
        raise ValueError("release lock package must be rob2-kit")
    if set(manifest.skills) != set(CANONICAL_SKILL_NAMES):
        raise ValueError("release lock must pin exactly the canonical skills")
    if set(manifest.adapters) != set(SUPPORTED_HOSTS):
        raise ValueError("release lock must pin both supported Harness adapters")
    if "latest" in manifest.launcher.casefold():
        raise ValueError("release launcher must pin an exact package release")
    if f"{manifest.package}=={manifest.package_version}" not in manifest.launcher:
        raise ValueError("release launcher must pin the exact package release")


def _prepare_adapter_destination(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    allowed = {"adapter.json", "launcher.txt", "skills", "SKILL.md", "activation-fixtures.json"}
    unexpected = {path.name for path in destination.iterdir()} - allowed
    if unexpected:
        raise ValueError(f"{destination.name} adapter has unexpected assets: {sorted(unexpected)}")
    for legacy in (destination / "SKILL.md", destination / "activation-fixtures.json"):
        if legacy.exists():
            raise ValueError(
                f"{destination.name} adapter retains a legacy single-skill layout"
            )
    generated_skills = destination / "skills"
    if generated_skills.exists():
        shutil.rmtree(generated_skills)


def _launcher(package_version: str) -> str:
    return f"uvx --python {PYTHON_VERSION} --from rob2-kit=={package_version} rob2-mcp"


def _dependency_lock_hash(root: Path) -> str:
    dependency_lock = root / "uv.lock"
    if not dependency_lock.is_file():
        raise ValueError("frozen dependency lock is missing")
    return _hash(dependency_lock)


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _descriptor(
    host: str,
    *,
    package_version: str,
    launcher: str,
    skill_pins: dict[str, SkillPin],
) -> dict[str, object]:
    template_path = Path(__file__).with_name("templates") / f"{host}-adapter.json"
    descriptor = json.loads(template_path.read_text(encoding="utf-8"))
    descriptor.update(
        {
            "package": "rob2-kit",
            "package_version": package_version,
            "skills": list(CANONICAL_SKILL_NAMES),
            "trigger_description": (
                "Prepare an evidence-grounded RoB 2 assessment and materialize "
                "a static report."
            ),
            "skill_hashes": {
                skill_name: pin.content_hash for skill_name, pin in skill_pins.items()
            },
            "activation_fixtures_hashes": {
                skill_name: pin.activation_fixtures_hash
                for skill_name, pin in skill_pins.items()
            },
            "launcher": launcher,
            "launcher_working_directory": "project_root",
        }
    )
    return descriptor


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    root = Path.cwd()
    manifest = build_host_adapters(root, package_version="0.1.0")
    print(manifest.model_dump_json())
