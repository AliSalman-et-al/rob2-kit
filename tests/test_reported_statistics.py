from __future__ import annotations

import copy
import json
import runpy
import zipfile
from pathlib import Path

import pytest
from support.rob2 import (
    _call,
    _domain_draft,
    _finalize_assessment,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _standalone_verify,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.finalization import _valid_result_shape, verify_bundle
from rob2_kit.packs import SCIENTIFIC_PACK


@pytest.mark.parametrize("comparative", [False, True])
def test_statistics_bind_and_recover_with_either_reported_form(
    tmp_path: Path, comparative: bool
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "input/trial/main.txt"
    source.write_text(source.read_text().rstrip() + "; p = 0.68.\n", encoding="utf-8")
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["reported_statistics"] = ["p = 0.68"]
    if comparative:
        result["reported"].update(
            form="comparative_effect", effect_measure="risk ratio", estimate="1", precision=None
        )
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    stored = _state(workspace)["proposal"]["payload"]["results"][0]
    assert stored["reported"]["reported_statistics"] == ["p = 0.68"]
    if not comparative:
        assert not {"effect_measure", "estimate", "precision"} & stored["reported"].keys()
    assert any(
        binding["field"]["path"] == "/reported/reported_statistics/0"
        for binding in stored["bindings"]
    )
    status = _call(workspace, "get_status", {})
    review = status["data"]["scope_review"][0]
    assert review["reported_statistics"] == ["p = 0.68"]
    assert len(review["reported_group_values"]) == 2
    assert review["reported_estimate"] == ("1" if comparative else None)
    standalone_shape = runpy.run_path("scripts/verify_bundle.py")["_valid_result_shape"]
    for validator in (_valid_result_shape, standalone_shape):
        assert validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.11")
        assert not validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.10")

    if comparative:
        return
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        committed = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert committed["outcome"] == "success", committed
        revision = int(committed["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0
    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        assert b"reported_statistics" in archive.read("report.html")
    assert canonical["scientific_pack"]["result_semantics_version"] == (
        "rob2-kit.result-semantics.v0.11"
    )
    assert canonical["proposal"]["payload"]["results"][0]["reported"] == stored["reported"]


def test_ancillary_statistic_requires_source_support_for_selected_result(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "input/trial/main.txt"
    source.write_text(source.read_text().rstrip() + "; p = 0.68.\n", encoding="utf-8")
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["reported_statistics"] = ["p = 0.12"]
    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert repair["outcome"] == "repair", repair
    assert any(item["path"].startswith("/results/0/reported") for item in repair["repairs"])


def test_absent_statistics_preserve_existing_canonical_record_shape(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    original = copy.deepcopy(result)
    result["reported"]["reported_statistics"] = []
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    stored = _state(workspace)["proposal"]["payload"]["results"][0]
    assert "reported_statistics" not in stored["reported"]
    assert stored["reported"]["group_values"] == original["reported"]["group_values"]
