from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / (
    "eval/runs/2026-09-27/issues-472-476-live/runs-v3/CHAARTED/"
    "overall-survival/phase-2.jsonl"
)
BUNDLE = ROOT / (
    "eval/runs/2026-09-27/issues-472-476-live/runs-v3/CHAARTED/"
    "overall-survival/workspace/.rob2-kit/finalized/"
    "cd6cd6dcfaca879581446d715ad32e1439d5f4fc7eebbf53c8e739b793fbdfb9.rob2.zip"
)
REFERENCE = Path("src/rob2_kit/skills/rob2-assess/references/missing.md")
MODEL = "gpt-6-luna"
EFFORT = "medium"
REPEATS = 3
QUESTION_ID = "sq:missing:data-available"
RESULT_CALL_ID = "item_24"
QUESTION_PAGE_CALL_ID = "item_25"
EVIDENCE_PAGE_CALL_ID = "item_26"
CARD_CALL_ID = "item_27"
SOURCE_PAGES_CALL_ID = "item_29"
VISUAL_CALL_ID = "item_32"
ANSWER_CALL_ID = "item_33"
OUTPUT_INSTRUCTIONS = """Return one JSON object with these fields:
{
  "dated_basis": [
    {
      "source": "source label and page or figure",
      "reported_time": "date or follow-up window stated in the source",
      "relation_to_approved_cutoff": "aligned | later | unclear",
      "availability_support": "direct | contextual | none | unclear",
      "reason": "brief, source-grounded explanation"
    }
  ],
  "main_report_statement": {
    "considered": true,
    "relation_to_approved_cutoff": "aligned | later | unclear",
    "availability_support": "direct | contextual | none | unclear",
    "reason": "brief, source-grounded explanation"
  },
  "d3_1_answer": "yes | probably_yes | probably_no | no | no_information",
  "justification": "brief answer rationale"
}

Classify the source basis separately from the answer. Use the supplied Result,
question card, official guidance, comparison card, and excerpts only. Do not
guess missing dates or counts. Return valid JSON without a markdown fence."""
CANDIDATE_PROMPT = (
    "Use the exact Result scope, passages, and quantities above. For each cited "
    "availability passage, identify its stated date or follow-up window and assess "
    "whether that window matches the approved Result. If a passage reports follow-up "
    "at a later date, classify that scope separately from any statement about the "
    "approved Result; do not assume later follow-up counts establish earlier "
    "availability or that a later publication date invalidates an explicitly "
    "cutoff-aligned statement. Then apply the question card and official guidance "
    "to the full evidence. An empty passage group is unopened, not a no-hit; inspect "
    "relevant Sources before recording an information limitation."
)
PAIR_ORDERS = (("baseline", "candidate"), ("candidate", "baseline"), ("baseline", "candidate"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_trace(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return records, raw


def _completed_call(records: list[dict[str, Any]], item_id: str, tool: str) -> dict[str, Any]:
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
    data = call.get("result", {}).get("structured_content", {}).get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{call.get('tool')} did not return structured data")
    return data


def _trace_context(records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    result_page = _data(_completed_call(records, RESULT_CALL_ID, "get_domain_context"))
    question_page = _data(_completed_call(records, QUESTION_PAGE_CALL_ID, "get_domain_context"))
    evidence_page = _data(_completed_call(records, EVIDENCE_PAGE_CALL_ID, "get_domain_context"))
    card_page = _data(_completed_call(records, CARD_CALL_ID, "get_domain_context"))
    source_page = _data(_completed_call(records, SOURCE_PAGES_CALL_ID, "read_pages"))
    visual = _data(_completed_call(records, VISUAL_CALL_ID, "select_visual_evidence"))

    questions = [*result_page.get("questions", []), *question_page.get("questions", [])]
    expected_ids = [
        "sq:missing:data-available",
        "sq:missing:evidence-unbiased",
        "sq:missing:true-value-dependent",
        "sq:missing:likely-dependent",
    ]
    if [question.get("id") for question in questions] != expected_ids:
        raise ValueError("trace does not contain the expected four D3 question cards")
    cards = [
        card
        for card in card_page.get("comparison_cards", [])
        if card.get("question_id") == QUESTION_ID
    ]
    if len(cards) != 1:
        raise ValueError("trace does not contain one D3.1 comparison card")

    excerpts: list[dict[str, Any]] = []
    for call_id, data in (
        (RESULT_CALL_ID, result_page),
        (EVIDENCE_PAGE_CALL_ID, evidence_page),
    ):
        for evidence in data.get("evidence", []):
            quote = evidence.get("quote")
            if isinstance(quote, str) and quote.strip():
                excerpts.append({"trace_item": call_id, **evidence})
    for page in source_page.get("pages", []):
        excerpts.append(
            {
                "trace_item": SOURCE_PAGES_CALL_ID,
                "source_id": page.get("source_id"),
                "page": page.get("page"),
                "numbered_text": page.get("numbered_text"),
            }
        )
    figure = visual.get("evidence")
    if not isinstance(figure, dict) or not isinstance(figure.get("transcription"), str):
        raise ValueError("trace does not contain the D3.1 CONSORT transcription")
    excerpts.append({"trace_item": VISUAL_CALL_ID, **figure})

    context = {
        "result": result_page["result"],
        "questions": questions,
        "official_guidance": [
            result_page.get("official_guidance"),
            question_page.get("official_guidance"),
        ],
        "source_excerpts": excerpts,
        "comparison_card": cards[0],
    }

    saved_answers = _completed_call(records, ANSWER_CALL_ID, "save_domain_judgment").get(
        "arguments", {}
    ).get("answers", [])
    recorded_answer = next(
        (answer for answer in saved_answers if answer.get("question_id") == QUESTION_ID), None
    )
    if recorded_answer is None:
        raise ValueError("trace does not contain the saved D3.1 answer")
    evaluator_key = {
        "schema": "rob2-kit.chaarted-d3-temporal-contrast-key.v1",
        "status": "source_grounded_diagnostic_not_expert_adjudication",
        "recorded_trace_answer": recorded_answer,
        "recorded_domain_judgment": {
            "domain_answer": "low",
            "overall_label": "low",
            "bundle_sha256": "8cd95f880bb71eda6cae9df462eb6e83cca48d523fd8b7545e9fc5ce061caee3",
        },
        "source_review": {
            "classification": "dated_basis_warrant_concern; final_label_unresolved",
            "rationale": (
                "The saved answer cites the supplement's ASCO-presentation follow-up counts "
                "as direct support for a Result whose OS data cutoff is 2013-12-23. The ASCO "
                "excerpt gives no date, so its counts alone do not establish availability at "
                "that cutoff. Separately, "
                "the main article states all randomized patients were followed and included in "
                "the primary analysis in the passage that specifies the 2013-12-23 cutoff; that "
                "may independently support availability. This diagnostic does not adjudicate "
                "whether the final D3 or overall Low label is correct."
            ),
        },
        "rubric": {
            "dated_basis": (
                "For each cited availability passage, check whether the response states its "
                "date/window and correctly classifies its relation to the approved 2013-12-23 "
                "OS cutoff. The supplement's 2014-12-23 counts are later follow-up. The ASCO "
                "excerpt has no date, so its relation to the approved cutoff is unestablished. "
                "Neither count alone establishes availability at that cutoff."
            ),
            "main_report_preservation": (
                "Check separately whether the response considers the main-article statement "
                "that all randomized patients were followed and included in the primary analysis, "
                "which appears in the passage specifying the approved survival cutoff. Do not "
                "make this source inherit the supplement's later date."
            ),
            "answer_separation": (
                "Record the selected D3.1 answer descriptively. Do not grade the answer or Low "
                "domain/overall label as correct or incorrect without expert adjudication."
            ),
            "pair_gain": (
                "A candidate repeat is a gain only if it improves dated-basis classification "
                "without losing recognition of the separate main-report basis. If all baseline "
                "repeats already meet both criteria, report no measured gain."
            ),
        },
    }
    return context, evaluator_key


def _fixed_context(context: dict[str, Any]) -> dict[str, Any]:
    fixed = json.loads(json.dumps(context, ensure_ascii=False))
    fixed["comparison_card"].pop("prompt", None)
    return fixed


def _arm_context(context: dict[str, Any], prompt: str) -> dict[str, Any]:
    arm_context = json.loads(json.dumps(context, ensure_ascii=False))
    arm_context["comparison_card"]["prompt"] = prompt
    return arm_context


def _render_prompt(context: dict[str, Any], reference: str) -> str:
    sections = [
        "Assess Domain 3, question 3.1 for the approved CHAARTED Overall Survival Result.",
        "## Saved Result, D3 question cards, source excerpts, and comparison card",
        "Use only the supplied assessment context.",
        "```json",
        json.dumps(context, ensure_ascii=False, indent=2),
        "```",
        "## Domain 3 reference guidance",
        reference.rstrip(),
        "## Response format",
        OUTPUT_INSTRUCTIONS,
    ]
    return "\n\n".join(sections) + "\n"


def _check_key_separation(prompt: str, key: dict[str, Any]) -> None:
    private_strings = [
        key.get("recorded_trace_answer", {}).get("justification"),
        key.get("source_review", {}).get("classification"),
        key.get("source_review", {}).get("rationale"),
        *key.get("rubric", {}).values(),
    ]
    if any(isinstance(value, str) and value and value in prompt for value in private_strings):
        raise ValueError("evaluator-only text appeared in a model input")


def _build_plan() -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    sequence = 0
    for repeat, arms in enumerate(PAIR_ORDERS, start=1):
        for arm in arms:
            sequence += 1
            run_id = f"input-{sequence:02d}"
            plan.append(
                {
                    "run_id": run_id,
                    "pair_id": f"gpt-6-luna-medium-repeat-{repeat}",
                    "arm": arm,
                    "repeat": repeat,
                    "model": MODEL,
                    "reasoning_effort": EFFORT,
                    "input_file": f"inputs/{run_id}.txt",
                    "workspace": f"workspaces/{run_id}",
                    "jsonl_log": f"logs/{run_id}.jsonl",
                    "stderr_file": f"logs/{run_id}.stderr.txt",
                }
            )
    return plan


def _cli_args(workspace: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--disable",
        "shell_tool",
        "--disable",
        "standalone_web_search",
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "--disable",
        "remote_plugin",
        "-c",
        'web_search="disabled"',
        "--json",
        "--ephemeral",
        "--model",
        MODEL,
        "-c",
        f'model_reasoning_effort="{EFFORT}"',
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--cd",
        str(workspace.resolve()),
        "-",
    ]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_contrast(trace: Path, output_dir: Path, *, execute: bool = False) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    records, trace_bytes = _load_trace(trace)
    context, evaluator_key = _trace_context(records)
    reference_bytes = (ROOT / REFERENCE).read_bytes()
    reference = reference_bytes.decode("utf-8")
    baseline_prompt = context["comparison_card"].get("prompt")
    if not isinstance(baseline_prompt, str) or not baseline_prompt:
        raise ValueError("captured comparison card has no baseline prompt")
    prompts = {"baseline": baseline_prompt, "candidate": CANDIDATE_PROMPT}
    plan = _build_plan()
    output_dir.mkdir(parents=True)
    for child in ("inputs", "logs", "workspaces"):
        (output_dir / child).mkdir()

    fixed_hash = _sha256(
        json.dumps(_fixed_context(context), ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    manifest: dict[str, Any] = {
        "schema": "rob2-kit.chaarted-d3-temporal-contrast.v1",
        "purpose": "reasoning_only_diagnostic_not_public_lifecycle_evidence",
        "trace": str(trace),
        "trace_sha256": _sha256(trace_bytes),
        "verified_bundle": str(BUNDLE),
        "verified_bundle_sha256": evaluator_key["recorded_domain_judgment"]["bundle_sha256"],
        "baseline_card_prompt": baseline_prompt,
        "candidate_card_prompt": CANDIDATE_PROMPT,
        "candidate_status": "diagnostic_candidate_not_production_guidance",
        "fixed_guidance_path": REFERENCE.as_posix(),
        "fixed_guidance_sha256": _sha256(reference_bytes),
        "fixed_context_sha256_without_card_prompt": fixed_hash,
        "source_excerpt_count": len(context["source_excerpts"]),
        "source_excerpt_trace_items": sorted(
            {excerpt["trace_item"] for excerpt in context["source_excerpts"]}
        ),
        "model": MODEL,
        "reasoning_effort": EFFORT,
        "repeats": REPEATS,
        "run_count": len(plan),
        "strict_config": True,
        "shell_tool_disabled": True,
        "standalone_web_search_disabled": True,
        "plugins_apps_remote_plugins_disabled": True,
        "web_search": "disabled",
        "sandbox": "read-only",
        "fresh_empty_workspace_per_call": True,
        "evaluator_key_file": "evaluator-key.json",
        "model_inputs_exclude": [
            "evaluator key and rubric",
            "recorded answer and saved domain judgment",
            "source-review classification and rationale",
            "arm, pair, and repeat identifiers",
            "expected labels",
        ],
        "execute": execute,
        "input_sha256_at_render": {},
        "runs": [],
    }

    for row in plan:
        model_input = _render_prompt(_arm_context(context, prompts[row["arm"]]), reference)
        _check_key_separation(model_input, evaluator_key)
        payload = model_input.encode("utf-8")
        (output_dir / row["input_file"]).write_bytes(payload)
        (output_dir / row["workspace"]).mkdir()
        row["input_sha256_at_render"] = _sha256(payload)
        manifest["input_sha256_at_render"][row["run_id"]] = _sha256(payload)
        manifest["runs"].append(row)

    _write_json(output_dir / "evaluator-key.json", evaluator_key)
    with (output_dir / "run-plan.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in plan:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest["status"] = "prepared"
    _write_json(output_dir / "manifest.json", manifest)
    if not execute:
        return manifest

    version = subprocess.run(
        ["codex", "--version"], cwd=ROOT, capture_output=True, check=False
    )
    manifest["codex_version"] = version.stdout.decode("utf-8", errors="replace").strip()
    manifest["status"] = "running"
    _write_json(output_dir / "manifest.json", manifest)
    for row in plan:
        payload = (output_dir / row["input_file"]).read_bytes()
        launch_hash = _sha256(payload)
        if launch_hash != row["input_sha256_at_render"]:
            raise ValueError(f"input changed after plan creation: {row['run_id']}")
        row["input_sha256_at_launch"] = launch_hash
        workspace = output_dir / row["workspace"]
        command = _cli_args(workspace)
        row["cli_args"] = command
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                input=payload,
                capture_output=True,
                check=False,
            )
            stdout, stderr = completed.stdout, completed.stderr
            row["return_code"] = completed.returncode
            row["status"] = "completed" if completed.returncode == 0 else "failed"
        except OSError as exc:
            stdout = b""
            stderr = str(exc).encode("utf-8", errors="replace")
            row["return_code"] = None
            row["status"] = "launch_failed"
        (output_dir / row["jsonl_log"]).write_bytes(stdout)
        (output_dir / row["stderr_file"]).write_bytes(stderr)
        row["stdout_sha256"] = _sha256(stdout)
        row["stderr_sha256"] = _sha256(stderr)
        _write_json(output_dir / "manifest.json", manifest)

    manifest["status"] = (
        "completed" if all(row.get("status") == "completed" for row in plan) else "partial"
    )
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run or prepare a paired CHAARTED OS D3.1 temporal-basis contrast."
    )
    parser.add_argument("--trace", type=Path, default=TRACE)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "eval/runs/2026-09-27/chaarted-os-d3-temporal-contrast",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = run_contrast(args.trace.resolve(), args.output_dir.resolve(), execute=args.execute)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in ("schema", "status", "run_count", "source_excerpt_count")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
