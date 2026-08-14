import importlib.util
import json
import zipfile
from base64 import urlsafe_b64encode
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, TypeAlias

import pytest

WheelMode: TypeAlias = Literal[
    "valid",
    "extra_dependency",
    "duplicate_dependency",
    "duplicate_name",
    "duplicate_version",
    "entry_point_redirect",
    "entry_point_missing",
    "entry_point_uppercase",
    "entry_point_colon",
    "entry_point_crlf",
    "entry_point_cr",
    "entry_point_unicode",
    "wheel_tag",
    "wheel_purelib",
    "wheel_version",
    "wheel_duplicate",
    "wheel_generator",
    "wheel_missing_header",
    "wheel_unexpected_header",
    "wheel_appended_body",
    "wheel_leading_envelope",
    "wheel_crlf",
    "metadata_version",
    "metadata_missing_version",
    "metadata_duplicate_version",
    "metadata_unexpected",
    "metadata_leading_envelope",
    "metadata_malformed_pre_body_line",
    "metadata_appended_undeclared_bytes",
    "metadata_header_order",
    "python_drift",
    "python_missing",
    "python_duplicate",
    "tampered_skill",
    "crlf_skills",
    "missing_host",
    "host_drift",
    "host_duplicate_top",
    "host_duplicate_nested",
    "zero_modules",
    "missing_module",
    "tampered_module",
    "crlf_module",
    "extra_module",
    "purelib_extra",
    "purelib_host",
    "platlib_skill",
    "data_overlay",
    "data_generic",
    "case_alias",
    "case_host_alias",
    "case_metadata_alias",
    "traversal",
    "backslash",
    "drive_absolute",
    "trailing_dot",
    "trailing_space",
    "ads_module",
    "ads_metadata",
    "reserved_device",
    "native_extension",
    "shared_library",
    "bytecode",
    "path_file",
    "arbitrary_file",
    "duplicate_member",
    "record_missing",
    "record_extra",
    "record_duplicate",
    "record_bad_hash",
    "record_bad_size",
    "record_bad_self",
]


def _verifier():
    spec = importlib.util.spec_from_file_location("release_verify", "docs/release/verify.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wheel(path: Path, manifest: dict[str, Any], mode: WheelMode = "valid") -> None:
    package = manifest["package"]
    distribution = f"{package['name'].replace('-', '_')}-{package['version']}.dist-info"
    dependencies = manifest["dependencies"]
    requires = [f"Requires-Dist: {name}=={version}" for name, version in dependencies.items()]
    if mode == "extra_dependency":
        requires.append("Requires-Dist: unexpected==1")
    if mode == "duplicate_dependency":
        requires.append(requires[0])
    entries: list[tuple[str, bytes]] = []

    def write(name: str, value: str | bytes) -> None:
        entries.append((name, value.encode() if isinstance(value, str) else value))

    metadata = (
        "Metadata-Version: 2.4\n"
        f"Name: {package['name']}\nVersion: {package['version']}\n"
        "Summary: Model-free MCP boundary for RoB 2 assessment\n"
        "Requires-Python: >=3.11\n"
        + "\n".join(requires)
        + "\nDescription-Content-Type: text/markdown\n\n"
        + Path("README.md")
        .read_bytes()
        .replace(b"\r\n", b"\n")
        .replace(b"\r", b"\n")
        .decode("utf-8")
    )
    wheel_metadata = (
        "Wheel-Version: 1.0\nGenerator: hatchling 1.27.0\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    entry_points = "[console_scripts]\nrob2-mcp = rob2_kit.server:main\n"
    if mode == "entry_point_redirect":
        entry_points = "[console_scripts]\nrob2-mcp = attacker:main\n"
    if mode == "entry_point_missing":
        entry_points = "[console_scripts]\n"
    if mode == "entry_point_uppercase":
        entry_points = "[console_scripts]\nROB2-MCP = rob2_kit.server:main\n"
    if mode == "entry_point_colon":
        entry_points = "[console_scripts]\nrob2-mcp: rob2_kit.server:main\n"
    if mode == "entry_point_crlf":
        entry_points = entry_points.replace("\n", "\r\n")
    if mode == "entry_point_cr":
        entry_points = entry_points.replace("\n", "\r")
    if mode == "entry_point_unicode":
        entry_points = entry_points.replace("\n", "\u2028")
    if mode == "wheel_tag":
        wheel_metadata = wheel_metadata.replace("py3-none-any", "py311-none-any")
    if mode == "wheel_purelib":
        wheel_metadata = wheel_metadata.replace("true", "false")
    if mode == "wheel_version":
        wheel_metadata = wheel_metadata.replace("1.0", "1.1")
    if mode == "wheel_duplicate":
        wheel_metadata += "Tag: py3-none-any\n"
    if mode == "wheel_generator":
        wheel_metadata = wheel_metadata.replace("hatchling 1.27.0", "other 1.0")
    if mode == "wheel_missing_header":
        wheel_metadata = wheel_metadata.replace("Generator: hatchling 1.27.0\n", "")
    if mode == "wheel_unexpected_header":
        wheel_metadata += "Build: unexpected\n"
    if mode == "wheel_appended_body":
        wheel_metadata += "\nundeclared body\n"
    if mode == "wheel_leading_envelope":
        wheel_metadata = "From attacker\n" + wheel_metadata
    if mode == "wheel_crlf":
        wheel_metadata = wheel_metadata.replace("\n", "\r\n")
    if mode == "metadata_version":
        metadata = metadata.replace("Metadata-Version: 2.4", "Metadata-Version: 2.3")
    if mode == "metadata_missing_version":
        metadata = metadata.replace("Metadata-Version: 2.4\n", "")
    if mode == "metadata_duplicate_version":
        metadata = metadata.replace("Name:", "Metadata-Version: 2.4\nName:")
    if mode == "metadata_unexpected":
        metadata = metadata.replace("\n\n", "\nX-Extra: unexpected\n\n", 1)
    if mode == "metadata_leading_envelope":
        metadata = "From attacker\n" + metadata
    if mode == "metadata_malformed_pre_body_line":
        metadata = metadata.replace("\n\n", "\nmalformed pre-body line\n\n", 1)
    if mode == "metadata_appended_undeclared_bytes":
        metadata += "\nundeclared trailing bytes"
    if mode == "metadata_header_order":
        metadata = metadata.replace(
            "Metadata-Version: 2.4\nName: rob2-kit\n",
            "Name: rob2-kit\nMetadata-Version: 2.4\n",
        )
    if mode == "python_drift":
        metadata = metadata.replace(">=3.11", ">=3.12")
    if mode == "python_missing":
        metadata = metadata.replace("Requires-Python: >=3.11\n", "")
    if mode == "python_duplicate":
        metadata += "\nRequires-Python: >=3.11\n"
    if mode == "duplicate_name":
        metadata += f"\nName: {package['name']}\n"
    if mode == "duplicate_version":
        metadata += f"\nVersion: {package['version']}\n"
    write(f"{distribution}/METADATA", metadata)
    write(f"{distribution}/WHEEL", wheel_metadata)
    write(f"{distribution}/entry_points.txt", entry_points)
    for skill in manifest["skills"]:
        content = Path("src/rob2_kit/skills") / skill["name"] / "SKILL.md"
        raw = content.read_bytes()
        if mode == "tampered_skill" and skill["name"] == "rob2-workflow":
            raw += b"tampered"
        if mode == "crlf_skills":
            raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
        write(f"rob2_kit/skills/{skill['name']}/SKILL.md", raw)
    for filename, host in (("codex.json", "codex"), ("claude-code.json", "claude-code")):
        if mode == "missing_host" and filename == "claude-code.json":
            continue
        skills = [skill["name"] for skill in manifest["skills"]]
        if mode == "host_drift" and filename == "codex.json":
            skills.reverse()
        host_data: str = json.dumps(
            {
                "host": host,
                "mcp_command": "rob2-mcp",
                "skill_directory": "rob2_kit/skills",
                "skills": skills,
            }
        )
        if mode == "host_duplicate_top" and filename == "codex.json":
            host_data = host_data.removesuffix("}") + ', "host": "codex"}'
        if mode == "host_duplicate_nested" and filename == "codex.json":
            host_data = host_data.replace(
                '"skills": ["rob2-workflow", "rob2-signalling"]',
                '"skills": [{"name": "one", "name": "two"}]',
            )
        write(f"rob2_kit/hosts/{filename}", host_data)
    if mode != "zero_modules":
        modules = sorted(Path("src/rob2_kit").glob("**/*.py"))
        for module in modules:
            name = module.relative_to("src").as_posix()
            if mode == "missing_module" and name == "rob2_kit/__init__.py":
                continue
            raw = module.read_bytes()
            if mode == "tampered_module" and name == "rob2_kit/__init__.py":
                raw = raw.replace(b'__version__ = "0.1.0"', b'__version__ = "9.9.9"')
            if mode == "crlf_module" and name == "rob2_kit/__init__.py":
                raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
            write(name, raw)
    if mode == "extra_module":
        write("rob2_kit/unexpected.py", b"# unexpected\n")
    data_dir = f"{distribution.removesuffix('.dist-info')}.data"
    extra = {
        "purelib_extra": f"{data_dir}/purelib/rob2_kit/extra.py",
        "purelib_host": f"{data_dir}/purelib/rob2_kit/hosts/codex.json",
        "platlib_skill": f"{data_dir}/platlib/rob2_kit/skills/extra/SKILL.md",
        "data_overlay": f"{data_dir}/data/site-packages/rob2_kit/hosts/codex.json",
        "data_generic": f"{data_dir}/scripts/tool",
        "case_alias": "ROB2_KIT/alias.py",
        "case_host_alias": "ROB2_KIT/hosts/codex.json",
        "case_metadata_alias": f"{distribution.upper()}/METADATA",
        "traversal": "rob2_kit/../escape.py",
        "backslash": "rob2_kit\\ambiguous.py",
        "drive_absolute": "C:/outside.txt",
        "trailing_dot": "rob2_kit./extra.py",
        "trailing_space": "rob2_kit/hosts /codex.json",
        "ads_module": "rob2_kit/extra.py:stream",
        "ads_metadata": f"{distribution}/METADATA:stream",
        "reserved_device": "rob2_kit/CON/extra.py",
        "native_extension": "rob2_kit/extra.pyd",
        "shared_library": "rob2_kit/extra.so",
        "bytecode": "rob2_kit/extra.pyc",
        "path_file": "extra.pth",
        "arbitrary_file": "notes.txt",
    }
    if mode in extra:
        write(extra[mode], b"unsafe")
    if mode == "duplicate_member":
        write("rob2_kit/__init__.py", b"# duplicate\n")

    record_name = f"{distribution}/RECORD"
    if mode != "record_missing":
        record_rows = []
        for name, value in entries:
            digest = urlsafe_b64encode(sha256(value).digest()).rstrip(b"=").decode()
            record_rows.append(f"{name},sha256={digest},{len(value)}")
        record_rows.append(f"{record_name},,")
        if mode == "record_extra":
            record_rows.append("extra,sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,1")
        if mode == "record_duplicate":
            record_rows.append(record_rows[0])
        if mode == "record_bad_hash":
            record_rows[0] = record_rows[0].replace(
                "sha256=", "sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1
            )
        if mode == "record_bad_size":
            record_rows[0] = record_rows[0].rsplit(",", 1)[0] + ",999"
        if mode == "record_bad_self":
            record_rows[-1] = f"{record_name},sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,1"
        write(record_name, "\n".join(record_rows) + "\n")
    with zipfile.ZipFile(path, "w") as wheel:
        for name, value in entries:
            wheel.writestr(name, value)


def test_release_manifest_verifies_production_contract() -> None:
    _verifier().verify()


def test_text_hashes_are_line_ending_invariant(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier._sha256_text(b"one\ntwo\n") == verifier._sha256_text(b"one\r\ntwo\r\n")
    assert verifier._sha256_text(b"one\ntwo\n") == verifier._sha256_text(b"one\rtwo\r")
    with pytest.raises(UnicodeDecodeError):
        verifier._canonical_text_bytes(bytes([0xFF]))
    lf = tmp_path / "lf"
    crlf = tmp_path / "crlf"
    lf.mkdir()
    crlf.mkdir()
    (lf / "asset.txt").write_bytes(b"one\ntwo\n")
    (crlf / "asset.txt").write_bytes(b"one\r\ntwo\r\n")
    assert verifier._source_contract_hash(lf, ["asset.txt"]) == verifier._source_contract_hash(
        crlf, ["asset.txt"]
    )


def test_manifest_rejects_unexpected_nested_value(tmp_path: Path) -> None:
    verifier = _verifier()
    manifest = deepcopy(verifier._manifest())
    manifest["skills"][0]["unexpected"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected skill shape"):
        verifier._manifest(path)


def test_manifest_rejects_candidate_lineage_drift(tmp_path: Path) -> None:
    verifier = _verifier()
    manifest = deepcopy(verifier._manifest())
    manifest["candidate"]["implementation_commit"] = "0" * 40
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate contract differs"):
        verifier._manifest(path)


@pytest.mark.parametrize(
    "contents",
    [
        '{"schema_version": 1, "schema_version": 1}',
        '{"package": {"name": "rob2-kit", "name": "rob2-kit"}}',
    ],
)
def test_manifest_rejects_duplicate_keys_at_every_depth(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _verifier()._manifest(path)


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
    "mode",
    [
        "entry_point_redirect",
        "entry_point_missing",
        "entry_point_uppercase",
        "entry_point_colon",
        "entry_point_cr",
        "entry_point_unicode",
        "wheel_tag",
        "wheel_purelib",
        "wheel_version",
        "wheel_duplicate",
        "wheel_generator",
        "wheel_missing_header",
        "wheel_unexpected_header",
        "wheel_appended_body",
        "wheel_leading_envelope",
        "wheel_crlf",
        "metadata_version",
        "metadata_missing_version",
        "metadata_duplicate_version",
        "metadata_unexpected",
        "metadata_leading_envelope",
        "metadata_malformed_pre_body_line",
        "metadata_appended_undeclared_bytes",
        "metadata_header_order",
        "python_drift",
        "python_missing",
        "python_duplicate",
        "duplicate_name",
        "duplicate_version",
        "duplicate_dependency",
        "record_missing",
        "record_extra",
        "record_duplicate",
        "record_bad_hash",
        "record_bad_size",
        "record_bad_self",
    ],
)
def test_wheel_contract_rejects_metadata_and_record_drift(tmp_path: Path, mode: WheelMode) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, mode)

    with pytest.raises(ValueError, match="wheel"):
        verifier._verify_wheel(wheel, manifest)


@pytest.mark.parametrize(
    "mode", ["missing_module", "extra_module", "tampered_module", "zero_modules"]
)
def test_wheel_contract_rejects_module_payload_drift(tmp_path: Path, mode: WheelMode) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, mode)

    with pytest.raises(ValueError, match="wheel (member set|Python module canonical)"):
        verifier._verify_wheel(wheel, manifest)


def test_wheel_contract_accepts_canonicalized_module_line_endings(tmp_path: Path) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, "crlf_module")

    verifier._verify_wheel(wheel, manifest)


@pytest.mark.parametrize(
    "mode",
    [
        "purelib_extra",
        "purelib_host",
        "platlib_skill",
        "data_overlay",
        "data_generic",
        "case_alias",
        "case_host_alias",
        "case_metadata_alias",
        "duplicate_member",
        "traversal",
        "backslash",
        "drive_absolute",
        "trailing_dot",
        "trailing_space",
        "ads_module",
        "ads_metadata",
        "reserved_device",
    ],
)
def test_wheel_contract_rejects_ambiguous_or_installable_module_aliases(
    tmp_path: Path, mode: WheelMode
) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, mode)

    with pytest.raises(ValueError, match="wheel"):
        verifier._verify_wheel(wheel, manifest)


@pytest.mark.parametrize(
    "mode", ["native_extension", "shared_library", "bytecode", "path_file", "arbitrary_file"]
)
def test_wheel_contract_rejects_every_unlisted_member(tmp_path: Path, mode: WheelMode) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, mode)

    with pytest.raises(ValueError, match="wheel member set differs"):
        verifier._verify_wheel(wheel, manifest)


def test_wheel_contract_accepts_crlf_skill_assets(tmp_path: Path) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, "crlf_skills")
    verifier._verify_wheel(wheel, manifest)


def test_wheel_contract_accepts_crlf_entry_points(tmp_path: Path) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, "entry_point_crlf")
    verifier._verify_wheel(wheel, manifest)


@pytest.mark.parametrize(
    "mode",
    [
        "tampered_skill",
        "missing_host",
        "extra_dependency",
        "host_drift",
        "host_duplicate_top",
        "host_duplicate_nested",
    ],
)
def test_wheel_asset_and_dependency_tampering_is_rejected(tmp_path: Path, mode: WheelMode) -> None:
    verifier = _verifier()
    wheel = tmp_path / "candidate.whl"
    manifest = verifier._manifest()
    _wheel(wheel, manifest, mode)
    with pytest.raises(ValueError):
        verifier._verify_wheel(wheel, manifest)
