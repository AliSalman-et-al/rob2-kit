"""Normalize two frozen outputs for independent review; never invokes a model."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def db(work, name):
    return sqlite3.connect(f"file:{work}/.rob2-kit/{name}?mode=ro", uri=True)


def collect(condition):
    root = ROOT / condition
    run = read(root / "run.json")
    for name, digest in read(root / "answer-freeze.json").items():
        assert sha(root / name) == digest
    assert read(root / "effective-model.json") == [{"model": "gpt-6-luna", "effort": "medium"}]
    for path, digest in read(root / "protected-staging.json").items():
        assert sha(Path(path)) == digest
    record = read(root / "canonical-domain.json")
    assert (
        record["result_identity"]
        == read(OUT / "pair-freeze.json")["amended_common_result_identity"]
    )
    sources = {x["id"]: x for x in read(root / "source-provenance.json")["sources"]}
    derivative = db(root / "workspace", "derivative.sqlite3")
    catalog = read(root / "canonical-evidence.json")
    selected = {
        identity: json.loads(payload)
        for identity, payload in derivative.execute("select identity,payload from evidence_handles")
    }
    selected.update(catalog)
    handles = {x["handle"]: x for x in selected.values()}
    ranges = {
        (x["source_id"], x["page"], x["start_line"], x["end_line"]): x
        for x in selected.values()
        if x["kind"] == "narrative"
    }
    citations = []

    def citation(ref):
        if isinstance(ref, str):
            evidence = selected.get(ref) or handles.get(ref)
            if evidence is None:
                raise ValueError(f"Unresolved Evidence reference: {ref}")
        else:
            source_id = next(
                s for s in sources if "sh_" + s.removeprefix("source_")[:16] == ref["source_id"]
            )
            key = (source_id, ref["page"], ref["start_line"], ref["end_line"])
            evidence = ranges.get(key)
            if evidence is None:
                text = derivative.execute(
                    "select text from pages where source_id=? and page=?", (source_id, ref["page"])
                ).fetchone()
                assert text is not None
                lines = text[0].splitlines()
                valid = 1 <= ref["start_line"] <= ref["end_line"] <= len(lines)
                evidence = {
                    "source_id": source_id,
                    "source_version": sources[source_id]["projection_hash"],
                    "kind": "narrative",
                    "page": ref["page"],
                    "start_line": ref["start_line"],
                    "end_line": ref["end_line"],
                    "quote": "\n".join(lines[ref["start_line"] - 1 : ref["end_line"]])
                    if valid
                    else None,
                    "resolution": "valid inspected range" if valid else "invalid line bounds",
                    "available_page_lines": len(lines),
                }
        source = sources[evidence["source_id"]]
        value = {
            "source_file": source["logical_path"],
            "captured_bytes_sha256": source["sha256"],
            "projection_version": evidence.get("source_version", source["projection_hash"]),
            "kind": evidence["kind"],
        }
        if evidence["kind"] == "figure":
            value.update(
                {
                    "page": evidence["render"]["page"],
                    "region": evidence["region"],
                    "transcription": evidence["transcription"],
                    "provenance": evidence["provenance"],
                    "uncertainty": evidence.get("uncertainty"),
                    "png_sha256": evidence["render"]["png_sha256"],
                    "visual_delivery_receipt": evidence["delivery_receipt"],
                }
            )
        else:
            value.update(
                {
                    "page": evidence["page"],
                    "start_line": evidence["start_line"],
                    "end_line": evidence["end_line"],
                    "exact_projection_quote": evidence["quote"],
                }
            )
            if "resolution" in evidence:
                value.update(
                    {
                        "resolution": evidence["resolution"],
                        "available_page_lines": evidence["available_page_lines"],
                    }
                )
        if value not in citations:
            citations.append(value)
        return "C" + str(citations.index(value) + 1).zfill(2)

    def normalize(answer, canonical):
        value = {k: answer[k] for k in ["question_id", "answer", "justification", "unknowns"]}
        bases = []
        for basis in answer.get("bases", []):
            if isinstance(basis, str) or "source_id" in basis:
                bases.append({"role": "indirect_support", "citation": citation(basis)})
            elif "evidence" in basis:
                entry = {
                    "role": basis.get("kind", basis.get("role")),
                    "citation": citation(basis["evidence"]),
                }
                if basis.get("working_observation") is not None:
                    entry["host_observation"] = basis["working_observation"]
                bases.append(entry)
            else:
                bases.append(
                    {
                        "role": "information_limit",
                        "unresolved_premise": basis.get("unresolved_premise", basis.get("premise")),
                        "stopping_rationale": basis["stopping_rationale"],
                    }
                )
        for limit in answer.get("limitations", []):
            bases.append(
                {
                    "role": "information_limit",
                    "unresolved_premise": limit["premise"],
                    "stopping_rationale": limit["stopping_rationale"],
                }
            )
        value["bases"] = bases
        points = []
        for point in answer["counterevidence"]:
            refs = (
                [bases[point["basis_index"]]["citation"]]
                if canonical
                else [citation(x) for x in point["evidence"]]
            )
            points.append({"citations": refs, "implication": point["implication"]})
        value["counterevidence"] = points
        if answer.get("missing_data"):
            rows = answer["missing_data"].get("rows", []) if canonical else answer["missing_data"]
            value["participant_flow"] = [
                {**row, "basis": [citation(ref) for ref in row["basis"]]} for row in rows
            ]
            if canonical:
                value["participant_flow_conflicts"] = answer["missing_data"]["conflicts"]
        return value

    final = [normalize(a, True) for a in record["answers"]]
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    calls = [
        row["item"]
        for row in events
        if row.get("type") == "item.completed"
        and row.get("item", {}).get("type") == "mcp_tool_call"
    ]
    saves = [x for x in calls if x["tool"] == "save_domain_judgment"]
    rejected = run["submission_rejections"]
    first_rejected = (
        [normalize(a, False) for a in rejected[0]["item"]["arguments"]["answers"]]
        if rejected
        else None
    )
    review = {
        "trial": "AWARD-1",
        "result_identity": record["result_identity"],
        "active_questions": record["active_questions"],
        "final_answers": final,
        "derived_domain_judgment": record["judgment"],
        "first_rejected_answers": first_rejected,
        "citations": {"C" + str(i + 1).zfill(2): value for i, value in enumerate(citations)},
    }
    references = []
    for index, save in enumerate(saves, 1):
        counts = Counter()
        for answer in save["arguments"]["answers"]:
            for basis in answer["bases"]:
                counts[
                    "bare_handle"
                    if isinstance(basis, str)
                    else "exact_range"
                    if "source_id" in basis
                    else "full_citation"
                ] += 1
            for point in answer["counterevidence"]:
                for evidence in point["evidence"]:
                    counts[
                        "counterpoint_handle" if isinstance(evidence, str) else "counterpoint_range"
                    ] += 1
        references.append(
            {
                "attempt": index,
                "reference_counts": dict(counts),
                "accepted": save["result"].get("structured_content", {}).get("outcome")
                == "success",
                "request_sha256": hashlib.sha256(
                    json.dumps(save["arguments"], sort_keys=True).encode()
                ).hexdigest(),
            }
        )
    images = []
    for call in calls:
        if call["tool"] == "render_page":
            for block in call["result"].get("content", []):
                if block["type"] == "image":
                    images.append(
                        {
                            "tool": "render_page",
                            "arguments": call["arguments"],
                            "mime_type": block["mimeType"],
                            "image_bytes_sha256": hashlib.sha256(
                                base64.b64decode(block["data"])
                            ).hexdigest(),
                        }
                    )
    reads = [
        dict(
            zip(
                ["batch_id", "phase", "trial_id", "source_id", "page", "start_line", "end_line"],
                row,
            )
        )
        for row in derivative.execute(
            "select * from page_reads where phase='assessment' "
            "order by source_id,page,start_line,end_line"
        )
    ]
    for row in reads:
        row["source_file"] = sources[row.pop("source_id")]["logical_path"]
    delivery = {
        "successful_read_calls": [
            {
                "arguments": x["arguments"],
                "output_sha256": hashlib.sha256(
                    json.dumps(x["result"], sort_keys=True).encode()
                ).hexdigest(),
            }
            for x in calls
            if x["tool"] == "read_pages"
            and (x["result"].get("structured_content") or {}).get("outcome") == "success"
        ],
        "assessment_read_receipts": reads,
        "image_content_delivery": images,
        "retained_visual_evidence": sum(e["kind"] == "figure" for e in catalog.values()),
        "source_integrity_verified": True,
        "note": (
            "Read receipts and native image ContentBlocks attest to tool delivery, "
            "not comprehension. Initial proposal receipts are excluded."
        ),
    }
    metrics = {
        k: run[k]
        for k in [
            "stop",
            "elapsed_seconds",
            "tool_calls",
            "usage",
            "uncached_input_tokens",
            "provider_response_count",
            "model_context",
            "scientific_original_and_staging_hashes_unchanged",
        ]
    }
    metrics.update(
        {
            "submission_rejections": len(rejected),
            "first_submission_accepted": not rejected,
            "tool_counts": dict(Counter(x["tool"] for x in calls)),
            "reference_use": references,
            "semantic_review": "pending independent interface-blind review",
            "terminal_error": rejected[0]["item"]["result"]["structured_content"]["condition"]
            if rejected
            else None,
        }
    )
    receipts = {
        "answer_freeze": read(root / "answer-freeze.json"),
        "actual_model": read(root / "effective-model.json"),
        "launch_preflight": read(root / "launch-preflight.json"),
        "stderr_sha256": sha(root / "stderr.log"),
        "stderr_bytes": (root / "stderr.log").stat().st_size,
        "canonical_domain_sha256": sha(root / "canonical-domain.json"),
        "canonical_evidence_sha256": sha(root / "canonical-evidence.json"),
        "protected_staging_hashes_reverified": True,
        "paid_invocations": 1,
        "retry": False,
    }
    derivative.close()
    return review, metrics, delivery, receipts


# Both terminal freezes must exist before any adjudication/export.
assert all((ROOT / c / "answer-freeze.json").exists() for c in ["A", "B"])
results = {c: collect(c) for c in ["A", "B"]}
review_dir = OUT / "independent-review"
review_dir.mkdir(exist_ok=True)
mapping = read(ROOT / "private-review-mapping.json")
for label, condition in mapping["mapping"].items():
    write(review_dir / (label + ".json"), {"review_id": label, **results[condition][0]})
for filename, index in [
    ("terminal-metrics.json", 1),
    ("source-delivery.json", 2),
    ("terminal-receipts.json", 3),
]:
    write(OUT / filename, {c: results[c][index] for c in ["A", "B"]})
write(
    OUT / "review-packet-manifest.json",
    {
        "normalization": (
            "Common resolved citation representation; exact model warrants, unknowns "
            "and counterclaims retained. No answer rewritten. Implicit compact "
            "support role retained as indirect_support. Invalid ranges remain "
            "invalid without fabricating quotes."
        ),
        "blindness_limit": (
            "Technical condition mapping and performance are excluded from "
            "independent-review/. Warrant style, optional tables and citation "
            "granularity may permit inference; blinding is imperfect."
        ),
        "review_order_frozen_before_semantic_inspection": True,
        "private_mapping_sha256": sha(ROOT / "private-review-mapping.json"),
        "review_files": {p.name: sha(p) for p in sorted(review_dir.glob("*.json"))},
        "no_accuracy_or_better_claim_before_review": True,
    },
)
print("Both frozen conditions exported; semantic review remains pending.")
