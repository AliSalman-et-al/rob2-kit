from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from rob2_kit.application import domains
from rob2_kit.interfaces.mcp.contracts import (
    RegistryOutcomeNavigation,
)


def _verifier():
    path = Path("scripts/verify_bundle.py").resolve()
    spec = importlib.util.spec_from_file_location("verify_bundle_regressions", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(applicability: object = None, *, include_applicability: bool = True) -> dict:
    result = {
        "kind": "assessable",
        "trial_id": "trial",
        "requested_outcome": "mortality",
        "relation": "broader",
        "relation_rationale": "The reported endpoint is broader than the requested outcome.",
        "target": {
            "outcome_definition": "mortality",
            "measurement": {"metric": "mortality", "method": "ascertainment"},
            "time_point_or_window": {"kind": "described", "description": "follow-up"},
            "effect_of_interest": "assignment",
            "comparison_groups": [
                {"id": "a", "assignment": "intervention"},
                {"id": "b", "assignment": "control"},
            ],
            "intended_analysis_population": "randomized participants",
            "intended_effect_measure": "risk ratio",
        },
        "reported": {
            "form": "group_bound_values",
            "analysis_population": "analyzed participants",
            "endpoint": {"name": "all-cause mortality", "definition": "death"},
            "values": [
                {"group_id": "a", "statistic": "risk", "value": "1", "unit": "%"},
                {"group_id": "b", "statistic": "risk", "value": "2", "unit": "%"},
            ],
        },
        "clarity": {
            key: "specified"
            for key in (
                "outcome_definition",
                "measurement",
                "time_point",
                "analysis_population",
                "comparison_groups",
                "effect_measure",
                "source_table_meaning",
                "eligible_result_choice",
            )
        },
        "evidence": [],
        "bindings": [],
    }
    if include_applicability:
        result["applicability"] = applicability
    return result


def test_v06_verifier_requires_nonnull_applicability_and_source_basis() -> None:
    verifier = _verifier()
    version = "rob2-kit.result-semantics.v0.6"
    assert not verifier._valid_result_shape(
        _result(include_applicability=False), "mortality", version
    )
    assert not verifier._valid_result_shape(_result(None), "mortality", version)
    assert not verifier._valid_result_shape(
        _result(
            {
                "design": "individual_parallel",
                "status": "supported",
                "rationale": "The allocation was individual and parallel.",
                "evidence": [],
            }
        ),
        "mortality",
        version,
    )
    assert verifier._valid_result_shape(
        _result(
            {
                "design": "individual_parallel",
                "status": "supported",
                "rationale": "The allocation was individual and parallel.",
                "evidence": ["eh_0000000000000000"],
            }
        ),
        "mortality",
        version,
    )


def test_oversized_registry_metadata_keeps_complete_source_recovery(tmp_path: Path) -> None:
    import json

    from rob2_kit.application._state import _json_pages
    from rob2_kit.interfaces.mcp.server import _paginate_domain_context_transport

    internal = tmp_path / ".rob2-kit"
    internal.mkdir()
    source_id = "sh_" + "b" * 16
    study = {
        "protocolSection": {"identificationModule": {"nctId": "NCT00000001"}},
        "resultsSection": {
            "outcomeMeasuresModule": {
                "outcomeMeasures": [
                    {"title": "Change in score", "populationDescription": "x" * 140_000}
                ]
            }
        },
    }
    (text,) = _json_pages(Path("registry.json"), json.dumps(study).encode())
    with sqlite3.connect(internal / "derivative.sqlite3") as connection:
        connection.execute("CREATE TABLE pages (page INTEGER, text TEXT, source_id TEXT)")
        connection.execute("INSERT INTO pages VALUES (1, ?, ?)", (text, source_id))
    navigation = domains._registry_navigation(
        tmp_path, "trial", [{"id": source_id, "role": "registry"}]
    )[source_id]
    entry = RegistryOutcomeNavigation.model_validate(navigation["outcomes"][0])
    assert entry.title == "Change in score"
    assert entry.populationDescription is None
    assert entry.not_inlined_fields == ("populationDescription",)
    window = entry.recovery.windows[0]
    covered = "".join(text.splitlines()[window.start_line - 1 : window.end_line])
    assert "x" * 140_000 in covered
    value = {
        "outcome": "success",
        "head": {"phase": "assessment", "state_revision": 4},
        "data": {
            "trial_id": "trial",
            "domain_id": "domain:missing",
            "registry_outcomes": [entry.model_dump(mode="json")],
        },
    }
    response = _paginate_domain_context_transport(value, None, None, "sha256:" + "a" * 64, 4)
    assert response["data"]["registry_outcomes"] == value["data"]["registry_outcomes"]


def test_preview_basis_must_be_explicit_and_same_trial() -> None:
    catalog = {
        "sha256:" + "a" * 64: {
            "identity": "sha256:" + "a" * 64,
            "handle": "eh_0000000000000000",
            "trial_id": "trial",
        },
        "sha256:" + "b" * 64: {
            "identity": "sha256:" + "b" * 64,
            "handle": "eh_1111111111111111",
            "trial_id": "other",
        },
    }
    row = {
        "arm": "A",
        "population": "randomized",
        "unit": "participants",
        "time_point": "follow-up",
        "randomized": 10,
        "observed": 8,
        "basis": ["eh_0000000000000000"],
    }
    result_identity = "sha256:" + "c" * 64
    preview = domains._canonical_preview_rows([row], catalog, "trial", result_identity)[0]
    assert preview["basis"] == ["sha256:" + "a" * 64]
    assert preview["result_identity"] == result_identity
    with pytest.raises(ValueError, match="requires Evidence basis"):
        domains._canonical_preview_rows([{**row, "basis": []}], catalog, "trial", result_identity)
    with pytest.raises(ValueError, match="unknown or cross-Trial"):
        domains._canonical_preview_rows(
            [{**row, "basis": ["eh_1111111111111111"]}], catalog, "trial", result_identity
        )
    with pytest.raises(ValueError, match="another approved Result"):
        domains._canonical_preview_rows(
            [{**row, "result_identity": "sha256:" + "d" * 64}],
            catalog,
            "trial",
            result_identity,
        )
