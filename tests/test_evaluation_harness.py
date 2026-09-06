from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from rob2_kit.evaluation import evaluate_fixture, validate_split_isolation


def fixture() -> dict[str, Any]:
    return json.loads(Path("eval/synthetic-heldout.json").read_text())


def test_strict_fixture_is_deterministic_and_safe() -> None:
    value = fixture()
    first, second = evaluate_fixture(value), evaluate_fixture(value)
    assert first == second
    assert first["coverage"]["premise_complete"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert first["coverage"]["stages"]["content_delivered"]["unknown"] == 1
    assert set(first["coverage"]["stages"]) == {
        "projection_available",
        "candidate_ranked",
        "passage_surfaced",
        "content_delivered",
        "passage_inspected",
        "evidence_cited",
        "premise_assessed",
        "answer_committed",
    }
    assert first["friction"]["context_bytes"] == 1
    serialized = json.dumps(first)
    for forbidden in ("query_hash", "holdout", "adjudicat", "reviewer", "coordinates"):
        assert forbidden not in serialized


@pytest.mark.parametrize("kind", ["extra", "draw", "event"])
def test_closed_schema_and_types_fail(kind: str) -> None:
    value = fixture()
    if kind == "extra":
        value["extra"] = True
    elif kind == "draw":
        value["attempts"][0]["draw"] = 1
    else:
        value["events"][0]["type"] = "unknown"
    with pytest.raises(ValueError):
        evaluate_fixture(value)


def test_alternative_sets_disputed_and_query_no_progress() -> None:
    value = fixture()
    value["references"].append(
        {**value["references"][0], "premise_id": "disputed", "status": "disputed"}
    )
    value["queries"].append(
        {
            **value["queries"][0],
            "query_hash": "sha256:" + "6" * 64,
            "result_ids": ["e1"],
            "stop": "no_new_identity",
        }
    )
    result = evaluate_fixture(value)
    assert result["coverage"]["premise_complete"]["denominator"] == 1
    assert result["queries"]["no_progress"] == 1


def test_paired_intervention_delta_uses_only_matched_cells() -> None:
    value = fixture()
    value["manifest"]["interventions"]["variant"] = "sha256:" + "7" * 64
    value["manifest"]["attempt_ids"].append("variant")
    value["references"].append({**value["references"][0], "intervention_id": "variant"})
    value["events"].extend(
        {**event, "intervention_id": "variant", "attempt_id": "variant"}
        for event in list(value["events"])
    )
    value["attempts"].append(
        {
            **value["attempts"][0],
            "attempt_id": "variant",
            "intervention_id": "variant",
            "prediction": "some_concerns",
        }
    )
    paired = evaluate_fixture(value)["paired_interventions"]["variant"]
    assert paired["matched_trial_cells"] == 1
    assert paired["accuracy_delta"] == {"numerator": -1, "denominator": 1, "rate": -1.0}


def test_missing_stage_is_rejected_but_unknown_is_valid() -> None:
    value = fixture()
    value["events"] = [event for event in value["events"] if event["type"] != "answer_committed"]
    with pytest.raises(ValueError, match="missing required event stages"):
        evaluate_fixture(value)


def test_ranked_passage_is_not_mistaken_for_supported_premise() -> None:
    value = fixture()
    premise = next(event for event in value["events"] if event["type"] == "premise_assessed")
    premise["support"] = "unsupported"

    result = evaluate_fixture(value)

    assert result["coverage"]["passage_alternative_complete"]["rate"] == 1.0
    assert result["coverage"]["premise_complete"]["rate"] == 0.0
    assert result["coverage"]["unsupported_premise"]["rate"] == 1.0
    support = result["coverage"]["premise_support_confusion"]
    assert support["confusion"] == {
        "full": {"full": 0, "unsupported": 1},
        "unsupported": {"full": 0, "unsupported": 0},
    }


def test_contradiction_requires_citation_and_premise_handling() -> None:
    value = fixture()
    value["references"][0]["contradiction_ids"] = ["e2"]
    value["references"][0]["restricted"]["support_label"] = "conflicted"
    premise = next(event for event in value["events"] if event["type"] == "premise_assessed")
    premise["support"] = "conflicted"
    handled = evaluate_fixture(value)["coverage"]["contradiction_handled"]
    assert handled == {"numerator": 1, "denominator": 1, "rate": 1.0}

    cited = next(event for event in value["events"] if event["type"] == "evidence_cited")
    cited["observed"] = False
    missed = evaluate_fixture(value)["coverage"]["contradiction_handled"]
    assert missed == {"numerator": 0, "denominator": 1, "rate": 0.0}


def test_attempt_selection_rule_is_enforced_not_trusted() -> None:
    value = fixture()
    value["attempts"].append({**value["attempts"][0], "attempt_id": "b", "selected": False})
    value["manifest"]["attempt_ids"].append("b")
    assert evaluate_fixture(value)["audit"]["attempt_count"] == 2

    value["attempts"][0]["selected"] = False
    value["attempts"][1]["selected"] = True
    with pytest.raises(ValueError, match="lowest final attempt_id"):
        evaluate_fixture(value)


def test_exact_vector_uses_one_domain_judgment_per_domain() -> None:
    value = fixture()
    reference = value["references"][0]
    attempt = value["attempts"][0]
    events = list(value["events"])
    value["references"] = []
    value["attempts"] = []
    value["events"] = []
    value["queries"] = []
    value["manifest"]["attempt_ids"] = []
    domain_ids = (
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    )
    for index, domain_id in enumerate(domain_ids, 1):
        attempt_id = f"a{index}"
        value["references"].append({**reference, "domain_id": domain_id, "question_id": "overall"})
        value["attempts"].append(
            {
                **attempt,
                "domain_id": domain_id,
                "question_id": "overall",
                "attempt_id": attempt_id,
            }
        )
        value["events"].extend(
            {
                **event,
                "domain_id": domain_id,
                "question_id": "overall",
                "attempt_id": attempt_id,
            }
            for event in events
        )
        value["manifest"]["attempt_ids"].append(attempt_id)

    result = evaluate_fixture(value)
    assert result["scientific"]["exact_vector"]["agreement"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert set(result["scientific"]["domains"]) == set(domain_ids)
    assert all(
        set(metrics) == {"accuracy", "balanced_accuracy", "confusion"}
        for metrics in result["scientific"]["domains"].values()
    )
    assert not any(
        "attempt_id" in metrics or "label" in metrics
        for metrics in result["scientific"]["domains"].values()
    )

    value["attempts"][-1]["prediction"] = "high"
    assert evaluate_fixture(value)["scientific"]["exact_vector"]["agreement"]["numerator"] == 0


def test_reliability_groups_repeated_draws_not_domains() -> None:
    value = fixture()
    reference = value["references"][0]
    attempt = value["attempts"][0]
    events = list(value["events"])
    value["references"].append({**reference, "run_id": "run-2", "draw": "2"})
    value["attempts"].append(
        {
            **attempt,
            "run_id": "run-2",
            "draw": "2",
            "attempt_id": "b",
            "prediction": "high",
        }
    )
    value["events"].extend(
        {**event, "run_id": "run-2", "draw": "2", "attempt_id": "b"} for event in events
    )
    value["manifest"]["attempt_ids"].append("b")

    reliability = evaluate_fixture(value)["reliability"]
    assert reliability["any_correct"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert reliability["all_correct"] == {"numerator": 0, "denominator": 1, "rate": 0.0}
    assert reliability["draws_per_cell"] == {2: 1}


def test_split_leak_fails_for_every_fingerprint_kind() -> None:
    for field in ("source_fingerprints", "projection_fingerprints", "document_family_fingerprints"):
        manifest = deepcopy(fixture()["manifest"])
        manifest["splits"].append(
            {
                "trial_id": "development",
                "split": "development",
                "source_fingerprints": [],
                "projection_fingerprints": [],
                "document_family_fingerprints": [],
            }
        )
        manifest["splits"][-1][field] = manifest["splits"][0][field]
        with pytest.raises(ValueError, match="crosses"):
            validate_split_isolation(manifest)


def test_duplicate_selected_and_restricted_input_are_not_silently_accepted() -> None:
    value = fixture()
    value["references"][0]["restricted"] = {
        "answer_label": "low",
        "reviewer_id": "restricted",
        "coordinates": [1, 2],
        "rationale": "private",
    }
    assert "restricted" not in json.dumps(evaluate_fixture(value))
    value = fixture()
    duplicate = {**value["attempts"][0], "attempt_id": "b"}
    value["attempts"].append(duplicate)
    value["manifest"]["attempt_ids"].append("b")
    with pytest.raises(ValueError, match="selection rule"):
        evaluate_fixture(value)


def test_reference_truth_is_independent_of_attempts() -> None:
    value = fixture()
    value["attempts"][0]["prediction"] = "high"
    value["attempts"].append(
        {**value["attempts"][0], "attempt_id": "b", "selected": False, "prediction": "low"}
    )
    value["manifest"]["attempt_ids"].append("b")

    result = evaluate_fixture(value)

    assert result["scientific"]["questions"]["q"]["accuracy"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0.0,
    }
    value["attempts"][0]["label"] = "high"
    with pytest.raises(ValueError, match="unclosed field"):
        evaluate_fixture(value)


def test_nonselected_attempt_trajectory_cannot_credit_selected_attempt() -> None:
    value = fixture()
    value["attempts"].append({**value["attempts"][0], "attempt_id": "b", "selected": False})
    value["manifest"]["attempt_ids"].append("b")
    for event in value["events"]:
        if event["type"] == "evidence_cited":
            event["observed"] = False
    value["events"].extend(
        {**event, "attempt_id": "b", "observed": True} for event in list(value["events"])
    )
    value["queries"][0]["result_ids"] = []
    value["queries"][0]["source_ids"] = []
    value["queries"].append(
        {
            **value["queries"][0],
            "attempt_id": "b",
            "query_hash": "sha256:" + "9" * 64,
            "result_ids": ["nonselected-result"],
            "source_ids": ["nonselected-source"],
        }
    )

    result = evaluate_fixture(value)

    assert result["coverage"]["passage_alternative_complete"]["numerator"] == 0
    assert result["queries"]["result_novel"] == 0
    assert result["queries"]["source_novel"] == 0


def test_optional_premise_does_not_change_required_premise_denominator() -> None:
    value = fixture()
    value["references"].append(
        {
            **value["references"][0],
            "premise_id": "optional",
            "required": False,
            "acceptable_evidence_sets": [["never-seen"]],
        }
    )

    result = evaluate_fixture(value)

    assert result["coverage"]["premise_complete"]["denominator"] == 1
    assert result["coverage"]["passage_alternative_complete"]["denominator"] == 1


def test_split_rows_are_closed_and_dimensions_are_manifest_bound() -> None:
    value = fixture()
    value["manifest"]["splits"][0]["source_text"] = "private"
    with pytest.raises(ValueError, match="split has an unclosed field set"):
        evaluate_fixture(value)

    value = fixture()
    value["attempts"][0]["model_version"] = "unfrozen"
    with pytest.raises(ValueError, match="frozen manifest"):
        evaluate_fixture(value)


def test_event_and_query_attempt_bindings_must_match_their_cells() -> None:
    for collection in ("events", "queries"):
        value = fixture()
        value[collection][0]["attempt_id"] = "missing"
        with pytest.raises(ValueError, match="invalid"):
            evaluate_fixture(value)
