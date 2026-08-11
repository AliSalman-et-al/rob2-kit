"""Build and verify the frozen lean-v1 release contract."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO, cast

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.application.contracts import CONTRACT_VERSION, RUN_OPERATION_NAMES

CANONICAL_SKILL_NAMES = ("rob2-init", "rob2-assess")
SUPPORTED_HOSTS = ("codex", "claude")
SKILL_REFERENCE_FILENAMES = (
    "HARNESS-WORKFLOW.md",
    "RUN-DEFINITION.md",
    "EVIDENCE-SEARCH.md",
    "SIGNALING-QUESTIONS.md",
)
JOURNEY_DOCUMENTATION_FILENAMES = ("USER-JOURNEY.md", "LOCAL-RUNBOOK.md")
_OBSOLETE_DOCUMENTATION_TERMS = (
    "run_status",
    "classify_sources",
    "submit_source_classification",
    "resolve_result",
    "correct_domain_answers",
    "limitation field",
)
# This is an adapter permission boundary, not an assertion that the server has
# no compatibility routes.  Skills may use only these stable workflow tools.
SKILL_ALLOWED_TOOL_NAMES = (
    "prepare_run",
    "continue_run",
    "get_work_context",
    "submit_run_proposal",
    "submit_proposal_discovery_review",
    "submit_result_mapping_review",
    "confirm_run_definition",
    "search_evidence",
    "read_evidence",
    "submit_evidence_review",
    "inspect_visual_candidate",
    "submit_source_role_review",
    "submit_result_resolution",
    "submit_domain_evidence",
    "submit_domain_answers",
)
LOCK_FILENAME = "rob2.lock"
RELEASE_MANIFEST_FILENAME = "release-manifest.json"
ADAPTER_VERSION = "1"
PYTHON_VERSION = "3.13"


class SkillPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    activation_fixtures_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    forward_fixtures_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class AdapterPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    skill_hashes: dict[str, str]


@dataclass(frozen=True)
class CanonicalSkillAssets:
    skill: Path
    fixtures: Path
    forward_fixtures: Path


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
    validate_skill_contract(root)
    validate_documentation_contract(root)
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
            shutil.copyfile(
                paths.forward_fixtures,
                generated_skill / "forward-fixtures.json",
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
            skill_hashes={skill_name: pin.content_hash for skill_name, pin in skill_pins.items()},
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
        logic_pack_hash=_hash(root / "packs" / "logic" / "rob2-parallel-assignment-2019.1.yaml"),
        guidance_pack="rob2-parallel-assignment-en-2019.1",
        guidance_pack_hash=_hash(
            root / "packs" / "guidance" / "rob2-parallel-assignment-en-2019.1.yaml"
        ),
    )
    _write_json(root / LOCK_FILENAME, manifest.model_dump(mode="json", exclude_none=True))
    _write_json(
        root / "adapters" / RELEASE_MANIFEST_FILENAME,
        manifest.model_dump(mode="json", exclude_none=True),
    )
    return manifest


def release_root() -> Path:
    """Return the root containing this installation's ``rob2.lock`` release contract.

    A release wheel embeds ``rob2.lock`` next to the installed ``rob2_kit``
    package; a source checkout keeps it at the repository root instead.
    """

    package_root = Path(__file__).resolve().parent
    if (package_root / LOCK_FILENAME).is_file():
        return package_root
    return package_root.parents[1]


def installed_release_fingerprint(root: Path, lock: ReleaseLock) -> dict[str, object]:
    """Canonical named identity components of one installed release.

    This is the single source of the schema/parser/pack/skill/adapter identity
    computation that the ownership-manifest check (bootstrap/doctor time) and
    the execution-contract check (per-run drift detection) each need; every
    caller compares only the subset of these components it actually depends
    on, rather than recomputing its own copy of the hashing.
    """

    schema_hashes = {
        path.name: _content_hash(path)
        for path in sorted((root / "schemas").glob("*.json"))
        if path.is_file()
    }
    return {
        "engine_version": lock.package_version,
        "schema_hashes": schema_hashes,
        "parser_name": "liteparse",
        "parser_version": _distribution_version("liteparse"),
        "logic_pack_hash": lock.logic_pack_hash,
        "guidance_pack_hash": lock.guidance_pack_hash,
        "skill_hashes": {name: pin.content_hash for name, pin in lock.skills.items()},
        "adapter_hashes": {host: pin.content_hash for host, pin in lock.adapters.items()},
        "release_status": lock.release_status,
        "dependency_lock_hash": lock.dependency_lock_hash,
    }


def verify_ownership_identities(manifest: dict[str, object], root: Path, lock: ReleaseLock) -> None:
    """Verify one project's recorded ownership identities against the installed release.

    Raises ``ValueError`` describing the first mismatch found. This is the
    identity-comparison logic shared by the harness ownership-manifest check
    (which also verifies unrelated host-configuration and owned-file
    concerns) and any lighter caller -- such as a per-run drift check -- that
    only needs to know whether a project's recorded release identity still
    matches what is currently installed.
    """

    identities = manifest.get("identities", {})
    if not isinstance(identities, dict):
        raise ValueError("ownership identities are malformed")
    fingerprint = installed_release_fingerprint(root, lock)
    if identities.get("engine", {}).get("version") != fingerprint["engine_version"]:
        raise ValueError("ownership engine identity differs from the installed release")
    schema = identities.get("schema", {})
    if schema.get("version") != "1" or schema.get("hashes") != fingerprint["schema_hashes"]:
        raise ValueError("ownership schema identity differs from the installed release")
    parser = identities.get("parser", {})
    if (
        parser.get("name") != fingerprint["parser_name"]
        or parser.get("version") != fingerprint["parser_version"]
    ):
        raise ValueError("ownership parser identity differs from the installed release")
    packs = identities.get("packs", {})
    if (
        packs.get("logic", {}).get("hash") != fingerprint["logic_pack_hash"]
        or packs.get("guidance", {}).get("hash") != fingerprint["guidance_pack_hash"]
    ):
        raise ValueError("ownership pack identity differs from the installed release")
    for name, expected_hash in fingerprint["skill_hashes"].items():
        if identities.get("skills", {}).get(name, {}).get("hash") != expected_hash:
            raise ValueError(f"ownership skill identity differs for {name}")
    for host, expected_hash in fingerprint["adapter_hashes"].items():
        if identities.get("adapters", {}).get(host, {}).get("hash") != expected_hash:
            raise ValueError(f"ownership adapter identity differs for {host}")
    if identities.get("policies", {}).get("release_status") != fingerprint["release_status"]:
        raise ValueError("ownership policy identity differs from the installed release")


def _content_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


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
    validate_skill_contract(root)
    validate_documentation_contract(root)
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
            (destination / legacy).exists() for legacy in ("SKILL.md", "activation-fixtures.json")
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
            if actual_files != {"SKILL.md", "activation-fixtures.json", "forward-fixtures.json"}:
                raise ValueError(f"{host} adapter skill {skill_name} has unexpected assets")
            if _canonical_text_bytes(generated_skill / "SKILL.md") != _canonical_text_bytes(
                paths.skill
            ):
                raise ValueError(f"{host} adapter skill {skill_name} diverges from canonical")
            if _canonical_text_bytes(
                generated_skill / "activation-fixtures.json"
            ) != _canonical_text_bytes(paths.fixtures):
                raise ValueError(f"{host} adapter fixtures for {skill_name} diverge from canonical")
            if _canonical_text_bytes(
                generated_skill / "forward-fixtures.json"
            ) != _canonical_text_bytes(paths.forward_fixtures):
                raise ValueError(
                    f"{host} adapter forward fixtures for {skill_name} diverge from canonical"
                )

        expected_descriptor = _descriptor(
            host,
            package_version=manifest.package_version,
            launcher=manifest.launcher,
            skill_pins=manifest.skills,
        )
        try:
            descriptor = json.loads((destination / "adapter.json").read_text(encoding="utf-8"))
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
    *,
    environment: dict[str, str] | None = None,
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
            env={**os.environ, **(environment or {})},
        )
        errlog = cast(TextIO, sys.__stderr__ or sys.stderr)
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                with anyio.fail_after(20):
                    await session.initialize()
                    inventory = await session.list_tools()
                return tuple(tool.name for tool in inventory.tools)

    tools = anyio.run(inspect)
    if tools != SKILL_ALLOWED_TOOL_NAMES:
        raise ValueError(
            "the launched MCP server does not expose the locked tool surface: "
            f"expected {SKILL_ALLOWED_TOOL_NAMES!r}, got {tools!r}"
        )
    return tools


def _canonical_skill_assets(root: Path) -> dict[str, CanonicalSkillAssets]:
    skills_root = root / "skills"
    if not skills_root.is_dir():
        raise ValueError("canonical skills directory is missing")
    actual_skill_names = {path.name for path in skills_root.iterdir()}
    expected_skill_names = set(CANONICAL_SKILL_NAMES)
    if actual_skill_names != expected_skill_names:
        raise ValueError("canonical skills must contain exactly rob2-init and rob2-assess")

    assets: dict[str, CanonicalSkillAssets] = {}
    for skill_name in CANONICAL_SKILL_NAMES:
        skill_root = skills_root / skill_name
        expected_files = {"SKILL.md", "activation-fixtures.json", "forward-fixtures.json"}
        actual_files = {path.name for path in skill_root.iterdir()}
        if actual_files != expected_files:
            raise ValueError(f"canonical skill {skill_name} has unexpected assets")
        skill_path = skill_root / "SKILL.md"
        fixture_path = skill_root / "activation-fixtures.json"
        forward_fixture_path = skill_root / "forward-fixtures.json"
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
        _validate_forward_fixtures(skill_name, forward_fixture_path)
        assets[skill_name] = CanonicalSkillAssets(
            skill=skill_path,
            fixtures=fixture_path,
            forward_fixtures=forward_fixture_path,
        )
    return assets


def _skill_pins(assets: dict[str, CanonicalSkillAssets]) -> dict[str, SkillPin]:
    return {
        skill_name: SkillPin(
            content_hash=_hash(paths.skill),
            activation_fixtures_hash=_hash(paths.fixtures),
            forward_fixtures_hash=_hash(paths.forward_fixtures),
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
            raise ValueError(f"{destination.name} adapter retains a legacy single-skill layout")
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
    return "sha256:" + hashlib.sha256(_canonical_text_bytes(path)).hexdigest()


def _canonical_text_bytes(path: Path) -> bytes:
    """Hash release text identically across LF and CRLF checkouts."""

    return path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(_canonical_text_bytes(path))
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
            "allowed_tools": list(SKILL_ALLOWED_TOOL_NAMES),
            "trigger_description": (
                "Prepare an evidence-grounded RoB 2 assessment and materialize a static report."
            ),
            "skill_hashes": {
                skill_name: pin.content_hash for skill_name, pin in skill_pins.items()
            },
            "activation_fixtures_hashes": {
                skill_name: pin.activation_fixtures_hash for skill_name, pin in skill_pins.items()
            },
            "forward_fixtures_hashes": {
                skill_name: pin.forward_fixtures_hash for skill_name, pin in skill_pins.items()
            },
            "launcher": launcher,
            "launcher_working_directory": "project_root",
        }
    )
    return descriptor


def validate_skill_contract(root: Path) -> None:
    """Validate the release-owned skill, reference, and forward-test contract."""

    root = root.resolve()
    if len(SKILL_ALLOWED_TOOL_NAMES) != 15 or len(set(SKILL_ALLOWED_TOOL_NAMES)) != 15:
        raise ValueError("skill tool allowlist must contain exactly fifteen unique tools")
    if any(not isinstance(name, str) or not name for name in SKILL_ALLOWED_TOOL_NAMES):
        raise ValueError("skill tool allowlist is malformed")
    if not set(SKILL_ALLOWED_TOOL_NAMES) <= set(RUN_OPERATION_NAMES):
        raise ValueError("skill tool allowlist includes a tool outside the public workflow")
    if tuple(SKILL_REFERENCE_FILENAMES) != tuple(dict.fromkeys(SKILL_REFERENCE_FILENAMES)):
        raise ValueError("skill references must be unique")
    for name in SKILL_REFERENCE_FILENAMES:
        reference = root / "docs" / name
        if not reference.is_file():
            raise ValueError(f"skill reference is missing: {name}")
        if ".md" in reference.read_text(encoding="utf-8").casefold():
            raise ValueError(f"skill reference must not chain to another reference: {name}")
    assets = _canonical_skill_assets(root)
    skill_bodies = {
        skill_name: paths.skill.read_text(encoding="utf-8") for skill_name, paths in assets.items()
    }
    pointers_by_skill = {
        skill_name: set(re.findall(r"\.\./references/([^/\s`]+\.md)", body))
        for skill_name, body in skill_bodies.items()
    }
    pointers = set().union(*pointers_by_skill.values())
    if pointers != set(SKILL_REFERENCE_FILENAMES):
        raise ValueError(
            "canonical skills must point directly to exactly the four shared references"
        )
    for skill_name, paths in assets.items():
        body = skill_bodies[skill_name]
        front_matter, delimiter, content = body.removeprefix("---\n").partition("\n---\n")
        front_matter_lines = front_matter.splitlines()
        if (
            not body.startswith("---\n")
            or not delimiter
            or not content.strip()
            or f"name: {skill_name}" not in front_matter_lines
        ):
            raise ValueError(f"canonical skill {skill_name} has invalid front matter")
        description = next(
            (
                line.removeprefix("description: ")
                for line in front_matter_lines
                if line.startswith("description: ")
            ),
            "",
        )
        if not description or len(description) > 240:
            raise ValueError(f"canonical skill {skill_name} description is missing or too long")
        required_references = (
            SKILL_REFERENCE_FILENAMES
            if skill_name == "rob2-assess"
            else ("HARNESS-WORKFLOW.md", "RUN-DEFINITION.md")
        )
        if not set(required_references) <= pointers_by_skill[skill_name]:
            raise ValueError(f"canonical skill {skill_name} is missing a direct context pointer")


def validate_documentation_contract(root: Path) -> None:
    """Reject stale workflow vocabulary in the canonical and bundled journey docs."""

    root = root.resolve()
    documentation = tuple(root / "docs" / name for name in JOURNEY_DOCUMENTATION_FILENAMES) + tuple(
        root / "docs" / name for name in SKILL_REFERENCE_FILENAMES
    )
    for path in documentation:
        if not path.is_file():
            raise ValueError(f"journey documentation is missing: {path.name}")
        content = path.read_text(encoding="utf-8")
        lowered = content.casefold()
        for obsolete in _OBSOLETE_DOCUMENTATION_TERMS:
            if obsolete in lowered:
                raise ValueError(f"obsolete workflow term in documentation: {obsolete}")

    journey = (root / "docs" / "USER-JOURNEY.md").read_text(encoding="utf-8").casefold()
    version_marker = f"<!-- rob2-kit-contract-version: {CONTRACT_VERSION} -->".casefold()
    if version_marker not in journey:
        raise ValueError("journey documentation contract version diverges from the release")
    required_topics = (
        "install once",
        "arrange inputs",
        "ask naturally",
        "troubleshoot safely",
        "maintain the installation",
    )
    if any(topic not in journey for topic in required_topics):
        raise ValueError("journey documentation is missing a required user path")


def _validate_forward_fixtures(skill_name: str, path: Path) -> None:
    try:
        fixtures = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"canonical skill {skill_name} forward fixtures are invalid: {error}"
        ) from error
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError(f"canonical skill {skill_name} forward fixtures are invalid")
    required = {"scenario", "prompt", "activated_skill", "allowed_tools"}
    for fixture in fixtures:
        if not isinstance(fixture, dict) or set(fixture) != required:
            raise ValueError(f"canonical skill {skill_name} forward fixture has an invalid shape")
        if not isinstance(fixture["scenario"], str) or not fixture["scenario"]:
            raise ValueError(f"canonical skill {skill_name} forward fixture has no scenario")
        if not isinstance(fixture["prompt"], str) or not fixture["prompt"]:
            raise ValueError(f"canonical skill {skill_name} forward fixture has no prompt")
        if fixture["activated_skill"] not in CANONICAL_SKILL_NAMES:
            raise ValueError(f"canonical skill {skill_name} forward fixture has an invalid skill")
        tools = fixture["allowed_tools"]
        if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            raise ValueError(f"canonical skill {skill_name} forward fixture has invalid tools")
        if not set(tools) <= set(SKILL_ALLOWED_TOOL_NAMES):
            raise ValueError(
                f"canonical skill {skill_name} forward fixture exceeds the tool allowlist"
            )
        if any(
            term in fixture["prompt"].casefold()
            for term in ("expected answer", "expected judgment")
        ):
            raise ValueError(
                f"canonical skill {skill_name} forward fixture leaks an expected answer"
            )
    if skill_name == "rob2-assess" and {
        "normal",
        "resume",
        "negative",
        "correction",
        "report_explanation",
    } - {fixture["scenario"] for fixture in fixtures}:
        raise ValueError("rob2-assess forward fixtures do not cover the required prompt families")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    root = Path.cwd()
    manifest = build_host_adapters(root, package_version="0.1.0")
    print(manifest.model_dump_json())
