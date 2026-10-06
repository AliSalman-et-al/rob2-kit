"""Offline active-set projection; no MCP, state mutation or answer selection."""

import hashlib
import json
from copy import deepcopy
from typing import Any


def project_active_questions(
    full_context: dict[str, Any], *, enabled: bool = False
) -> dict[str, Any]:
    projected = deepcopy(full_context)
    if not enabled:
        return projected
    questions = full_context["questions"]
    selected = [
        question
        for question in questions
        if question["activation_status"] in {"always_active", "active_in_saved_checkpoint"}
    ]
    if not selected:
        raise ValueError("no recorded active question; use complete context")
    # Full guidance for every branch remains in the exact offline snapshot.
    # Evidence/card fields are deliberately not filtered by inferred relevance.
    projected["questions"] = deepcopy(selected)
    projected.pop("official_guidance", None)
    projected["question_view"] = {
        "prototype_only": True,
        "scope": "recorded active set; conditional activation still depends on draft answers",
        "index": [
            {
                key: deepcopy(question[key])
                for key in ("id", "wording", "options", "activation_status", "activation")
            }
            for question in questions
        ],
        "official_source_index": [
            {key: deepcopy(value) for key, value in section.items() if key != "excerpt"}
            for section in full_context["official_guidance"]["sections"]
        ],
        "full_guidance_recovery": {
            "full_context_sha256": hashlib.sha256(
                json.dumps(
                    full_context, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest(),
            "offline_snapshot": "full-context.json",
            "json_pointers": ["/questions", "/official_guidance"],
            "runtime_existing_tool": "get_domain_context",
            "runtime_caveat": (
                "prototype is not exposed by MCP; no executable focused cursor exists"
            ),
        },
    }
    return projected
