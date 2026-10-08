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
from rob2_kit.application.evidence import _result_value_contains
from rob2_kit.application.finalization import (
    _reported_result_has_coherent_anchor,
    _valid_result_shape,
    verify_bundle,
)
from rob2_kit.application.proposal import _coherent_anchor_indices, _source_bound_leaves
from rob2_kit.packs import SCIENTIFIC_PACK
from tests.test_result_scope_review import _allsop_result


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


@pytest.mark.parametrize(
    "source_statistic, claimed_statistic",
    [("p = 0.68", "p = 0.12"), ("p = 0.689", "p = 0.68")],
)
def test_ancillary_statistic_requires_source_support_for_selected_result(
    tmp_path: Path, source_statistic: str, claimed_statistic: str
) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "input/trial/main.txt"
    source.write_text(
        source.read_text().rstrip() + "; " + source_statistic + ".\n", encoding="utf-8"
    )
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["reported_statistics"] = [claimed_statistic]
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


@pytest.mark.parametrize(
    "source_statistic, claim, expected",
    [
        ("p = 0.68", "p = 0.68", True),
        ("p = 0.689", "p = 0.68", False),
        ("p < 0.01", "p < 0.01", True),
        ("p < 0.010", "p < 0.01", False),
        ("p < 0.01", "p = 0.01", False),
        ("p < 0.01", "0.01", False),
        ("z = -1.2", "z = -1.2", True),
        ("z = -1.23", "z = -1.2", False),
        ("z = +1.2", "z = +1.2", True),
        ("p = 6.8e-3", "p = 6.8e-3", True),
        ("p = 6.8e-30", "p = 6.8e-3", False),
        ("p = 0.68e-3", "p = 0.68", False),
        ("not estimable", "not estimable", True),
    ],
)
def test_statistics_use_numeric_boundaries_in_binding_and_all_anchors(
    source_statistic: str, claim: str, expected: bool
) -> None:
    standalone = runpy.run_path("scripts/verify_bundle.py")
    path = "/reported/reported_statistics/0"
    for matcher in (_result_value_contains, standalone["_result_value_contains"]):
        assert matcher(source_statistic, claim, path) is expected
        # An unrelated textual field keeps its historical matching behavior.
        assert matcher("Endpoint 20", "Endpoint 2", "/reported/endpoint/name")

    result = _allsop_result()
    result["reported"]["reported_statistics"] = [claim]
    evidence: list[dict[str, object]] = [{"kind": "narrative", "handle": "eh_statistic"}]
    result["evidence"] = evidence
    source_reported = copy.deepcopy(result["reported"])
    source_reported["reported_statistics"] = [source_statistic]
    quote = "; ".join(_source_bound_leaves(source_reported, "/reported").values())
    selected: dict[str, object] = {
        "handle": "eh_statistic",
        "trial_id": result["trial_id"],
        "quote": quote,
    }
    assert bool(_coherent_anchor_indices(result, {"selection": selected})) is expected
    for checker in (
        _reported_result_has_coherent_anchor,
        standalone["_reported_result_has_coherent_anchor"],
    ):
        assert checker(result, evidence, {"eh_statistic": selected}) is expected
