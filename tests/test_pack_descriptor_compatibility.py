"""Keep independent descriptor pins synchronized without relaxing bundle checks."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

from support.rob2 import _assessed_artifact, _rehashed_full_tamper, _workspace

from rob2_kit.application.finalization import (
    _scientific_contract_descriptor,
    _valid_scientific_contract_descriptor,
    verify_bundle,
)

_REPO = Path(__file__).resolve().parents[1]
_STANDALONE = runpy.run_path(str(_REPO / "scripts" / "verify_bundle.py"))


def test_current_descriptor_pin_and_recognized_history_match_installed_pack() -> None:
    assert _STANDALONE["_REPORTED_STATISTICS_SCIENTIFIC_PACK"] == _scientific_contract_descriptor()
    for descriptor in _STANDALONE.values():
        if isinstance(descriptor, dict) and descriptor.get("id") == "rob2.parallel.assignment":
            assert _valid_scientific_contract_descriptor(descriptor), descriptor
            altered = copy.deepcopy(descriptor)
            altered["official_source"]["source_sha256"] = "0" * 64
            assert not _valid_scientific_contract_descriptor(altered)


def test_rehashed_altered_descriptors_fail_both_verifiers(tmp_path: Path) -> None:
    artifact = _assessed_artifact(_workspace(tmp_path))
    changes = (
        {"content_hash": "sha256:" + "0" * 64},
        {"version": "2019.2"},
        {"result_semantics_version": "rob2-kit.result-semantics.v100"},
        {"official_source": {"version": "22 August 2019", "source_sha256": "0" * 64}},
        {"unreviewed_field": True},
    )
    for index, change in enumerate(changes):
        tampered = tmp_path / f"descriptor-{index}.rob2.zip"
        _rehashed_full_tamper(
            artifact,
            tampered,
            lambda canonical, change=change: canonical["scientific_pack"].update(change),
        )
        assert not verify_bundle(tampered)
        assert _STANDALONE["verify"](tampered) == (False, "scientific pack descriptor differs")
