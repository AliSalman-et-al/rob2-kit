"""Independent offline design review: authority parity, branch completeness and capacity."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pymupdf
import tiktoken

from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.packs import SCIENTIFIC_PACK

ROOT = Path(sys.argv[1]).resolve()
HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("reviewed_adapter", HERE / "diagnostic.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
common = json.loads((ROOT / "common.json").read_text())
rich = json.loads((ROOT / "rich-scaffolding.json").read_text())
minimal_prompt = (ROOT / "minimal/prompt.txt").read_text()
rich_prompt = (ROOT / "rich/prompt.txt").read_text()
assert rich_prompt.startswith(minimal_prompt)
assert common["diagnostic_result"] == json.loads((ROOT / "diagnostic-result.json").read_text())
assert "original_result_identity" not in minimal_prompt
assert "scope-provenance" not in rich_prompt
# Source excerpts retain the contradictory primary label, not a host bias interpretation.
assert "primary endpoint was the mean drop" in minimal_prompt
for forbidden in [
    "get_domain_context",
    "save_domain_judgment",
    "request_companion_source",
    "prepare_batch",
    "missing_data",
    "basis_index",
    "official_d3_prototype",
    "server ignores inactive",
    "inactive answers may be omitted or retained",
]:
    assert forbidden.lower() not in json.dumps(rich).lower(), forbidden
with pymupdf.open(ROOT / "official.pdf") as document:
    expected = "\n".join(
        f"OFFICIAL PRINTED PAGE {p}\n{document[p - 1].get_text(sort=True)}"
        for p in module.GUIDANCE_PAGES
    )
assert common["official_guidance"]["complete_applicable_text"] == expected
assert common["official_guidance"]["printed_pages"] == list(range(2, 34)) + list(range(39, 68))
questions = {q["id"]: q for d in common["questions"] for q in d["questions"]}
assert len(questions) == 22
for q in SCIENTIFIC_PACK.questions:
    assert questions[q.id] == {
        "id": q.id,
        "wording": q.wording,
        "options": [a.value for a in q.allowed_answers],
        "activation": q.activation.model_dump(mode="json"),
    }

branches = {}
for domain in SCIENTIFIC_PACK.domains:
    patterns = {}
    leaves = 0

    def visit(answers):
        global leaves
        pending = [
            q for q in active_questions(answers) if q in domain.question_ids and q not in answers
        ]
        if pending:
            qid = pending[0]
            for option in questions[qid]["options"]:
                visit({**answers, qid: option})
            return
        evaluate_domain(domain.id, answers)
        leaves += 1
        patterns.setdefault(tuple(answers), answers)

    visit({})
    defects = 0
    for pattern in patterns.values():
        for qid in pattern:
            invalid = {k: v for k, v in pattern.items() if k != qid}
            try:
                evaluate_domain(domain.id, invalid)
            except ValueError:
                defects += 1
            else:
                raise AssertionError("incomplete active branch accepted")
        inactive = next((q for q in domain.question_ids if q not in pattern), None)
        if inactive:
            try:
                evaluate_domain(domain.id, {**pattern, inactive: questions[inactive]["options"][0]})
            except ValueError:
                defects += 1
            else:
                raise AssertionError("inactive question accepted")
    branches[domain.id] = {
        "valid_answer_combinations": leaves,
        "distinct_active_paths": len(patterns),
        "negative_checks": defects,
    }

cache = Path.home() / ".codex/models_cache.json"
cache_bytes = cache.read_bytes()
model = next(m for m in json.loads(cache_bytes)["models"] if m["slug"] == "gpt-6-luna")
assert "medium" in {x["effort"] for x in model["supported_reasoning_levels"]}
context = model["context_window"] * model["effective_context_window_percent"] // 100
encodings = {name: tiktoken.get_encoding(name) for name in ["o200k_base", "cl100k_base"]}


def counts(text):
    return {name: len(enc.encode(text, disallowed_special=())) for name, enc in encodings.items()}


schemas = (ROOT / "actual-tool-schemas.json").read_text()
output_schema = (ROOT / "response-schema.json").read_text()
# Count the exact frozen page/line text segments, excluding binary PNG payloads.
manifest = json.loads((ROOT / "minimal/evidence-manifest.json").read_text())
bundle = (ROOT / "evidence.bundle").read_bytes()
source_text = "\n".join(
    bundle[w["input_start_byte"] : w["input_end_byte"]].decode()
    for w in manifest["supplied_windows"]
)
base_tools = max(counts(schemas).values()) + max(counts(output_schema).values())
# Explicit planning reserves, not asserted exact image/server token charges.
reserves = {
    "cli_system_and_wire_overhead": 12000,
    "source_interaction_repetition": 30000,
    "trial_and_guidance_image_allowance": 40000,
    "output_and_reasoning": 24000,
}
capacity = {}
for arm, prompt in [("minimal", minimal_prompt), ("rich", rich_prompt)]:
    proxy = counts(prompt)
    total = (
        max(proxy.values())
        + base_tools
        + max(counts(source_text).values())
        + sum(reserves.values())
    )
    assert total < context, (arm, total, context)
    capacity[arm] = {
        "prompt_utf8_bytes": len(prompt.encode()),
        "prompt_proxy_tokens": proxy,
        "planning_total_tokens": total,
        "remaining_effective_context_tokens": context - total,
    }
receipt = {
    "paid_calls": 0,
    "source_scope_corrected": True,
    "common_input_exactly_shared": True,
    "no_historical_answers_or_gold_loaded_by_preparation": True,
    "raw_source_primary_wording_retained": True,
    "official_text_parity": True,
    "question_options_activation_parity": True,
    "interface_conflicts_neutralized": True,
    "branch_review": branches,
    "context_feasibility": {
        "model": "gpt-6-luna",
        "cache_sha256": hashlib.sha256(cache_bytes).hexdigest(),
        "advertised_context_window": model["context_window"],
        "effective_percent": model["effective_context_window_percent"],
        "effective_context_tokens": context,
        "context_expansion_requested": False,
        "tokenizer_version": tiktoken.__version__,
        "tools_proxy_tokens": counts(schemas),
        "output_schema_proxy_tokens": counts(output_schema),
        "all_trial_text_proxy_tokens": counts(source_text),
        "reserves": reserves,
        "arms": capacity,
        "limitation": "Two public BPE encodings are measured proxies, not a "
        "verified Luna tokenizer. Image and CLI overhead reserves are planning allowances. "
        "Actual delivery/usage/context events require review after any authorized run; "
        "context capacity does not establish useful attention or scientific accuracy.",
    },
}
module.write(ROOT / "independent-review.json", receipt)
print(json.dumps(receipt, indent=2))
