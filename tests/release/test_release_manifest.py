from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest


def _verifier():
    spec = importlib.util.spec_from_file_location("release_verify", "docs/release/verify.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_contract_verifies_local_public_surface() -> None:
    _verifier().verify()


def test_contract_rejects_catalog_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = _verifier()
    contract = deepcopy(verifier._load_contract())
    contract["tools"].pop()
    path = tmp_path / "public-contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    monkeypatch.setattr(verifier, "CONTRACT", path)
    with pytest.raises(ValueError, match="tool order"):
        verifier._load_contract()


def test_wheel_archive_rejects_wrong_entry_point(tmp_path: Path) -> None:
    wheel = tmp_path / "bad.whl"
    import zipfile

    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "rob2_kit-0.2.0.dist-info/entry_points.txt", "[console_scripts]\nrob2-mcp = bad:main\n"
        )
    with pytest.raises(ValueError, match="entry point"):
        _verifier()._verify_wheel_archive(wheel)
