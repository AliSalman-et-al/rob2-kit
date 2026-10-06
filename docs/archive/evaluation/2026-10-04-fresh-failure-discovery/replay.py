"""Read-only October 1 corpus audit and current comparison-card replay."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from rob2_kit.application.domains import _comparison_cards

ROOT = Path("/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases")
OUT = Path(__file__).parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


records = []
for slug in ("monarch-2", "monaleesa-3"):
    case = ROOT / slug
    bundle = next((case / ".rob2-kit/finalized").glob("*.rob2.zip"))
    paths = [bundle, *sorted(case.glob("turn-*.jsonl"))]
    hashes = {str(path): digest(path) for path in paths}
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        evidence = {
            json.loads(archive.read(name))["identity"]: json.loads(archive.read(name))
            for name in archive.namelist()
            if name.startswith("evidence/")
        }
    result = canonical["proposal"]["payload"]["results"][0]
    domains = {
        key: value
        for key, value in canonical["domain_records"].items()
        if any(domain in key for domain in ("deviations", "missing", "selection"))
    }
    receipts = []
    for path in paths[1:]:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            row = json.loads(line)
            item = row.get("item") or {}
            if row["type"] != "item.completed" or item.get("type") != "mcp_tool_call":
                continue
            structured = (item.get("result") or {}).get("structured_content") or {}
            data = structured.get("data", {})
            tool = item.get("tool")
            if tool not in (
                "get_domain_context",
                "read_pages",
                "select_text_evidence",
                "save_domain_judgment",
            ):
                continue
            arguments = item.get("arguments", {})
            if tool == "get_domain_context":
                data = {key: data[key] for key in ("result", "comparison_cards") if key in data}
                if not data:
                    continue
            if tool == "save_domain_judgment" and arguments.get("domain_id") not in (
                "domain:deviations",
                "domain:missing",
                "domain:selection",
            ):
                continue
            receipts.append(
                {
                    "file": path.name,
                    "line": line_number,
                    "item_id": item["id"],
                    "tool": tool,
                    "arguments": arguments,
                    "data": data,
                }
            )
    cards = {
        domain: _comparison_cards(domain, result, {}, [], [])[0]
        for domain in ("domain:deviations", "domain:missing", "domain:selection")
    }
    for card in cards.values():
        assert (
            card["result_scope"]["population"] == result["target"]["intended_analysis_population"]
        )
        assert card["reported_result"] == result["reported"]
        assert card["target_relation"] == result["relation"]
    assert hashes == {str(path): digest(path) for path in paths}
    write(
        slug + ".json",
        {
            "original_hashes": hashes,
            "sources": canonical["batch"]["trials"][0]["sources"],
            "result": result,
            "domains": domains,
            "evidence": evidence,
            "historical_receipts": receipts,
            "current_cards": cards,
        },
    )
    records.append(
        {
            "slug": slug,
            "relation": result["relation"],
            "target_population": result["target"]["intended_analysis_population"],
            "reported_population": result["reported"]["analysis_population"],
            "original_files_unchanged": True,
            "current_three_domain_card_checks": "passed",
        }
    )
write(
    "verification.json",
    {
        "cases_deeply_inspected": records,
        "model_calls": 0,
        "runtime_changes": False,
        "human_reference_used": False,
    },
)
print(json.dumps(records, indent=2))
