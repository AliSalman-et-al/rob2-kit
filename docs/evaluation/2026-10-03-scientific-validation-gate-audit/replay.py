"""Freeze bounded existing case receipts and current primary guidance; no inference."""

import hashlib
import json
from pathlib import Path

from rob2_kit.application.domains import _RESPONSE_FRAMEWORK
from rob2_kit.packs import SCIENTIFIC_PACK

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).parent
CANVAS = Path(
    "/home/ali/Documents/Code/rob2-kit-benchmark/"
    "benchmark-luna6-medium-2026-10-01/cases/canvas-program/turn-2.jsonl"
)
AN = ROOT / "docs/evaluation/2026-10-02-frozen-an-5a3e580/an-2021/submissions.json"

canvas = {}
for line in CANVAS.read_text().splitlines():
    event = json.loads(line)
    item = event.get("item", {})
    if event.get("type") == "item.completed" and item.get("id") in {
        "item_103",
        "item_105",
        "item_108",
    }:
        canvas[item["id"]] = item
assert canvas["item_103"]["result"]["structured_content"] is None
assert canvas["item_105"]["result"]["structured_content"] is None
accepted = canvas["item_108"]
assert accepted["result"]["structured_content"]["outcome"] == "success"
assert accepted["arguments"]["answers"][0]["answer"] == "probably_yes"
assert accepted["arguments"]["answers"][0]["unknowns"]
an = json.loads(AN.read_text())[1]
assert an["arguments"]["answers"][3]["question_id"] == "sq:deviations:appropriate-analysis"
assert an["arguments"]["answers"][3]["answer"] == "no"
assert an["arguments"]["answers"][3]["limitations"]
assert an["result"]["structured_content"]["outcome"] == "repair"
assert an["result"]["structured_content"]["repairs"][0]["code"] == (
    "complete_claim_has_unresolved_premise"
)
question_ids = {
    "sq:deviations:appropriate-analysis",
    "sq:deviations:substantial-impact",
    "sq:missing:evidence-unbiased",
    "sq:selection:prespecified-analysis",
    "sq:selection:multiple-measurements",
    "sq:selection:multiple-analyses",
}
packet = {
    "decision": "no demonstrated analogous scientific overconstraint in these two candidate gates",
    "input_sha256": {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (CANVAS, AN)
    },
    "current_pack": SCIENTIFIC_PACK.content_hash,
    "response_framework": _RESPONSE_FRAMEWORK.model_dump(mode="json"),
    "questions": [
        q.model_dump(mode="json") for q in SCIENTIFIC_PACK.questions if q.id in question_ids
    ],
    "an_rejected_draft": an,
    "canvas_structural_rejections_and_accepted_probable": canvas,
}
(OUTPUT / "gate-evidence.json").write_text(json.dumps(packet, indent=2) + "\n")
print("Frozen gate evidence assertions passed; packet regenerated.")
