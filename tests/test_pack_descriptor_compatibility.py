"""Keep independent descriptor pins synchronized without relaxing bundle checks."""

from __future__ import annotations

import copy
import hashlib
import runpy
from pathlib import Path

from support.rob2 import _rehashed_full_tamper

from rob2_kit.application.finalization import (
    _scientific_contract_descriptor,
    _valid_scientific_contract_descriptor,
    verify_bundle,
)

_REPO = Path(__file__).resolve().parents[1]
_STANDALONE = runpy.run_path(str(_REPO / "scripts" / "verify_bundle.py"))
_ALLSOP = (
    _REPO
    / "docs/archive/evaluation/2026-10-03-allsop-completion-544a523"
    / "ae8d89700e5915ce9d93e4be472bc78f8165d4f3dfaeee3e92c8e3e47a6565e8.rob2.zip"
)


def test_current_descriptor_pin_and_recognized_history_match_installed_pack() -> None:
    assert _STANDALONE["_CONDITIONAL_SCIENTIFIC_PACK"] == _scientific_contract_descriptor()
    for descriptor in _STANDALONE.values():
        if isinstance(descriptor, dict) and descriptor.get("id") == "rob2.parallel.assignment":
            assert _valid_scientific_contract_descriptor(descriptor), descriptor
            altered = copy.deepcopy(descriptor)
            altered["official_source"]["source_sha256"] = "0" * 64
            assert not _valid_scientific_contract_descriptor(altered)


def test_untouched_completion_bundle_passes_both_verifiers() -> None:
    before = hashlib.sha256(_ALLSOP.read_bytes()).hexdigest()
    assert before == "845b43ae089382cfd53c3f32dd492c5222752ce60e4cd1ddf880cb4427a0c6d6"
    assert verify_bundle(_ALLSOP)
    assert _STANDALONE["verify"](_ALLSOP) == (True, "bundle verified")
    assert hashlib.sha256(_ALLSOP.read_bytes()).hexdigest() == before


def test_prior_guidance_descriptor_remains_verifiable() -> None:
    historical = _REPO / "tests/fixtures/bundles/allsop-2014-result-semantics-v0.8.rob2.zip"
    assert verify_bundle(historical)
    assert _STANDALONE["verify"](historical) == (True, "bundle verified")


def test_rehashed_altered_descriptors_fail_both_verifiers(tmp_path: Path) -> None:
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
            _ALLSOP,
            tampered,
            lambda canonical, change=change: canonical["scientific_pack"].update(change),
        )
        assert not verify_bundle(tampered)
        assert _STANDALONE["verify"](tampered) == (False, "scientific pack descriptor differs")
