from copy import deepcopy
from typing import Any

from scripts.account_repair_review import review_checkpoint_repairs


def test_rejected_draft_and_scientific_loss_are_visible_without_merge():
    original: dict[str, Any] = {
        "trial_id": "neutral",
        "result_account": {
            "steps": [
                {
                    "id": "collection",
                    "aspect": "outcome_ascertainment",
                    "observation": {
                        "text": "Recorder observed measurement.",
                        "sources": ["eh_12345678"],
                    },
                    "unknowns": ["Assessor blinding unknown."],
                    "counterevidence": [
                        {"text": "Recorder role unresolved.", "sources": ["eh_12345678"]}
                    ],
                }
            ]
        },
    }
    repaired = deepcopy(original)
    repaired["result_account"] = repaired["result_account"]["steps"]
    unchanged = deepcopy(repaired)
    del repaired["result_account"][0]["unknowns"]
    events = []
    for number, draft in enumerate((original, unchanged, repaired)):
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "id": str(number),
                    "tool": "save_working_checkpoint",
                    "arguments": {"checkpoint": draft},
                    "result": {
                        "structured_content": {"outcome": "condition" if number == 0 else "success"}
                    },
                },
            }
        )
    frozen = deepcopy(events)
    review = review_checkpoint_repairs(events)
    assert review[0]["checkpoint"] == original
    assert review[1]["scientific_content_changes"] == []
    assert review[2]["scientific_content_changes"] == [
        {
            "path": "collection.unknowns",
            "before": ["Assessor blinding unknown."],
            "after": None,
            "kind": "removed",
        }
    ]
    assert "unknowns" not in review[2]["checkpoint"]["result_account"][0]
    assert events == frozen
    other_trial = deepcopy(events[-1])
    other_trial["item"]["arguments"]["checkpoint"]["trial_id"] = "different-trial"
    assert (
        review_checkpoint_repairs([events[0], other_trial])[-1]["scientific_content_changes"] == []
    )
