import importlib.util
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest


def _verifier():
    spec = importlib.util.spec_from_file_location("release_verify", "docs/release/verify.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wheel(path: Path, manifest: dict[str, Any], mode: str = "valid") -> None:
    package = manifest["package"]
    distribution = f"{package['name'].replace('-', '_')}-{package['version']}.dist-info"
    dependencies = manifest["dependencies"]
    requires = [f"Requires-Dist: {name}=={version}" for name, version in dependencies.items()]
    if mode == "extra_dependency":
        requires.append("Requires-Dist: unexpected==1")
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr(
            f"{distribution}/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: {package['name']}\n"
            f"Version: {package['version']}\n" + "\n".join(requires),
        )
        for skill in manifest["skills"]:
            content = Path("src/rob2_kit/skills") / skill["name"] / "SKILL.md"
            raw = content.read_bytes()
            if mode == "tampered_skill" and skill["name"] == "rob2-workflow":
                raw += b"tampered"
            wheel.writestr(f"rob2_kit/skills/{skill['name']}/SKILL.md", raw)
        for filename, host in (("codex.json", "codex"), ("claude-code.json", "claude-code")):
            if mode == "missing_host" and filename == "claude-code.json":
                continue
            skills = [skill["name"] for skill in manifest["skills"]]
            if mode == "host_drift" and filename == "codex.json":
                skills.reverse()
            wheel.writestr(
                f"rob2_kit/hosts/{filename}",
                json.dumps(
                    {
                        "host": host,
                        "mcp_command": "rob2-mcp",
                        "skill_directory": "rob2_kit/skills",
                        "skills": skills,
                    }
                ),
            )


def test_release_manifest_verifies_production_contract() -> None:
    _verifier().verify()


def test_manifest_rejects_unexpected_nested_value(tmp_path: Path) -> None:
    verifier = _verifier()
    manifest = deepcopy(verifier._manifest())
    manifest["skills"][0]["unexpected"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected skill shape"):
        verifier._manifest(path)


def test_registry_schema_drift_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _verifier()
    monkeypatch.setattr(verifier.ingestion_service, "_REGISTRY_SCHEMA", "drift")
    with pytest.raises(ValueError, match="registry source schema differs"):
        verifier.verify()


def test_wheel_contract_accepts_complete_wheel(tmp_path: Path) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest)
    verifier._verify_wheel(wheel, manifest)


@pytest.mark.parametrize(
    "mode", ["tampered_skill", "missing_host", "extra_dependency", "host_drift"]
)
def test_wheel_asset_and_dependency_tampering_is_rejected(tmp_path: Path, mode: str) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, mode)
    with pytest.raises(ValueError):
        verifier._verify_wheel(wheel, manifest)
