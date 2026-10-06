"""Inventory existing heads read-only; export current skill without staging fake history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from rob2_kit.interfaces.cli.app import main

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
D = ROOT.parent / "diagnostics"
CODE = Path("/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


paths = [
    D / "exscel-continuity-verdict/workspace/.rob2-kit/canonical.sqlite3",
    D / "frozen-exscel-bd92ec8/workspace/.rob2-kit/canonical.sqlite3",
    D / "gupta-validation-fcd83d7/workspace/.rob2-kit/canonical.sqlite3",
    ROOT / "docs/evaluation/2026-10-03-gupta-full-validation/canonical.sqlite3",
    CODE / "dapa-hf/.rob2-kit/canonical.sqlite3",
    CODE / "stopdapt-3/.rob2-kit/canonical.sqlite3",
]
rows = []
for path in paths:
    before = digest(path)
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        revision, raw = connection.execute("SELECT revision,payload FROM workflow_head").fetchone()
        state = json.loads(raw)
    closures = state.get("trial_closures", {})
    domains = state.get("domain_records", {})
    rows.append(
        {
            "path": str(path),
            "sha256": before,
            "revision": revision,
            "phase": state["phase"],
            "domain_keys": list(domains),
            "trial_dispositions": state.get("trial_dispositions"),
            "closure_identities": {k: v.get("identity") for k, v in closures.items()},
            "acknowledgment_identities": [
                a.get("identity") for a in state.get("acknowledgments", [])
            ],
            "review_stage_editable_candidate": len(domains) == 5 and not closures,
            "original_unchanged": digest(path) == before,
        }
    )
assert all(row["original_unchanged"] for row in rows)
assert not any(row["review_stage_editable_candidate"] for row in rows)
export = D / "optional-review-integration-20261004/rob2-assess"
assert main(["export-skill", "--output", str(export)]) == 0
source = ROOT / "src/rob2_kit/skills/rob2-assess/SKILL.md"
assert source.read_bytes() == (export / "SKILL.md").read_bytes()
result = {
    "model_calls": 0,
    "database_edits": False,
    "heads": rows,
    "supported_review_revision_staging_available_in_checked_copies": False,
    "export_path": str(export),
    "source_skill_sha256": digest(source),
    "exported_skill_sha256": digest(export / "SKILL.md"),
    "export_byte_equality": True,
}
(OUT / "preservation-and-export.json").write_text(json.dumps(result, indent=2) + "\n")
print(
    json.dumps(
        {
            "all_original_heads_unchanged": True,
            "review_staging_available": False,
            "export_byte_equality": True,
        }
    )
)
