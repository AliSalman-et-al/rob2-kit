"""Verify the release manifest against the production source tree and wheel."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from email.parser import BytesParser
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from fastmcp import Client

from rob2_kit import __version__
from rob2_kit.batch_summary import BatchSummary, ProblemTerminal
from rob2_kit.finish import AssessmentSnapshot
from rob2_kit.ingestion import service as ingestion_service
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.server import mcp

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).with_name("release-manifest.json")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SOURCE_PATHS = [
    "pyproject.toml",
    "uv.lock",
    "src/rob2_kit/**/*.py",
    "src/rob2_kit/hosts/*.json",
    "src/rob2_kit/skills/*/SKILL.md",
]


def _fail(message: str) -> None:
    raise ValueError(f"release manifest: {message}")


def _exact(value: object, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        _fail(f"unexpected {name} shape")
    return cast(dict[str, Any], value)


def _strings(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _fail(f"{name} must be a string list")
    return cast(list[str], value)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _source_contract_hash(root: Path, patterns: list[str]) -> str:
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(path for path in root.glob(pattern) if path.is_file())
        if not matches:
            _fail(f"source contract pattern matches nothing: {pattern}")
        paths.extend(matches)
    relative = [path.relative_to(root).as_posix() for path in paths]
    if len(set(relative)) != len(relative):
        _fail("source contract patterns overlap")
    digest = hashlib.sha256()
    for path, name in sorted(zip(paths, relative, strict=True), key=lambda item: item[1]):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _exact(
        value,
        {
            "$schema",
            "schema_version",
            "package",
            "candidate",
            "dependencies",
            "build_dependencies",
            "development_dependencies",
            "dependencies_lock_sha256",
            "supported_platforms",
            "canonical_schemas",
            "packs",
            "skills",
            "mcp_contract",
            "host_acceptance",
            "execution_contract",
            "source_contract",
        },
        "top-level",
    )
    if (
        value["$schema"] != "https://json-schema.org/draft/2020-12/schema"
        or value["schema_version"] != 1
    ):
        _fail("unsupported schema version")
    package = _exact(value["package"], {"name", "version", "wheel_tag"}, "package")
    if package != {"name": "rob2-kit", "version": __version__, "wheel_tag": "py3-none-any"}:
        _fail("package identity differs from production")
    candidate = _exact(
        value["candidate"],
        {"branch", "base_commit", "implementation_commit", "release_freeze"},
        "candidate",
    )
    if candidate["branch"] != "greenfield/epic-182" or candidate["release_freeze"] != (
        "The release tag must be created from a clean checkout after this manifest is committed; "
        "this implementation commit is the frozen pre-manifest product base."
    ):
        _fail("candidate contract differs")
    if not all(isinstance(candidate[key], str) for key in ("base_commit", "implementation_commit")):
        _fail("candidate values must be strings")
    if not all(
        COMMIT.fullmatch(candidate[key]) for key in ("base_commit", "implementation_commit")
    ):
        _fail("candidate commit is not a full SHA-1")
    for name in ("dependencies", "build_dependencies", "development_dependencies"):
        pins = value[name]
        if (
            not isinstance(pins, dict)
            or not pins
            or any(
                not isinstance(key, str) or not isinstance(version, str) or not version
                for key, version in pins.items()
            )
        ):
            _fail(f"{name} must be a non-empty exact pin map")
    if set(value["dependencies"]) != {"fastmcp", "httpx", "pymupdf"}:
        _fail("runtime dependency set is not exact")
    if not isinstance(value["dependencies_lock_sha256"], str) or not SHA256.fullmatch(
        value["dependencies_lock_sha256"]
    ):
        _fail("invalid lock hash")
    platforms = _exact(value["supported_platforms"], {"python", "os"}, "supported platforms")
    for name in ("python", "os"):
        items = _strings(platforms[name], f"supported platforms {name}")
        if not items or len(set(items)) != len(items):
            _fail(f"supported platforms {name} must be unique and non-empty")
    schemas = value["canonical_schemas"]
    if not isinstance(schemas, dict) or set(schemas) != {
        "assessment_snapshot",
        "batch_summary",
        "problem_terminal",
        "registry_sources",
    }:
        _fail("canonical schema set differs")
    for name, schema in schemas.items():
        schema = _exact(schema, {"id", "version"}, f"canonical schema {name}")
        if not isinstance(schema["id"], str) or not isinstance(schema["version"], int):
            _fail(f"invalid canonical schema {name}")
    packs = _exact(value["packs"], {"scientific", "policy"}, "packs")
    for name, pack in packs.items():
        pack = _exact(pack, {"id", "version", "content_hash"}, f"{name} pack")
        if (
            not isinstance(pack["id"], str)
            or not isinstance(pack["version"], str)
            or not (
                isinstance(pack["content_hash"], str) and SHA256.fullmatch(pack["content_hash"])
            )
        ):
            _fail(f"invalid {name} pack")
    skills = value["skills"]
    if not isinstance(skills, list) or len(skills) != 2:
        _fail("must declare exactly two skills")
    names = []
    for skill in skills:
        skill = _exact(skill, {"name", "content_sha256"}, "skill")
        if not isinstance(skill["name"], str) or not isinstance(skill["content_sha256"], str):
            _fail("invalid skill")
        if not SHA256.fullmatch(skill["content_sha256"]):
            _fail("invalid skill hash")
        names.append(skill["name"])
    if names != ["rob2-workflow", "rob2-signalling"]:
        _fail("skill names or order differs")
    contract = _exact(value["mcp_contract"], {"tools", "resources"}, "MCP contract")
    for name in ("tools", "resources"):
        items = _strings(contract[name], f"MCP {name}")
        if not items or len(set(items)) != len(items):
            _fail(f"MCP {name} must be unique and non-empty")
    acceptance = _exact(
        value["host_acceptance"],
        {"claude_code", "raw_mcp", "codex_windows_0.147.0"},
        "host acceptance",
    )
    if not all(isinstance(item, str) and item for item in acceptance.values()):
        _fail("invalid host acceptance")
    execution = _exact(
        value["execution_contract"],
        {"server", "workspace_environment", "lockfile", "model_loop"},
        "execution contract",
    )
    if execution != {
        "server": "rob2_kit.server:main",
        "workspace_environment": "ROB2_WORKSPACE",
        "lockfile": "uv.lock",
        "model_loop": "installed Codex or Claude Code host only",
    }:
        _fail("execution contract differs")
    source = _exact(
        value["source_contract"], {"algorithm", "paths", "content_sha256"}, "source contract"
    )
    if (
        source["algorithm"] != "sha256(path-nul-content; lexical-posix-path-order)"
        or not isinstance(source["content_sha256"], str)
        or not SHA256.fullmatch(source["content_sha256"])
    ):
        _fail("invalid source contract")
    if source["paths"] != SOURCE_PATHS:
        _fail("source contract paths differ")
    return value


def _candidate_history(manifest: dict[str, Any]) -> None:
    candidate = manifest["candidate"]
    for commit in (candidate["base_commit"], candidate["implementation_commit"]):
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, check=False
        )
        if result.returncode:
            raise ValueError(f"candidate commit is unavailable: {commit}")
    result = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            candidate["base_commit"],
            candidate["implementation_commit"],
        ],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise ValueError("candidate base is not an ancestor of the implementation commit")


def _project_pins(manifest: dict[str, Any]) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def pinned(items: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in items:
            name, separator, version = item.partition("==")
            if not separator or not name or not version or name in result:
                raise ValueError("pyproject contains a non-exact dependency pin")
            result[name] = version
        return result

    if pinned(project["project"]["dependencies"]) != manifest["dependencies"]:
        raise ValueError("pyproject runtime pins differ from release manifest")
    if pinned(project["build-system"]["requires"]) != manifest["build_dependencies"]:
        raise ValueError("pyproject build pins differ from release manifest")
    if pinned(project["dependency-groups"]["dev"]) != manifest["development_dependencies"]:
        raise ValueError("pyproject development pins differ from release manifest")


def _workflow_matrix(manifest: dict[str, Any]) -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for name, expected in (
        ("os", manifest["supported_platforms"]["os"]),
        ("python-version", manifest["supported_platforms"]["python"]),
    ):
        match = re.search(rf"^        {re.escape(name)}: \[(.+)\]$", workflow, re.MULTILINE)
        if match is None:
            raise ValueError(f"CI does not declare a {name} matrix")
        actual = [item.strip().strip('"') for item in match.group(1).split(",")]
        if actual != expected:
            raise ValueError(f"CI {name} matrix differs from release manifest")
    if 'python-version: "${{ matrix.python-version }}"' not in workflow:
        raise ValueError("CI setup-python does not use the declared matrix")
    if "fetch-depth: 0" not in workflow:
        raise ValueError("CI does not fetch the frozen candidate ancestry")
    if "verify.py --wheel .release-dist/rob2_kit-0.1.0-py3-none-any.whl" not in workflow:
        raise ValueError("CI does not verify the exact built wheel")


async def _verify_mcp(manifest: dict[str, Any]) -> None:
    contract = manifest["mcp_contract"]
    current, guidance, registry = contract["resources"]
    async with Client(mcp) as client:
        tools = [tool.name for tool in await client.list_tools()]
        resources = [str(resource.uri) for resource in await client.list_resources()]
        templates = [str(item.uriTemplate) for item in await client.list_resource_templates()]
        current_value = await client.read_resource(current)
        guidance_value = await client.read_resource(
            guidance.replace("{domain_id}", "domain:randomization")
        )
        registry_value = await client.read_resource(registry.replace("{trial_id}", "release-check"))
    if tools != contract["tools"] or resources != [current] or templates != [guidance, registry]:
        raise ValueError("production MCP inventory differs from release manifest")
    if (
        current_value[0].text != '{"active_batch":null}'
        or not guidance_value[0].text
        or not registry_value[0].text
    ):
        raise ValueError("production MCP resources are not readable")


def _verify_wheel(path: Path, manifest: dict[str, Any]) -> None:
    package = manifest["package"]
    distribution = f"{package['name'].replace('-', '_')}-{package['version']}.dist-info"
    with zipfile.ZipFile(path) as wheel:
        names = set(wheel.namelist())
        metadata_name = f"{distribution}/METADATA"
        required = {metadata_name, "rob2_kit/hosts/codex.json", "rob2_kit/hosts/claude-code.json"}
        required.update(f"rob2_kit/skills/{skill['name']}/SKILL.md" for skill in manifest["skills"])
        if not required <= names:
            raise ValueError("wheel is missing a required package, host, or skill asset")
        metadata = BytesParser().parsebytes(wheel.read(metadata_name))
        if metadata["Name"] != package["name"] or metadata["Version"] != package["version"]:
            raise ValueError("wheel package metadata differs from release manifest")
        actual_dependencies = set(metadata.get_all("Requires-Dist", []))
        expected_dependencies = {
            f"{name}=={version}" for name, version in manifest["dependencies"].items()
        }
        if actual_dependencies != expected_dependencies:
            raise ValueError("wheel runtime dependency set differs from release manifest")
        skill_names = {skill["name"] for skill in manifest["skills"]}
        packaged_skills = {
            name.split("/")[2]
            for name in names
            if name.startswith("rob2_kit/skills/") and name.endswith("/SKILL.md")
        }
        if packaged_skills != skill_names:
            raise ValueError("wheel portable skill set differs from release manifest")
        for skill in manifest["skills"]:
            raw = wheel.read(f"rob2_kit/skills/{skill['name']}/SKILL.md")
            if _sha256_bytes(raw) != skill["content_sha256"]:
                raise ValueError(f"wheel skill hash differs: {skill['name']}")
        expected_hosts = {
            "codex.json": "codex",
            "claude-code.json": "claude-code",
        }
        packaged_hosts = {
            name.removeprefix("rob2_kit/hosts/")
            for name in names
            if name.startswith("rob2_kit/hosts/") and name.endswith(".json")
        }
        if packaged_hosts != set(expected_hosts):
            raise ValueError("wheel host asset set differs from release manifest")
        for filename, host in expected_hosts.items():
            host_data = json.loads(wheel.read(f"rob2_kit/hosts/{filename}"))
            if host_data != {
                "host": host,
                "mcp_command": "rob2-mcp",
                "skill_directory": "rob2_kit/skills",
                "skills": [skill["name"] for skill in manifest["skills"]],
            }:
                raise ValueError(f"wheel host asset differs: {filename}")


def _verify_schema_identities(manifest: dict[str, Any]) -> None:
    expected = {
        "assessment_snapshot": AssessmentSnapshot,
        "batch_summary": BatchSummary,
        "problem_terminal": ProblemTerminal,
    }
    for name, model in expected.items():
        frozen = manifest["canonical_schemas"][name]
        fields = model.model_fields
        if (
            fields["schema_id"].default != frozen["id"]
            or fields["schema_version"].default != frozen["version"]
        ):
            raise ValueError(f"schema identity differs: {name}")
    registry = manifest["canonical_schemas"]["registry_sources"]
    if registry["id"] != ingestion_service._REGISTRY_SCHEMA:
        raise ValueError("registry source schema differs from release manifest")
    version = re.fullmatch(r".+\.v(\d+)", ingestion_service._REGISTRY_SCHEMA)
    if version is None or registry["version"] != int(version.group(1)):
        raise ValueError("registry source schema version differs from release manifest")


def verify(wheel: Path | None = None, manifest_path: Path = MANIFEST_PATH) -> None:
    manifest = _manifest(manifest_path)
    _candidate_history(manifest)
    if _sha256_bytes((ROOT / "uv.lock").read_bytes()) != manifest["dependencies_lock_sha256"]:
        raise ValueError("uv.lock hash differs from release manifest")
    if (
        _source_contract_hash(ROOT, manifest["source_contract"]["paths"])
        != manifest["source_contract"]["content_sha256"]
    ):
        raise ValueError("source contract hash differs from release manifest")
    _project_pins(manifest)
    _workflow_matrix(manifest)
    assets = files("rob2_kit")
    for skill in manifest["skills"]:
        if (
            _sha256_bytes(assets.joinpath("skills", skill["name"], "SKILL.md").read_bytes())
            != skill["content_sha256"]
        ):
            raise ValueError(f"portable skill hash differs: {skill['name']}")
    packs = manifest["packs"]
    if packs["scientific"] != SCIENTIFIC_PACK.model_dump(include={"id", "version", "content_hash"}):
        raise ValueError("scientific pack identity differs from release manifest")
    if packs["policy"] != MAINTAINER_POLICY_PACK.model_dump(
        include={"id", "version", "content_hash"}
    ):
        raise ValueError("policy pack identity differs from release manifest")
    _verify_schema_identities(manifest)
    asyncio.run(_verify_mcp(manifest))
    if wheel is not None:
        _verify_wheel(wheel, manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    verify(parser.parse_args().wheel)
