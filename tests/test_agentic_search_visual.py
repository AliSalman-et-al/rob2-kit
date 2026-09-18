from __future__ import annotations

from rob2_kit.application._state import _identity
from rob2_kit.application.finalization import _verify_result_evidence
from rob2_kit.application.proposal import _bind_result


def _visual_case() -> tuple[
    dict[str, object], dict[str, dict[str, object]], dict[str, dict[str, object]]
]:
    source = {
        "id": "source-1",
        "trial_id": "trial-1",
        "sha256": "sha256:" + "1" * 64,
        "page_count": 1,
    }
    render = {
        "identity": _identity(
            {
                "source_id": source["id"],
                "source_sha256": source["sha256"],
                "page": 1,
                "recipe": "page-1",
            }
        ),
        "source_id": source["id"],
        "page": 1,
        "png_sha256": "sha256:" + "2" * 64,
        "recipe": "page-1",
    }
    transcription = (
        "death ascertainment; randomized population; assigned to intervention; "
        "assigned to control; end of follow-up; requested outcome; risk ratio; "
        "risk; 1; events; 2."
    )
    selected = {
        "kind": "figure",
        "trial_id": source["trial_id"],
        "source_id": source["id"],
        "render": render,
        "transcription": transcription,
        "region": [0.1, 0.2, 0.9, 0.8],
        "provenance": "host_visual",
    }
    selected["delivery_receipt"] = _identity(
        {
            "trial_id": source["trial_id"],
            "source_id": source["id"],
            "render_identity": render["identity"],
            "png_sha256": render["png_sha256"],
            "channel": "mcp_image_content",
            "mime_type": "image/png",
        }
    )
    selected["identity"] = _identity(selected)
    selected["handle"] = "eh_" + str(selected["identity"])[8:24]
    result = {
        "kind": "assessable",
        "trial_id": source["trial_id"],
        "relation": "exact",
        "relation_rationale": "The visual methods statement identifies the requested Result.",
        "applicability": {
            "design": "individual_parallel",
            "rationale": "The figure identifies the design.",
            "evidence": [selected["handle"]],
        },
        "target": {
            "measurement": {"method": "death ascertainment"},
            "time_point_or_window": {"kind": "described", "description": "end of follow-up"},
            "comparison_groups": [
                {"id": "a", "assignment": "assigned to intervention"},
                {"id": "b", "assignment": "assigned to control"},
            ],
            "baseline_subgroup": None,
            "intended_effect_measure": "risk ratio",
        },
        "reported": {
            "form": "group_bound_values",
            "analysis_population": "randomized population",
            "endpoint": {"name": "requested outcome", "definition": None},
            "group_values": [
                {"group_id": "a", "statistic": "risk", "value": "1", "unit": "events"},
                {"group_id": "b", "statistic": "risk", "value": "2", "unit": "events"},
            ],
        },
        "evidence": [
            {
                "kind": "figure",
                "handle": selected["handle"],
                "render_identity": render["identity"],
                "delivery_receipt": selected["delivery_receipt"],
                "region": selected["region"],
                "transcription": transcription,
                "provenance": "host_visual",
            }
        ],
    }
    return result, {selected["identity"]: selected}, {source["id"]: source}


def test_host_visual_methods_and_population_can_bind_and_replay() -> None:
    result, catalog, sources = _visual_case()
    result["target"].pop("baseline_subgroup")

    defects, _ = _bind_result(result, catalog, 0, "/results/0", [])

    assert defects == []
    result.update(
        {
            "requested_outcome": "requested outcome",
            "clarity": {
                key: "specified"
                for key in (
                    "outcome_definition", "measurement", "time_point", "analysis_population",
                    "comparison_groups",
                    "effect_measure",
                    "source_table_meaning",
                    "eligible_result_choice",
                )
            },
        }
    )
    target = result["target"]
    target["outcome_definition"] = "requested outcome"
    target["measurement"] = {
        "metric": "requested outcome",
        "method": target["measurement"]["method"],
    }
    target["effect_of_interest"] = "assignment"
    target["intended_analysis_population"] = "randomized population"
    assert _verify_result_evidence(
        result, catalog, sources, _identity, {"trial-1": "requested outcome"}
    )


def test_host_visual_wrong_region_is_still_rejected() -> None:
    result, catalog, _ = _visual_case()
    result["evidence"][0]["region"] = [0.0, 0.0, 1.1, 1.0]

    defects, _ = _bind_result(result, catalog, 0, "/results/0", [])

    assert any(defect["code"] == "figure_material_mismatch" for defect in defects)
