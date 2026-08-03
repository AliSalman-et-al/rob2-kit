import hashlib
import json
import shutil
from pathlib import Path

import pytest

from rob2_kit.release import build_host_adapters, load_release_lock, verify_host_adapters

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {"rob2-init", "rob2-assess"}
EXPECTED_HOSTS = {"codex", "claude"}


def sha256_file(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def test_checked_in_release_lock_pins_the_two_skills_and_both_harnesses() -> None:
    lock = load_release_lock(ROOT)

    assert lock.package == "rob2-kit"
    assert lock.package_version == "0.1.0"
    assert lock.python_version == "3.13"
    assert set(lock.skills) == EXPECTED_SKILLS
    assert set(lock.adapters) == EXPECTED_HOSTS

    for skill_name in EXPECTED_SKILLS:
        skill_root = ROOT / "skills" / skill_name
        assert lock.skills[skill_name].content_hash == sha256_file(skill_root / "SKILL.md")
        assert lock.skills[skill_name].activation_fixtures_hash == sha256_file(
            skill_root / "activation-fixtures.json"
        )

    for host in EXPECTED_HOSTS:
        adapter = lock.adapters[host]
        assert set(adapter.skill_hashes) == EXPECTED_SKILLS
        assert adapter.skill_hashes == {
            skill_name: lock.skills[skill_name].content_hash for skill_name in EXPECTED_SKILLS
        }

    verify_host_adapters(ROOT)


def test_generated_adapters_materialize_both_skill_trees_and_detect_drift(
    tmp_path: Path,
) -> None:
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "packs", tmp_path / "packs")
    shutil.copy(ROOT / "uv.lock", tmp_path / "uv.lock")

    manifest = build_host_adapters(tmp_path, package_version="0.1.0")

    assert set(manifest.skills) == EXPECTED_SKILLS
    for host in EXPECTED_HOSTS:
        for skill_name in EXPECTED_SKILLS:
            generated = tmp_path / "adapters" / host / "skills" / skill_name
            assert (generated / "SKILL.md").is_file()
            assert (generated / "activation-fixtures.json").is_file()
    verify_host_adapters(tmp_path)

    generated_skill = tmp_path / "adapters" / "codex" / "skills" / "rob2-init" / "SKILL.md"
    generated_skill.write_text(
        generated_skill.read_text(encoding="utf-8") + "drift\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="codex.*rob2-init|skill"):
        verify_host_adapters(tmp_path)


def test_release_verification_is_stable_across_text_line_endings(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "packs", tmp_path / "packs")
    shutil.copy(ROOT / "uv.lock", tmp_path / "uv.lock")
    build_host_adapters(tmp_path, package_version="0.1.0")

    text_assets = [
        tmp_path / "skills" / "rob2-init" / "SKILL.md",
        tmp_path / "adapters" / "codex" / "skills" / "rob2-init" / "SKILL.md",
        tmp_path / "uv.lock",
    ]
    for path in text_assets:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        path.write_bytes(text.replace("\n", "\r\n").encode())

    verify_host_adapters(tmp_path)


def test_release_lock_rejects_an_extra_canonical_skill(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "packs", tmp_path / "packs")
    shutil.copy(ROOT / "uv.lock", tmp_path / "uv.lock")
    build_host_adapters(tmp_path, package_version="0.1.0")

    extra = tmp_path / "skills" / "legacy-review"
    extra.mkdir()
    (extra / "SKILL.md").write_text("---\nname: legacy-review\n---\n", encoding="utf-8")
    (extra / "activation-fixtures.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="canonical skills|exactly"):
        verify_host_adapters(tmp_path)


def test_release_lock_rejects_an_adapter_version_claim(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "packs", tmp_path / "packs")
    shutil.copy(ROOT / "uv.lock", tmp_path / "uv.lock")
    build_host_adapters(tmp_path, package_version="0.1.0")

    lock_path = tmp_path / "rob2.lock"
    raw = json.loads(lock_path.read_text(encoding="utf-8"))
    raw["adapters"]["codex"]["version"] = "2"
    lock_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="adapter version"):
        verify_host_adapters(tmp_path)


def test_lock_file_is_json_with_no_legacy_single_skill_hash() -> None:
    raw = json.loads((ROOT / "rob2.lock").read_text(encoding="utf-8"))

    assert set(raw["skills"]) == EXPECTED_SKILLS
    assert "canonical_skill_hash" not in raw
    assert "skill_hash" not in raw
