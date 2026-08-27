from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


def _module():
    spec = importlib.util.spec_from_file_location(
        "qualification_manifest", Path("scripts/qualification_manifest.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _manifest() -> dict[str, object]:
    input_hash = _hash("input")
    runs = [
        {
            "id": f"haiku-{index}",
            "role": "claude_haiku",
            "host": "claude-code",
            "model": "haiku",
            "effort": "medium",
            "input_sha256": input_hash,
            "bundle_identity": _hash(f"identity-{index}"),
            "bundle_sha256": _hash(f"bundle-{index}"),
            "verifier": "passed",
            "dispositions": {"trial": "assessed"},
            "outcome": ["outcome_a", "outcome_b", "outcome_c"][index],
        }
        for index in range(3)
    ]
    runs += [
        {
            "id": "codex",
            "role": "codex_canary",
            "host": "codex",
            "model": "gpt-5",
            "effort": "medium",
            "input_sha256": input_hash,
            "bundle_identity": _hash("codex"),
            "bundle_sha256": _hash("bundle-codex"),
            "verifier": "passed",
            "dispositions": {"canary": "needs_input"},
            "outcome": "canary",
        },
    ]
    return {
        "schema": "rob2-kit.retained-evidence.v0.3",
        "commit": "a" * 40,
        "wheel_sha256": _hash("wheel"),
        "inputs": [{"identity": "trial-set", "sha256": input_hash}],
        "outcomes": ["outcome_a", "outcome_b", "outcome_c"],
        "runs": runs,
        "restart_proof": {
            "run_id": "haiku-1",
            "before_proposal_review_identity": _hash("proposal-review"),
            "after_proposal_review_identity": _hash("proposal-review"),
            "before_batch_identity": _hash("batch"),
            "after_batch_identity": _hash("batch"),
            "before_source_set_identity": _hash("sources"),
            "after_source_set_identity": _hash("sources"),
            "passed": True,
        },
        "ci": [
            {"os": os_name, "python": python, "passed": True}
            for os_name in ("ubuntu-latest", "windows-latest", "macos-latest")
            for python in ("3.11", "3.12", "3.13")
        ],
        "verdict": "all_green",
    }


def test_qualification_generate_and_validate_cli(tmp_path: Path) -> None:
    source, output = tmp_path / "run.json", tmp_path / "retained.json"
    source.write_text(json.dumps(_manifest()), encoding="utf-8")
    generated = subprocess.run(
        [sys.executable, "scripts/qualification_manifest.py", "generate", str(source), str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    checked = subprocess.run(
        [sys.executable, "scripts/qualification_manifest.py", "validate", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    assert str(source) not in output.read_text(encoding="utf-8")


def test_restart_proof_requires_pre_ack_identity_equality(tmp_path: Path) -> None:
    manifest = _manifest()
    restart = manifest["restart_proof"]
    assert isinstance(restart, dict)
    restart["after_batch_identity"] = _hash("different-batch")
    source = tmp_path / "restart-self.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    assert any(
        "Proposal, Batch, and Source identities must be equal" in error
        for error in _module().validate(manifest)
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"runs": value["runs"][1:]}),
        lambda value: value["runs"].__setitem__(1, {**value["runs"][1], "id": "haiku-0"}),
        lambda value: value["runs"].__setitem__(0, {**value["runs"][0], "model": "sonnet"}),
        lambda value: value.update({"runs": value["runs"][:-1]}),
        lambda value: value["restart_proof"].update({"passed": False}),
        lambda value: value["restart_proof"].update({"run_id": "codex"}),
        lambda value: value["restart_proof"].update(
            {"after_source_set_identity": _hash("different")}
        ),
        lambda value: value.update({"ci": value["ci"][:-1]}),
        lambda value: value["runs"][0].update({"input_sha256": _hash("unknown")}),
        lambda value: value["runs"][1].update(
            {"bundle_identity": value["runs"][0]["bundle_identity"]}
        ),
        lambda value: value["runs"][0].update({"bundle_sha256": "bad"}),
        lambda value: value["runs"][0].update({"verifier": "failed"}),
        lambda value: value["runs"][0].update({"dispositions": {}}),
        lambda value: value["runs"][0].update({"path": "private/file"}),
        lambda value: value["runs"][0].update({"effort": "private/file"}),
    ],
)
def test_qualification_rejects_inconsistent_or_private_evidence(mutate) -> None:
    manifest = deepcopy(_manifest())
    mutate(manifest)
    assert _module().validate(manifest)
