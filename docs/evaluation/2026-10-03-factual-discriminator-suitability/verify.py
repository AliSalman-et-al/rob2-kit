"""Verify existing diagnostic metadata and discriminator statements offline."""

import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "docs/evaluation"
OUTPUT = Path(__file__).parent
runs = {
    "recovery": ROOT / "2026-10-03-recovery-d5-production",
    "bendix_source_only": ROOT / "2026-10-03-bendix-source-only",
}
packet = {}
for name, folder in runs.items():
    config_name = "launcher-config.toml" if name == "recovery" else "cli-config.toml"
    config = tomllib.loads((folder / config_name).read_text())
    assert config["model"] == "gpt-6-luna"
    assert config["model_reasoning_effort"] == "medium"
    proof_name = "model-settings.json" if name == "recovery" else "response-proof.json"
    proof = json.loads((folder / proof_name).read_text())
    settings = proof if isinstance(proof, list) else proof["model_settings"]
    assert all(s["model"] == "gpt-6-luna" and s["effort"] == "medium" for s in settings)
    records = json.loads((folder / "durable-token-usage-records.json").read_text())
    assert all("reasoning_output_tokens" in r["usage"] for r in records)
    reasoning = sum(r["usage"]["reasoning_output_tokens"] for r in records)
    run = json.loads((folder / "run.json").read_text())
    assert reasoning == run["usage"]["reasoning_output_tokens"]
    assert reasoning == (3328 if name == "recovery" else 0)
    if name == "recovery":
        submission = json.loads((folder / "model-submission.json").read_text())
        answer = submission["arguments"]["answers"][0]
        assert "Cox" in answer["justification"] and "Fine" in answer["justification"]
        assert answer["answer"] == "probably_yes"
        discriminator = answer
        evidence_file = "model-submission.json"
    else:
        response = (folder / "response.txt").read_text()
        assert "does not establish for every excluded participant" in response
        assert "whether the four-month outcome was unavailable" in response
        assert "**Answer: No.**" in response
        discriminator = response
        evidence_file = "response.txt"
    files = [config_name, proof_name, "durable-token-usage-records.json", "run.json", evidence_file]
    packet[name] = {
        "files_sha256": {
            str(folder / file): hashlib.sha256((folder / file).read_bytes()).hexdigest()
            for file in files
        },
        "recorded_model_settings": settings,
        "response_generations": len(records),
        "reasoning_output_tokens": reasoning,
        "all_response_records_have_explicit_reasoning_field": True,
        "raw_provider_field_availability": "not established by preserved client records",
        "discriminator_already_in_response": discriminator,
    }
(OUTPUT / "verified-records.json").write_text(json.dumps(packet, indent=2) + "\n")
print("Existing discriminator and configuration assertions passed.")
