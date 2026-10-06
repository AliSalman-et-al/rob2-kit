"""Bounded read-only audit of completed Code benchmark text delivery, not correctness."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

CASES = {
    "canvas-program": (139, 582, 640),
    "pioneer-6": (64, 205, 206, 212),
    "emperor-reduced": (262, 263, 321, 322, 323, 358, 359),
    "dapa-hf": (223, 230, 231, 243, 247, 248, 275),
}
TOOLS = {"read_pages", "search_sources", "search_sources_batch", "get_domain_context"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = []
    for case, selected in CASES.items():
        folder = args.benchmark_root / "benchmark-luna6-medium-2026-10-01/cases" / case
        db = folder / ".rob2-kit/derivative.sqlite3"
        before = sha(db)
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
            sources = [
                json.loads(row[0]) for row in connection.execute("SELECT payload FROM source_index")
            ]
            pages = {
                (sid, page): text
                for sid, page, text in connection.execute("SELECT source_id,page,text FROM pages")
            }
        handles = {
            "sh_" + source["id"].removeprefix("source_")[:16]: source["id"] for source in sources
        }
        events = []
        files = sorted(folder.glob("turn-*.jsonl"), key=lambda p: int(p.stem.split("-")[-1]))
        for file in files:
            for number, line in enumerate(file.read_text().splitlines(), 1):
                event = json.loads(line)
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
                    events.append((file.name, number, item))
        accepted = [
            index
            for index, (_, _, item) in enumerate(events)
            if item.get("tool") == "save_domain_judgment"
            and (item.get("arguments") or {}).get("domain_id") == "domain:selection"
            and ((item.get("result") or {}).get("structured_content") or {}).get("outcome")
            == "success"
        ]
        assert accepted, case
        stop = accepted[-1]
        receipts = []
        contexts = []

        def walk(value, path, inherited, file, number, item):
            if isinstance(value, dict):
                sid = handles.get(
                    value.get("source_id", inherited), value.get("source_id", inherited)
                )
                page = value.get("page")
                if (sid, page) in pages:
                    original = pages[sid, page].splitlines()
                    for field in ("numbered_text", "quote", "preview"):
                        body = value.get(field)
                        if not isinstance(body, str) or not body:
                            continue
                        if field == "numbered_text":
                            parsed = [
                                re.fullmatch(r"(\d+)\|(.*)", line) for line in body.splitlines()
                            ]
                            if not all(parsed):
                                continue
                            nums = [int(match[1]) for match in parsed]
                            exact = all(
                                1 <= int(match[1]) <= len(original)
                                and original[int(match[1]) - 1] == match[2]
                                for match in parsed
                            )
                            start, end = min(nums), max(nums)
                            complete = exact and nums == list(range(start, end + 1))
                        else:
                            start, end = value.get("start_line"), value.get("end_line")
                            if not isinstance(start, int) or not isinstance(end, int):
                                continue
                            expected = "\n".join(original[start - 1 : end])
                            complete = body.rstrip("\r\n") == expected
                            exact = complete or body.rstrip("\r\n") in expected
                        receipts.append(
                            {
                                "source_id": sid,
                                "page": page,
                                "start_line": start,
                                "end_line": end,
                                "tool": item["tool"],
                                "call_id": item.get("id"),
                                "file": file,
                                "line": number,
                                "json_pointer": path + "/" + field,
                                "literal_match": exact,
                                "complete_lines": complete,
                                "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                            }
                        )
                for key, child in value.items():
                    walk(child, path + "/" + str(key), sid, file, number, item)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, path + "/" + str(index), inherited, file, number, item)

        for file, number, item in events[:stop]:
            if item.get("tool") in TOOLS:
                structured = (item.get("result") or {}).get("structured_content")
                walk(structured, "/result/structured_content", None, file, number, item)
                if (
                    item["tool"] == "get_domain_context"
                    and (item.get("arguments") or {}).get("domain_id") == "domain:selection"
                ):
                    data = (structured or {}).get("data") or {}
                    contexts.append(
                        {
                            "file": file,
                            "line": number,
                            "call_id": item.get("id"),
                            "data_keys": list(data),
                            "comparison_cards": data.get("comparison_cards"),
                            "questions": data.get("questions"),
                        }
                    )
        source = next(s for s in sources if "protocol.pdf" in s["label"].lower())
        selected_pages = []
        passages = []
        for page in selected:
            text = pages[source["id"], page]
            hits = [r for r in receipts if r["source_id"] == source["id"] and r["page"] == page]
            covered = set()
            for hit in hits:
                if hit["complete_lines"]:
                    covered.update(range(hit["start_line"], hit["end_line"] + 1))
            selected_pages.append(
                {
                    "physical_page": page,
                    "source_id": source["id"],
                    "source_label": source["label"],
                    "source_sha256": source["sha256"],
                    "projection_hash": source["projection_hash"],
                    "source_line_count": len(text.splitlines()),
                    "full_page_delivered_before_save": covered
                    == set(range(1, len(text.splitlines()) + 1)),
                    "delivered_complete_lines": sorted(covered),
                    "receipts": hits,
                }
            )
            passages.append(
                {
                    "physical_page": page,
                    "source_id": source["id"],
                    "numbered_text": "\n".join(
                        f"{i}|{line}" for i, line in enumerate(text.splitlines(), 1)
                    ),
                }
            )
        file, number, last = events[stop]
        output.append(
            {
                "case": case,
                "read_only_db_hash_unchanged": before == sha(db),
                "database_sha256": before,
                "trace_files": {p.name: sha(p) for p in files},
                "delivery_method": (
                    "Completed structured bodies only, literal physical-line verification, "
                    "before last accepted D5 save. Requests and source availability are not "
                    "reading. Partial previews retained separately; no visual reading or "
                    "comprehension claim."
                ),
                "last_accepted_D5_save": {"file": file, "line": number, "call_id": last.get("id")},
                "selected_pages": selected_pages,
            }
        )
        (args.output_dir / (case + "-private-detail.json")).write_text(
            json.dumps(
                {
                    "selected_source_text": passages,
                    "D5_context_deliveries": contexts,
                    "accepted_D5_arguments": last["arguments"],
                },
                indent=2,
            )
            + "\n"
        )
    (args.output_dir / "delivery-audit.json").write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                x["case"]: {
                    p["physical_page"]: len(p["delivered_complete_lines"])
                    for p in x["selected_pages"]
                }
                for x in output
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
