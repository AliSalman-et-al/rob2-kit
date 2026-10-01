from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / (
    "eval/runs/2026-09-26/rob2-trial-benchmark-luna-medium/isolated-worktree-run/"
    "rob2-trial-benchmark/overall-survival/ARASENS/phase-2.jsonl"
)
BASELINE_PROMPT_REVISION = "8fa90ed5aec80de8bfc5dfb55e480b7a38f65dd8"
FIXED_CONTEXT_REVISION = "d5528044066bc0300bd96ea4e99c25a35d58f6b0"
DOMAINS_PATH = Path("src/rob2_kit/application/domains.py")
MISSING_GUIDANCE_PATH = Path("src/rob2_kit/skills/rob2-assess/references/missing.md")
TESTED_D3_PROMPT_CANDIDATE = (
    "For 3.1, match observed outcomes and follow-up to the approved Result. "
    "Event and censor counts can sum to an analyzed denominator without establishing "
    "when or why follow-up ended. Use actual outcome-availability evidence for an "
    "affirmative answer; preserve No information when availability remains unknown. "
    "An empty passage group is unopened; inspect relevant Sources before recording "
    "an information limitation."
)
USER_REQUEST = (
    "Assess the risk of bias due to missing outcome data for Overall Survival in ARASENS."
)
CONDITIONS = (("gpt-6-luna", "medium"), ("gpt-6-sol", "high"))
REPEAT_ORDER = (("baseline", "current"), ("current", "baseline"), ("baseline", "current"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_show(revision: str, path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _string_constants(source: str) -> list[str]:
    tree = ast.parse(source)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _extract_arm_prompts(baseline_source: str) -> dict[str, str]:
    baseline_candidates = [
        value
        for value in _string_constants(baseline_source)
        if value.startswith("Use the exact Result scope, passages, and quantities above.")
    ]
    if len(baseline_candidates) != 1:
        raise ValueError("could not identify one baseline card prompt")
    return {
        "baseline": baseline_candidates[0],
        "current": TESTED_D3_PROMPT_CANDIDATE,
    }


def _load_trace(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return records, raw


def _completed_call(
    records: list[dict[str, Any]], item_id: str, tool: str
) -> dict[str, Any]:
    matches = [
        record.get("item", {})
        for record in records
        if record.get("type") == "item.completed"
        and record.get("item", {}).get("id") == item_id
        and record.get("item", {}).get("type") == "mcp_tool_call"
        and record.get("item", {}).get("tool") == tool
    ]
    if len(matches) != 1 or matches[0].get("status") != "completed":
        raise ValueError(f"expected one completed {tool} call at {item_id}")
    return matches[0]


def _data(call: dict[str, Any]) -> dict[str, Any]:
    result = call.get("result", {}).get("structured_content", {})
    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{call.get('tool')} did not return structured data")
    return data


def _trace_context(records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    result_page = _data(_completed_call(records, "item_28", "get_domain_context"))
    question_page = _data(_completed_call(records, "item_29", "get_domain_context"))
    evidence_page = _data(_completed_call(records, "item_30", "get_domain_context"))
    card_page = _data(_completed_call(records, "item_31", "get_domain_context"))

    questions = [*result_page.get("questions", []), *question_page.get("questions", [])]
    if [question.get("id") for question in questions] != [
        "sq:missing:data-available",
        "sq:missing:evidence-unbiased",
        "sq:missing:true-value-dependent",
        "sq:missing:likely-dependent",
    ]:
        raise ValueError("trace does not contain the expected four D3 question cards")
    cards = card_page.get("comparison_cards", [])
    if len(cards) != 1 or cards[0].get("question_id") != "sq:missing:data-available":
        raise ValueError("trace does not contain the expected D3 comparison card")

    excerpts: list[dict[str, Any]] = []
    for item_id in ("item_34", "item_37", "item_38"):
        pages = _data(_completed_call(records, item_id, "read_pages")).get("pages", [])
        excerpts.extend({"trace_item": item_id, **page} for page in pages)
    excerpts.extend(
        {"trace_item": "item_30", **evidence}
        for evidence in evidence_page.get("evidence", [])
        if isinstance(evidence.get("quote"), str) and evidence["quote"].strip()
    )
    visual = _data(_completed_call(records, "item_21", "select_visual_evidence")).get("evidence")
    if not isinstance(visual, dict) or not isinstance(visual.get("transcription"), str):
        raise ValueError("trace does not contain the selected CONSORT figure transcription")
    excerpts.append({"trace_item": "item_21", **visual})

    context = {
        "result": result_page["result"],
        "questions": questions,
        "source_excerpts": excerpts,
        "comparison_card": cards[0],
    }
    answer_call = _completed_call(records, "item_40", "validate_domain_assessment")
    saved_call = _completed_call(records, "item_41", "save_domain_judgment")
    answer = answer_call.get("arguments", {}).get("answers", [None])[0]
    checkpoint = _data(saved_call).get("checkpoint", {})
    evaluator_key = {
        "schema": "rob2-kit.d3-card-prompt-contrast-key.v1",
        "status": "trace_reference_not_gold_standard",
        "recorded_trace_answer": answer,
        "recorded_trace_domain_judgment": checkpoint.get("judgment"),
        "source_review": {
            "classification": "likely_model_error",
            "authorship": "AI source-grounded review; not independent human adjudication",
            "source": "eval/cohorts/2026-09-27-source-audits.json",
            "rationale": (
                "The answer inferred nearly complete availability because deaths plus "
                "censorings equal the analyzed denominators. It acknowledged unknown "
                "censoring reasons. Those counts do not establish that participants with "
                "censored outcomes remained observed. The Low label matches the catalog, "
                "but the warrant is unsupported and the final label is not thereby proven false."
            ),
            "unresolved_facts": [
                "The reasons and timing for censoring are not established by the cited totals."
            ],
        },
        "rubric": [
            (
                "Check whether the response treats event plus censor counts as observed-"
                "participant counts or uses the analysis denominator as proof of ascertainment."
            ),
            (
                "Check whether it distinguishes deaths (events), censored survival records, "
                "analyzed participants, and the randomized population."
            ),
            (
                "Check whether it accurately states the follow-up and censoring information "
                "in the supplied excerpts, without claiming every censored participant was "
                "observed through the data cutoff."
            ),
            (
                "Check whether the conclusion and confidence match the evidence and preserve "
                "the recorded uncertainty about censoring reasons and the excluded randomized "
                "participant."
            ),
            (
                "Do not score an answer label as correct or incorrect until a domain expert "
                "adjudicates the scientific interpretation of censoring for this time-to-event "
                "Result."
            ),
        ],
    }
    return context, evaluator_key


def _fixed_context(context: dict[str, Any]) -> dict[str, Any]:
    fixed = json.loads(json.dumps(context, ensure_ascii=False))
    fixed["comparison_card"].pop("prompt", None)
    return fixed


def _arm_context(context: dict[str, Any], arm_prompt: str) -> dict[str, Any]:
    arm_context = json.loads(json.dumps(context, ensure_ascii=False))
    arm_context["comparison_card"]["prompt"] = arm_prompt
    return arm_context


def _render_prompt(context: dict[str, Any], missing_guidance: str) -> str:
    sections = [
        USER_REQUEST,
        "## Saved Result, D3 question cards, source excerpts, and comparison card",
        (
            "The following JSON is the captured assessment context. Assess the result "
            "from this context."
        ),
        "```json",
        json.dumps(context, ensure_ascii=False, indent=2),
        "```",
        "## Domain 3 reference guidance",
        missing_guidance.rstrip(),
    ]
    return "\n\n".join(sections) + "\n"


def _check_evaluator_key_separation(prompt: str, evaluator_key: dict[str, Any]) -> None:
    recorded_answer = evaluator_key.get("recorded_trace_answer")
    source_review = evaluator_key.get("source_review")
    private_text = [
        recorded_answer.get("justification") if isinstance(recorded_answer, dict) else None,
        source_review.get("classification") if isinstance(source_review, dict) else None,
        source_review.get("rationale") if isinstance(source_review, dict) else None,
    ]
    if any(isinstance(value, str) and value and value in prompt for value in private_text):
        raise ValueError("evaluator-only text appeared in a model input")


def _build_plan() -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    sequence = 0
    for model, effort in CONDITIONS:
        for repeat, arms in enumerate(REPEAT_ORDER, start=1):
            pair_id = f"{model}-{effort}-repeat-{repeat}"
            for arm in arms:
                sequence += 1
                run_id = f"input-{sequence:02d}"
                plan.append(
                    {
                        "run_id": run_id,
                        "pair_id": pair_id,
                        "arm": arm,
                        "model": model,
                        "reasoning_effort": effort,
                        "repeat": repeat,
                        "input_file": f"inputs/{run_id}.txt",
                        "expected_jsonl_log": f"logs/{run_id}.jsonl",
                    }
                )
    return plan


def render_harness(
    trace: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    records, raw_trace = _load_trace(trace)
    context, evaluator_key = _trace_context(records)

    meta = json.loads(trace.with_name("phase-2.meta.json").read_text(encoding="utf-8"))
    fixed_revision = str(meta.get("kit_commit", FIXED_CONTEXT_REVISION))
    fixed_guidance = _git_show(fixed_revision, MISSING_GUIDANCE_PATH)
    baseline_source = _git_show(BASELINE_PROMPT_REVISION, DOMAINS_PATH)
    prompts = _extract_arm_prompts(baseline_source)

    output_dir.mkdir(parents=True)
    (output_dir / "inputs").mkdir()
    (output_dir / "logs").mkdir()
    plan = _build_plan()
    prompt_hashes: dict[str, str] = {}
    fixed_hash = _sha256(
        json.dumps(_fixed_context(context), ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    for item in plan:
        arm_context = _arm_context(context, prompts[item["arm"]])
        prompt = _render_prompt(arm_context, fixed_guidance)
        _check_evaluator_key_separation(prompt, evaluator_key)
        prompt_bytes = prompt.encode("utf-8")
        (output_dir / item["input_file"]).write_bytes(prompt_bytes)
        prompt_hashes[item["run_id"]] = _sha256(prompt_bytes)

    with (output_dir / "run-plan.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for item in plan:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    (output_dir / "evaluator-key.json").write_text(
        json.dumps(evaluator_key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema": "rob2-kit.d3-card-prompt-contrast-harness.v1",
        "purpose": "reasoning_only_diagnostic_not_public_lifecycle_evidence",
        "trace": str(trace),
        "trace_file_sha256": _sha256(raw_trace),
        "trace_metadata_sha256": meta.get("trace_sha256"),
        "trace_kit_commit": fixed_revision,
        "baseline_card_prompt_revision": BASELINE_PROMPT_REVISION,
        "current_card_prompt_origin": (
            "Frozen from the tested candidate in src/rob2_kit/application/domains.py; "
            "retained here so regeneration does not depend on the production prompt."
        ),
        "fixed_reference_guidance": str(MISSING_GUIDANCE_PATH),
        "fixed_reference_guidance_revision": fixed_revision,
        "fixed_reference_guidance_sha256": _sha256(fixed_guidance.encode("utf-8")),
        "baseline_card_prompt": prompts["baseline"],
        "current_card_prompt": prompts["current"],
        "fixed_context_sha256_without_card_prompt": fixed_hash,
        "input_sha256_by_run_id": prompt_hashes,
        "source_excerpt_count": len(context["source_excerpts"]),
        "source_excerpt_trace_items": sorted(
            {item["trace_item"] for item in context["source_excerpts"]}
        ),
        "user_request": USER_REQUEST,
        "run_count": len(plan),
        "plan": plan,
        "model_input_excludes": [
            "evaluator-key.json",
            "recorded labels",
            "saved justification",
            "source-audit classification",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a paired, no-call ARASENS D3 comparison-card prompt harness."
    )
    parser.add_argument("--trace", type=Path, default=TRACE)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "eval/runs/2026-09-27/arasens-os-d3-card-prompt-contrast-final",
    )
    args = parser.parse_args()
    manifest = render_harness(args.trace.resolve(), args.output_dir.resolve())
    summary = {
        key: manifest[key]
        for key in (
            "schema",
            "run_count",
            "source_excerpt_count",
            "fixed_context_sha256_without_card_prompt",
        )
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
