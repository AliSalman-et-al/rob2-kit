"""Recount local September 27 traces and frozen provisional score vectors."""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parents[3]
    root = repo / "eval/runs/2026-09-27"
    campaigns = {}
    hashes = defaultdict(list)
    for campaign in sorted(root.iterdir()):
        if not campaign.is_dir():
            continue
        files = sorted(campaign.rglob("*.jsonl"))
        statuses, tools, errors = Counter(), Counter(), []
        for path in files:
            raw = path.read_bytes()
            hashes[hashlib.sha256(raw).hexdigest()].append(str(path.relative_to(root)))
            for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    errors.append([str(path.relative_to(root)), line_number])
                    continue
                item = event.get("item", {})
                if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
                    statuses[item.get("status", "unknown")] += 1
                    tools[item.get("tool", "unknown")] += 1
        campaigns[campaign.name] = {
            "segments": len(files),
            "malformed_lines": errors,
            "mcp_status": dict(statuses),
            "mcp_tools": dict(tools),
        }
    fresh = root / "rob2-trial-benchmark-fresh-4e03e798"
    cases = json.loads((fresh / "scores.json").read_text(encoding="utf-8"))["cases"]
    domains = [f"D{i}" for i in range(1, 6)]
    matches = {d: sum(c["expected"][d] == c["observed"][d] for c in cases) for d in domains}
    reference = Counter(c["expected"][d] for c in cases for d in domains)
    observed = Counter(c["observed"][d] for c in cases for d in domains)
    scope = Counter(
        (c.get("scope_adjudication") or {}).get("observed_relation", "none") for c in cases
    )
    result = {
        "campaigns": campaigns,
        "duplicate_logs": [v for v in hashes.values() if len(v) > 1],
        "fresh": {
            "cases": len(cases),
            "domain_matches": matches,
            "domain_exact": sum(matches.values()),
            "domain_denominator": len(cases) * 5,
            "reference_classes": dict(reference),
            "observed_classes": dict(observed),
            "scope_adjudications": sum(bool(c.get("scope_adjudication")) for c in cases),
            "proposal_relations_in_adjudications": dict(scope),
            "overall_exact": sum(
                c["expected"]["overall"] == c["observed"]["overall"] for c in cases
            ),
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
