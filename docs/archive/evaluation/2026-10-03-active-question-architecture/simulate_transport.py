# ruff: noqa: E501
import json
from pathlib import Path

from rob2_kit.interfaces.mcp.server import (
    _domain_context_transport_bytes,
    _paginate_domain_context_transport,
)

r = Path("docs/evaluation/2026-10-03-active-question-architecture")
results = []
for case in ["award-10", "host-exam"]:
    pages = json.loads((r / case / "transport-pages.json").read_text())
    head = pages[-1]["result"]["structured_content"]["head"]
    rev = head["state_revision"]
    for view in ["full", "active"]:
        data = json.loads((r / case / f"{view}-context.json").read_text())
        for budget in [20000, 32768, 65536]:
            value = {"outcome": "success", "head": head, "data": data}
            cursor = None
            wire = []
            while True:
                p = _paginate_domain_context_transport(
                    value, cursor, budget, "offline-only-basis", rev
                )
                wire.append(p)
                cursor = p["data"]["context_page"]["next_cursor"]
                if cursor is None:
                    break
            results.append(
                {
                    "case": case,
                    "view": view,
                    "page_bytes": budget,
                    "calls": len(wire),
                    "first_page_question_count": len(wire[0]["data"]["questions"]),
                    "serialized_mcp_envelope_bytes": sum(
                        _domain_context_transport_bytes(p) for p in wire
                    ),
                    "scope": "offline actual paginator; dcp1 deterministic cursor, no nativeMCP/storecall/model",
                    "conditional_guidance_recovery_not_included": view == "active",
                }
            )
(r / "transport-simulation.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
