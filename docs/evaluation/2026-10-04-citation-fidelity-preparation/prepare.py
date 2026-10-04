"""Freeze exact preserved claims and sources without expected labels in task input."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from diagnostic_evidence_preflight import check_manifest

from rob2_kit.application.trials import _review_domain_findings

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
AUDIT = ROOT / "docs/evaluation/2026-10-03-citation-linkage-audit"
D = ROOT.parent / "diagnostics"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read(path: Path) -> object:
    return json.loads(path.read_text())


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


audit = read(AUDIT / "audit.json")
dapa = read(
    ROOT / "docs/evaluation/2026-10-03-exscel-review-response-d789ea8/code-dapa-comparator.json"
)
items = []
for item_id, key, focus in [
    (
        "A",
        "gupta",
        (
            "For eligible infants, oxygen-reduction testing was not performed in similar "
            "proportions (13/86 vs 13/94)."
        ),
    ),
    (
        "C",
        "exscel",
        (
            "The SAP specifies the ITT Cox analysis and enumerates primary censoring and "
            "sensitivity analyses, including plausible missing-follow-up event "
            "imputation;"
        ),
    ),
]:
    original = audit["case_negatives"][key]
    claim = original["exact_final_saved_claim"]
    assert focus in claim["justification"]
    items.append(
        {
            "id": item_id,
            "trial": key,
            "claim": focus,
            "original_warrant": claim["justification"],
            "unknowns": claim["unknowns"],
            "counterevidence": claim["counterevidence"],
            "cited": original["basis_links"],
            "other_available": [original["already_read_correct_source"]],
        }
    )
focus = "The protocol states that SAP amendments would be completed before unblinding."
assert focus in dapa["justification"]
e = dapa["evidence"]
items.insert(
    1,
    {
        "id": "B",
        "trial": "dapa-hf",
        "claim": focus,
        "original_warrant": dapa["justification"],
        "unknowns": [],
        "counterevidence": [],
        "cited": [
            {
                "selected_handle": e["handle"],
                "selected_identity": e["identity"],
                "original_page_receipt": {
                    "source_id": e["source_id"],
                    "page": e["page"],
                    "returned_start_line": e["start_line"],
                    "returned_end_line": e["end_line"],
                    "numbered_text": "\n".join(
                        f"{n}|{line}"
                        for n, line in enumerate(e["quote"].splitlines(), e["start_line"])
                    ),
                },
            }
        ],
        "other_available": [],
    },
)
text = (
    "Review only the focused claim in each item against its cited passages. "
    "The original warrant is context, not a request to reassess the Domain. "
    "Other available passages were also delivered in the preserved assessment. "
    "For each clause, state what the cited source directly establishes, "
    "what requires inference and why, what is not established there, "
    "and whether another supplied passage supports it. "
    "Distinguish lack of support from contradiction and plans from actual conduct. "
    "Retain uncertainty. Give exact source/page/line references for your findings. "
    "If needed, offer the smallest source-supported wording or citation change; "
    "do not replace citations automatically. "
    "Do not assign a risk-of-bias judgment. Answer in at most 600 words.\n\n"
)
windows = []
provenance = []
for item in items:
    text += (
        f"Item {item['id']} ({item['trial']})\nFocused claim: {item['claim']}\n"
        f"Original warrant: {item['original_warrant']}\n"
    )
    text += (
        "Recorded uncertainty: "
        + json.dumps({"unknowns": item["unknowns"], "counterevidence": item["counterevidence"]})
        + "\n"
    )
    for group in ("cited", "other_available"):
        text += "Cited passages:\n" if group == "cited" else "Other available passages:\n"
        for link in item[group]:
            page = link["original_page_receipt"]
            if page is None:
                selected = link["selected_record"]
                lines = selected["quote"].splitlines()
                assert len(lines) == selected["end_line"] - selected["start_line"] + 1
                page = {
                    "source_id": selected["source_id"],
                    "page": selected["page"],
                    "returned_start_line": selected["start_line"],
                    "returned_end_line": selected["end_line"],
                    "numbered_text": "\n".join(
                        f"{n}|{line}" for n, line in enumerate(lines, selected["start_line"])
                    ),
                }
            source = page["source_id"]
            text += (
                f"Source {source}; physical page {page['page']}; "
                f"evidence {link['selected_handle']}\n"
            )
            passage = page["numbered_text"]
            start = len(text.encode())
            text += passage
            end = len(text.encode())
            text += "\n\n"
            window = {
                "source_identity": source,
                "page": page["page"],
                "start_line": page["returned_start_line"],
                "end_line": page["returned_end_line"],
            }
            windows.append(
                {
                    **window,
                    "input_start_byte": start,
                    "input_end_byte": end,
                    "text_sha256": sha(passage.encode()),
                }
            )
            provenance.append(
                {"item": item["id"], "group": group, "window": window, "original_link": link}
            )
input_path = OUT / "input.txt"
input_path.write_text(text)
manifest = {
    "research_question": (
        "Does a focused factual review preserve clause-level citation fidelity "
        "without confusing unsupported citation, inference, contradiction, and support elsewhere?"
    ),
    "input_sha256": sha(input_path.read_bytes()),
    "required_windows": [
        {k: w[k] for k in ("source_identity", "page", "start_line", "end_line")} for w in windows
    ],
    "supplied_windows": windows,
}
write("evidence-manifest.json", manifest)
write("coverage-check.json", check_manifest(OUT / "evidence-manifest.json", input_path))
write("source-provenance.json", provenance)

# Current function-level review projection using a disposable cache copy and exact closed state.
original_root = D / "frozen-exscel-bd92ec8/workspace"
cache = original_root / ".rob2-kit"
original_hashes = {str(p): sha(p.read_bytes()) for p in cache.glob("*.sqlite3")}
copy = D / "citation-fidelity-review-20261004"
if not copy.exists():
    shutil.copytree(cache, copy / ".rob2-kit")
state = read(ROOT / "docs/evaluation/2026-10-03-exscel-host-recovery/frozen-final-state.json")
findings = _review_domain_findings(copy, state, "exscel")
answer = next(
    a
    for d in findings
    for a in d["answers"]
    if a["question_id"] == "sq:selection:multiple-analyses"
)
assert (
    answer["warrant"]
    == audit["case_negatives"]["exscel"]["exact_final_saved_claim"]["justification"]
)
assert len(answer["facts"]) == 3
assert all(f["text"] and f["evidence"]["handle"] for f in answer["facts"])
assert len(answer["evidence_expansions"]) == 3
assert original_hashes == {str(p): sha(p.read_bytes()) for p in cache.glob("*.sqlite3")}
write("current-review-answer.json", answer)
write(
    "preparation.json",
    {
        "model_calls": 0,
        "runtime_changes": False,
        "input_sha256": sha(input_path.read_bytes()),
        "input_bytes": len(input_path.read_bytes()),
        "required_windows": len(windows),
        "original_cache_hashes_unchanged": original_hashes,
        "review_projection_kind": (
            "current function-level answer; not a model response or live MCP wire replay"
        ),
    },
)
print(
    json.dumps(
        {
            "input_bytes": len(input_path.read_bytes()),
            "source_windows": len(windows),
            "review_facts": len(answer["facts"]),
        }
    )
)
