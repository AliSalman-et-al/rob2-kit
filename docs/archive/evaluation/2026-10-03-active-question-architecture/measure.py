# ruff: noqa: E501
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

from rob2_kit.packs import SCIENTIFIC_PACK

repo = Path.cwd()
out = repo / "docs/evaluation/2026-10-03-active-question-architecture"
project_active_questions = runpy.run_path(str(out / "prototype.py"))["project_active_questions"]


def size(x: object) -> int:
    return len(json.dumps(x, ensure_ascii=False, separators=(",", ":")).encode())


def strings(x: object) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for v in x.values() for s in strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in strings(v)]
    return []


metrics = []
for case, name in [
    ("award-10", "2026-10-03-award10-production-d3"),
    ("host-exam", "2026-10-03-host-exam-d5-production"),
]:
    path = repo / "docs/evaluation" / name / "events.jsonl"
    seen = set()
    calls = []
    saves = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        item = row.get("item", {})
        if item.get("status") != "completed" or item.get("id") in seen:
            continue
        seen.add(item.get("id"))
        if item.get("tool") == "get_domain_context":
            calls.append(item)
        if item.get("tool") == "save_domain_judgment":
            saves.append(item)
    first = calls[0]["result"]["structured_content"]["data"]["context_page"]["snapshot_digest"]
    calls = [
        c
        for c in calls
        if c["result"]["structured_content"]["data"]["context_page"]["snapshot_digest"] == first
    ]
    calls.sort(key=lambda c: c["result"]["structured_content"]["data"]["context_page"]["index"])
    assert len(calls) == calls[0]["result"]["structured_content"]["data"]["context_page"]["count"]
    full = {}
    transportbytes = sum(size(c["result"]["structured_content"]) for c in calls)
    for call in calls:
        d = call["result"]["structured_content"]["data"]
        for key, value in d.items():
            if key == "context_page":
                continue
            if key in ["questions", "evidence", "comparison_cards", "primary_report"]:
                full.setdefault(key, []).extend(value)
            else:
                assert key not in full
                full[key] = value
    qby = {q["id"]: q for q in full["questions"]}
    duplicatedofficial = []
    for section in full["official_guidance"]["sections"]:
        for qid in section["question_ids"]:
            assert section["excerpt"] == qby[qid]["official_guidance"]
            duplicatedofficial.append(section["excerpt"])
    # Verify recorded D3/D5 guidance still matches currentHEAD scientific text.
    for qid, card in qby.items():
        q = next(q for q in SCIENTIFIC_PACK.questions if q.id == qid)
        g = q.guidance.operational.model_dump(mode="json")
        assert (
            card["wording"] == q.wording
            and card["official_guidance"] == q.guidance.official.source_excerpt
        )
        for key in [
            "bias_construct",
            "decision_rule",
            "evidence_needed",
            "no_information_rule",
            "answer_anchors",
            "considerations",
            "invalid_shortcuts",
            "query_suggestions",
        ]:
            assert card[key] == g[key], (case, qid, key)
    active = [
        q
        for q in full["questions"]
        if q["activation_status"] in ["always_active", "active_in_saved_checkpoint"]
    ]
    conditional = [q for q in full["questions"] if q not in active]
    projected = project_active_questions(full, enabled=True)
    folder = out / case
    folder.mkdir(exist_ok=True)
    for filename, obj in [
        ("full-context.json", full),
        ("active-context.json", projected),
        ("transport-pages.json", calls),
    ]:
        (folder / filename).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    leaf = Counter(s for s in strings(full) if len(s) >= 80)
    reportdup = sum(
        size(c["reported_result"])
        for c in full["comparison_cards"]
        if c.get("reported_result") == full["result"]["reported"]
    )
    saveargs = saves[0]["arguments"]
    answerstrings = sum(
        len(s.encode())
        for a in saveargs["answers"]
        for key in ["justification", "unknowns", "counterevidence"]
        for s in strings(a.get(key))
    )
    metrics.append(
        {
            "case": case,
            "original_trace": str(path),
            "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "current_head_D3_D5_question_text_equal_to_recorded": True,
            "pack_identity_not_regenerated": True,
            "actual_context_calls": len(calls),
            "requested_page_bytes": calls[0]["arguments"].get("max_response_bytes", 32768),
            "first_page_question_count": len(
                calls[0]["result"]["structured_content"]["data"].get("questions", [])
            ),
            "transport_structured_bytes": transportbytes,
            "full_context_bytes": size(full),
            "active_projection_bytes": size(projected),
            "reduction_bytes": size(full) - size(projected),
            "reduction_percent": round(100 * (size(full) - size(projected)) / size(full), 2),
            "active_question_ids": [q["id"] for q in active],
            "conditional_not_yet_active_ids": [q["id"] for q in conditional],
            "active_question_card_bytes": sum(size(q) for q in active),
            "conditional_question_card_bytes": sum(size(q) for q in conditional),
            "section_bytes": {k: size(v) for k, v in full.items()},
            "official_excerpt_duplicate_utf8_bytes": sum(
                len(s.encode()) for s in duplicatedofficial
            ),
            "reported_result_exact_duplicate_bytes": reportdup,
            "duplicate_leaf_string_bytes_min80": sum(
                (n - 1) * len(s.encode()) for s, n in leaf.items() if n > 1
            ),
            "duplicate_leaf_count": sum(n - 1 for s, n in leaf.items() if n > 1),
            "source_evidence_unchanged": projected["evidence"] == full["evidence"],
            "comparison_card_unchanged": projected["comparison_cards"] == full["comparison_cards"],
            "target_result_unchanged": projected["result"] == full["result"],
            "recovery_coverage_workspace_unchanged": all(
                projected.get(k) == full.get(k)
                for k in ["reading_recovery", "coverage", "evidence_workspace"]
            ),
            "save_argument_bytes": size(saveargs),
            "scientific_explanation_string_bytes": answerstrings,
            "submission_question_ids": [a["question_id"] for a in saveargs["answers"]],
            "included_candidates": calls[0]["arguments"].get("include_candidates", False),
            "byte_count_not_token_or_attention_measure": True,
        }
    )
(out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
print(
    json.dumps(
        [
            {
                k: v
                for k, v in m.items()
                if k
                in [
                    "case",
                    "full_context_bytes",
                    "active_projection_bytes",
                    "reduction_bytes",
                    "reduction_percent",
                    "actual_context_calls",
                    "active_question_ids",
                    "conditional_not_yet_active_ids",
                    "official_excerpt_duplicate_utf8_bytes",
                    "reported_result_exact_duplicate_bytes",
                    "save_argument_bytes",
                    "scientific_explanation_string_bytes",
                ]
            }
            for m in metrics
        ],
        indent=2,
    )
)
