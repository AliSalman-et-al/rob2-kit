"""Mechanical controls only; not scientific expected answers or model input."""

import copy
import hashlib
import json
import runpy
from pathlib import Path

root = Path("docs/evaluation/2026-10-05-synthetic-source-inference-contrast")
private = Path("diagnostics/synthetic-source-inference-contrast-20261005/binding-fixtures")
private.mkdir(exist_ok=True)
checker = runpy.run_path(str(root / "check_output.py"))
packet_bytes = (root / "sources-and-claims.json").read_bytes()
packet = json.loads(packet_bytes)
findings, revisions = [], []
for case in packet["cases"]:
    for claim in case["claims"]:
        findings.append(
            {
                "claim_id": claim["claim_id"],
                "field": "justification",
                "clause": claim["text"],
                "classification": "unresolved",
                "explanation": "Mechanical fixture; no semantic claim.",
                "uncertainty": "Not evaluated for factual entailment.",
                "references": [
                    {
                        "location": {
                            "source_id": case["source_id"],
                            "page": 1,
                            "start_line": 1,
                            "end_line": 1,
                        },
                        "quote": case["numbered_text"].splitlines()[0].split("|", 1)[1],
                        "relation": "limits",
                    }
                ],
            }
        )
        revisions.append(
            {
                "claim_id": claim["claim_id"],
                "revised_text": claim["text"],
                "rationale": "Unchanged mechanical fixture; not an evaluated correction.",
            }
        )
valid = {
    "review": {
        "snapshot_identity": "sha256:" + hashlib.sha256(packet_bytes).hexdigest(),
        "findings": findings,
    },
    "revisions": revisions,
}
fixtures = [("mechanical-valid", valid, True)]


def mutate(name, fn):
    value = copy.deepcopy(valid)
    fn(value)
    fixtures.append((name, value, False))


mutate("foreign-claim", lambda v: v["review"]["findings"][0].update(claim_id="foreign"))
mutate(
    "duplicate-claim",
    lambda v: v["review"]["findings"].__setitem__(0, copy.deepcopy(v["review"]["findings"][1])),
)
mutate("missing-claim", lambda v: v["review"]["findings"].pop())
mutate(
    "extra-claim",
    lambda v: v["review"]["findings"].append(copy.deepcopy(v["review"]["findings"][0])),
)
mutate(
    "wrong-case",
    lambda v: v["review"]["findings"][0]["references"][0]["location"].update(
        source_id=packet["cases"][1]["source_id"]
    ),
)
mutate(
    "spliced-quote",
    lambda v: v["review"]["findings"][0]["references"][0].update(
        quote=(
            "This synthetic randomized adult stroke rehabilitation study assigned 48 "
            "participants. All participants met the eligibility criteria before randomization."
        )
    ),
)
mutate("stale-snapshot", lambda v: v["review"].update(snapshot_identity="sha256:" + "0" * 64))
mutate(
    "partial-clause",
    lambda v: v["review"]["findings"][0].update(clause="The two excluded participants"),
)
mutate("wrong-field", lambda v: v["review"]["findings"][0].update(field="unknowns"))
mutate(
    "wrong-page", lambda v: v["review"]["findings"][0]["references"][0]["location"].update(page=2)
)
mutate(
    "zero-lines",
    lambda v: v["review"]["findings"][0]["references"][0]["location"].update(
        start_line=0, end_line=0
    ),
)
mutate(
    "outside-lines",
    lambda v: v["review"]["findings"][0]["references"][0]["location"].update(end_line=99),
)
mutate(
    "reversed-lines",
    lambda v: v["review"]["findings"][0]["references"][0]["location"].update(
        start_line=2, end_line=1
    ),
)
mutate(
    "boolean-line",
    lambda v: v["review"]["findings"][0]["references"][0]["location"].update(start_line=True),
)
mutate("null-text-quote", lambda v: v["review"]["findings"][0]["references"][0].update(quote=None))
mutate("blank-explanation", lambda v: v["review"]["findings"][0].update(explanation=" "))
mutate("blank-revision", lambda v: v["revisions"][0].update(revised_text=" "))
mutate("foreign-revision", lambda v: v["revisions"][0].update(claim_id="foreign"))
mutate(
    "duplicate-revision", lambda v: v["revisions"].__setitem__(0, copy.deepcopy(v["revisions"][1]))
)
mutate("missing-revision", lambda v: v["revisions"].pop())
mutate("extra-property", lambda v: v.update(extra=True))
empty = copy.deepcopy(valid)
for finding in empty["review"]["findings"]:
    finding["references"] = []
fixtures.append(("unresolved-empty-references", empty, False))
collapsed = copy.deepcopy(valid)
ref = collapsed["review"]["findings"][0]["references"][0]
ref["location"]["end_line"] = 2
ref["quote"] += " " + packet["cases"][0]["numbered_text"].splitlines()[1].split("|", 1)[1]
fixtures.append(("contiguous-whitespace-collapse", collapsed, True))
mutate("zero-findings", lambda v: v["review"].update(findings=[]))
mutate(
    "thirteen-duplicate-unknown-revisions",
    lambda v: v.update(revisions=[{**r, "claim_id": "foreign"} for r in v["revisions"]]),
)
mutate(
    "stale-whole-clause",
    lambda v: v["review"]["findings"][0].update(clause=v["review"]["findings"][1]["clause"]),
)
mutate("finding-order", lambda v: v["review"]["findings"].reverse())
mutate("revision-order", lambda v: v["revisions"].reverse())
mutate(
    "fabricated-quote",
    lambda v: v["review"]["findings"][0]["references"][0].update(
        quote="Both outcomes were recorded by blinded assessors."
    ),
)
mutate("empty-quote", lambda v: v["review"]["findings"][0]["references"][0].update(quote=""))
mutate(
    "unknown-source",
    lambda v: v["review"]["findings"][0]["references"][0]["location"].update(
        source_id="sh_" + "0" * 16
    ),
)
mutate(
    "visual-reference",
    lambda v: v["review"]["findings"][0]["references"][0].update(
        location={
            "delivery_receipt": "sha256:" + "0" * 64,
            "region": [0.0, 0.0, 1.0, 1.0],
            "transcription": "Mechanical visual fixture.",
            "uncertainty": None,
        },
        quote=None,
    ),
)
results = []
for name, value, expected in fixtures:
    data = (json.dumps(value, indent=2) + "\n").encode()
    (private / (name + ".json")).write_bytes(data)
    error = None
    try:
        checker["check"](data)
        accepted = True
    except Exception as exc:
        accepted = False
        error = str(exc)
    assert accepted == expected, (name, accepted, error)
    results.append(
        {"fixture": name, "expected_valid": expected, "accepted": accepted, "error": error}
    )
# Duplicate JSON keys cannot be silently overwritten by a parser.
data = json.dumps(valid).replace('"review": {', '"review": {}, "review": {', 1).encode()
(private / "duplicate-json-key.json").write_bytes(data)
try:
    checker["check"](data)
except ValueError as exc:
    results.append(
        {
            "fixture": "duplicate-json-key",
            "expected_valid": False,
            "accepted": False,
            "error": str(exc),
        }
    )
else:
    raise AssertionError("Duplicate JSON key accepted")
receipt = {
    "scope": "Mechanical offline fixture checks only; zero model calls or semantic scoring",
    "passed": len(results),
    "valid_controls": sum(r["expected_valid"] for r in results),
    "results": results,
}
(root / "binding-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({k: v for k, v in receipt.items() if k != "results"}))
