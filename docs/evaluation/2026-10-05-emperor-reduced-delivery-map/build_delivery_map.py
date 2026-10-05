"""Offline receipt map; no inference, Source mutation or corpus acquisition."""

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--run-dir", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
run, out = args.run_dir.resolve(), args.output_dir.resolve()
out.mkdir(parents=True, exist_ok=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


seal = json.loads((run / "outputs-freeze-final.json").read_text())
for name, digest in seal["files"].items():
    assert sha(run / name) == digest, name
state = json.loads((run / "terminal-state.json").read_text())
sources = state["batch"]["trials"][0]["sources"]
ids = {s["id"]: s for s in sources}
handles = {"sh_" + s["id"].removeprefix("source_")[:16]: s["id"] for s in sources}
with sqlite3.connect(
    (run / "workspace-run/.rob2-kit/derivative.sqlite3").as_uri() + "?mode=ro", uri=True
) as db:
    pages = {
        (sid, page): text for sid, page, text in db.execute("SELECT source_id,page,text FROM pages")
    }
selected = [
    ("D3 composite flow/footnote", "nejmoa2022190_appendix.pdf", 28),
    ("D5 original signed SAP cover", "nejmoa2022190_protocol.pdf", 232),
    ("D5 original primary methods", "nejmoa2022190_protocol.pdf", 265),
    ("D5 original primary sensitivity continuation", "nejmoa2022190_protocol.pdf", 266),
    ("D5 original censoring", "nejmoa2022190_protocol.pdf", 262),
    ("D5 original censoring continuation", "nejmoa2022190_protocol.pdf", 263),
    ("D5 revised changes/reasons", "Current registry-linked sap: SAP_001.pdf", 11),
    ("D5 revised endpoints", "Current registry-linked sap: SAP_001.pdf", 12),
    ("D5 revised estimand/primary", "Current registry-linked sap: SAP_001.pdf", 36),
    ("D5 revised primary continuation", "Current registry-linked sap: SAP_001.pdf", 37),
    ("D5 revised primary covariates/estimator", "Current registry-linked sap: SAP_001.pdf", 38),
    ("D5 revised censoring", "Current registry-linked sap: SAP_001.pdf", 32),
    ("D5 revised censoring continuation", "Current registry-linked sap: SAP_001.pdf", 33),
    ("D5 history", "Current registry-linked sap: SAP_001.pdf", 68),
    ("D5 history continuation", "Current registry-linked sap: SAP_001.pdf", 69),
    ("D5 June history", "Current registry-linked sap: SAP_001.pdf", 70),
    ("D5 June signatures", "nejmoa2022190_protocol.pdf", 360),
]
receipts = []


def walk(value, path, inherited, event_line, item):
    if isinstance(value, dict):
        sid = value.get("source_id", inherited)
        sid = handles.get(sid, sid)
        page = value.get("page")
        if sid in ids and isinstance(page, int):
            lines = pages[sid, page].splitlines()
            for field in ("numbered_text", "quote", "preview"):
                body = value.get(field)
                if not isinstance(body, str):
                    continue
                if field == "numbered_text":
                    parsed = [re.fullmatch(r"(\d+)\|(.*)", line) for line in body.splitlines()]
                    assert parsed and all(parsed), (item["id"], path)
                    numbers = [int(m[1]) for m in parsed]
                    exact = all(lines[int(m[1]) - 1] == m[2] for m in parsed)
                    first, last = min(numbers), max(numbers)
                    full_lines = exact and numbers == list(range(first, last + 1))
                else:
                    first, last = value.get("start_line"), value.get("end_line")
                    if not isinstance(first, int) or not isinstance(last, int):
                        continue
                    expected = "\n".join(lines[first - 1 : last])
                    full_lines = body.rstrip("\r\n") == expected
                    exact = full_lines or body.rstrip("\r\n") in expected
                receipts.append(
                    {
                        "source_id": sid,
                        "page": page,
                        "start_line": first,
                        "end_line": last,
                        "tool": item["tool"],
                        "call_id": item["id"],
                        "events_jsonl_line": event_line,
                        "json_pointer": path + "/" + field,
                        "text_field": field,
                        "literal_text_matches": exact,
                        "complete_lines_verified": full_lines,
                        "text_sha256": hashlib.sha256(body.encode()).hexdigest(),
                    }
                )
        for key, child in value.items():
            walk(
                child, path + "/" + key.replace("~", "~0").replace("/", "~1"), sid, event_line, item
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, path + "/" + str(index), inherited, event_line, item)


visual = []
requests = []
for line_number, line in enumerate((run / "events.jsonl").read_text().splitlines(), 1):
    event = json.loads(line)
    item = event.get("item", {})
    if event["type"] != "item.completed" or item.get("type") != "mcp_tool_call":
        continue
    if item["tool"] in {
        "read_pages",
        "search_sources",
        "search_sources_batch",
        "get_domain_context",
    }:
        walk(
            item.get("result", {}).get("structured_content"),
            "/item/result/structured_content",
            None,
            line_number,
            item,
        )
        requests.append(
            {
                "tool": item["tool"],
                "call_id": item["id"],
                "events_jsonl_line": line_number,
                "arguments": item["arguments"],
            }
        )
    if item["tool"] in {"render_page", "select_visual_evidence"}:
        visual.append(
            {
                "tool": item["tool"],
                "call_id": item["id"],
                "events_jsonl_line": line_number,
                "arguments": item["arguments"],
                "status": item["status"],
            }
        )
result = []
texts = []
for purpose, label, page in selected:
    source = next(s for s in sources if s["label"] == label)
    sid = source["id"]
    text = pages[sid, page]
    lines = text.splitlines()
    hits = [r for r in receipts if r["source_id"] == sid and r["page"] == page]
    covered = set()
    for hit in hits:
        if hit["complete_lines_verified"]:
            covered.update(range(hit["start_line"], hit["end_line"] + 1))
    result.append(
        {
            "purpose": purpose,
            "source_id": sid,
            "source_handle": "sh_" + sid.removeprefix("source_")[:16],
            "source_label": label,
            "source_sha256": source["sha256"],
            "projection_hash": source["projection_hash"],
            "focus_windows": [{"start_line": 11, "end_line": 16}]
            if purpose == "D3 composite flow/footnote"
            else [],
            "physical_page": page,
            "start_line": 1,
            "end_line": len(lines),
            "page_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "all_page_lines_delivered_in_run": set(range(1, len(lines) + 1)) <= covered,
            "delivered_complete_lines": sorted(covered),
            "receipts": hits,
            "reviewer_text_reference": "reviewer-passages.json#/passages/" + str(len(texts)),
            "not_delivered_note": None
            if hits
            else (
                "No matching read/search/context text receipt in this session. "
                "Presence, requests, inherited preparation receipts and metadata are not reading."
            ),
        }
    )
    texts.append(
        {
            "purpose": purpose,
            "source_id": sid,
            "physical_page": page,
            "page_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "numbered_lines": [f"{i}|{line}" for i, line in enumerate(lines, 1)],
        }
    )
meta = {
    "session_id": json.loads((run / "exit.json").read_text())["session_id"],
    "events_sha256": sha(run / "events.jsonl"),
    "raw_seal_sha256": sha(run / "outputs-freeze-final.json"),
    "method": (
        "Completed structured text bodies only; exact physical-line comparison; "
        "request/metadata never counts as delivery. Partial previews retained separately. "
        "Visual delivery not promoted to text-line coverage. "
        "Inherited seed/preparation reading excluded from session delivery."
    ),
    "passages": result,
    "visual_calls": visual,
}
(out / "delivery-map.json").write_text(json.dumps(meta, indent=2) + "\n")
(out / "reviewer-passages.json").write_text(
    json.dumps(
        {
            "scope": (
                "17 selected physical pages, not the full 756-page corpus; "
                "frozen projected text, not PDF layout"
            ),
            "passages": texts,
        },
        indent=2,
    )
    + "\n"
)
(out / "request-index.json").write_text(json.dumps(requests, indent=2) + "\n")
for name, digest in seal["files"].items():
    assert sha(run / name) == digest, name
print(
    json.dumps(
        [
            {
                "purpose": x["purpose"],
                "page": x["physical_page"],
                "text_receipts": len(x["receipts"]),
                "all_lines_delivered": x["all_page_lines_delivered_in_run"],
            }
            for x in result
        ],
        indent=2,
    )
)
