from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval/runs/2026-09-27"
TRACE_ROOT = (
    ROOT
    / "eval/runs/2026-09-26/rob2-trial-benchmark-luna-medium/isolated-worktree-run/"
    / "rob2-trial-benchmark/adverse-events/LATITUDE"
)
PHASE1_TRACE = TRACE_ROOT / "phase-1.jsonl"
PHASE2_TRACE = TRACE_ROOT / "phase-2.jsonl"
FIXTURE = ROOT / "eval/scientific-premise-contrasts-2026-09-27.json"
SOURCE_AUDITS = ROOT / "eval/cohorts/2026-09-27-source-audits.json"
MEASUREMENT_REFERENCE = Path("src/rob2_kit/skills/rob2-assess/references/measurement.md")
FIXED_GUIDANCE_REVISION = "d5528044066bc0300bd96ea4e99c25a35d58f6b0"
MODEL = "gpt-6-luna"
EFFORT = "medium"
REPEATS = 3
ARMS = ("baseline", "candidate")
LATITUDE_CASE = "latitude-source-review"
PRESERVATION_CASE = "c68-extra-testing"
USER_REQUEST = (
    "Assess Domain 4, question 4.2 for the supplied adverse-event Result and evidence."
)
BASELINE_PROMPT = (
    "Use the exact Result scope, passages, and quantities above. Classify only the remaining "
    "propositions; do not infer causation, availability, censoring, measurement influence, "
    "plan correspondence, or risk from metadata, arithmetic, or wording alone. An empty "
    "passage group is unopened, not a no-hit; inspect relevant Sources before recording an "
    "information limitation."
)
TESTED_D4_PROMPT_CANDIDATE = (
    "For the approved outcome, compare cumulative opportunity to detect it, not only whether "
    "the grading method and scheduled visits were shared. For adverse events, use the "
    "source-defined safety window, including follow-up after treatment ends, and check whether "
    "unequal time receiving treatment leaves unequal time at risk or under observation. Median "
    "exposure is a reason to examine that link; it does not quantify the observation difference "
    "or establish its effect. State what the sources establish and what remains unknown."
)


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


def _load_trace(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()], raw


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
    result = call.get("result", {}).get("structured_content", {})
    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{call.get('tool')} did not return structured data")
    return data


def _source_excerpt(
    records: list[dict[str, Any]], item_id: str, trace_label: str
) -> list[dict[str, Any]]:
    pages = _data(_completed_call(records, item_id, "read_pages")).get("pages", [])
    if not pages:
        raise ValueError(f"trace item {item_id} contains no source excerpts")
    return [
        {
            "trace_file": trace_label,
            "trace_item": item_id,
            "source_id": page["source_id"],
            "page": page["page"],
            "numbered_text": page["numbered_text"],
        }
        for page in pages
    ]


def _page_window(
    records: list[dict[str, Any]],
    item_id: str,
    trace_label: str,
    page_number: int,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    pages = _data(_completed_call(records, item_id, "read_pages")).get("pages", [])
    page = next((item for item in pages if item.get("page") == page_number), None)
    if page is None:
        raise ValueError(f"trace item {item_id} does not contain page {page_number}")
    lines = [
        line
        for line in page["numbered_text"].splitlines()
        if start_line <= int(line.split("|", 1)[0]) <= end_line
    ]
    if not lines:
        raise ValueError(f"trace item {item_id} has no lines in the requested window")
    return {
        "trace_file": trace_label,
        "trace_item": item_id,
        "source_id": page["source_id"],
        "page": page_number,
        "start_line": start_line,
        "end_line": end_line,
        "numbered_text": "\n".join(lines),
    }


def _latitude_context(
    phase1: list[dict[str, Any]], phase2: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    result_page = _data(_completed_call(phase2, "item_61", "get_domain_context"))
    question_page = _data(_completed_call(phase2, "item_62", "get_domain_context"))
    evidence_page = _data(_completed_call(phase2, "item_63", "get_domain_context"))
    card_page = _data(_completed_call(phase2, "item_64", "get_domain_context"))
    questions = [*result_page.get("questions", []), *question_page.get("questions", [])]
    question_ids = {question.get("id") for question in questions}
    if "sq:measurement:differential" not in question_ids:
        raise ValueError("saved context does not contain the D4 differential-measurement question")
    cards = card_page.get("comparison_cards", [])
    if len(cards) != 1 or cards[0].get("question_id") != "sq:measurement:method-inappropriate":
        raise ValueError("saved context does not contain the expected Domain 4 comparison card")
    if cards[0].get("prompt") != BASELINE_PROMPT:
        raise ValueError("saved trace comparison-card prompt differs from the pinned baseline")

    excerpts = _source_excerpt(phase1, "item_11", "phase-1.jsonl")
    excerpts.append(
        _page_window(phase1, "item_5", "phase-1.jsonl", 4, 53, 76)
    )
    excerpts.extend(_source_excerpt(phase2, "item_68", "phase-2.jsonl"))
    excerpts.extend(
        {"trace_file": "phase-2.jsonl", "trace_item": "item_63", **evidence}
        for evidence in evidence_page.get("evidence", [])
        if isinstance(evidence.get("quote"), str) and evidence["quote"].strip()
    )
    context = {
        "result": result_page["result"],
        "questions": questions,
        "source_excerpts": excerpts,
        "comparison_card": cards[0],
    }

    answer_call = _completed_call(phase2, "item_72", "validate_domain_assessment")
    answer = next(
        (
            item
            for item in answer_call.get("arguments", {}).get("answers", [])
            if item.get("question_id") == "sq:measurement:differential"
        ),
        None,
    )
    if answer is None:
        raise ValueError("saved validation call has no D4 differential-measurement answer")
    judgment_call = _completed_call(phase2, "item_73", "save_domain_judgment")
    checkpoint = _data(judgment_call).get("checkpoint", {})
    sidecars = json.loads(SOURCE_AUDITS.read_text(encoding="utf-8"))
    source_review = next(
        (
            item
            for item in sidecars
            if item.get("case_identity") == "2026-09-26:adverse-events:latitude"
            and item.get("question_identity") == "sq:measurement:differential"
        ),
        None,
    )
    if source_review is None:
        raise ValueError("source-audit sidecar does not contain the LATITUDE D4 review")

    evaluator_key = {
        "schema": "rob2-kit.latitude-d4-card-prompt-contrast-key.v1",
        "status": "source-review_candidate_not_independent_human_adjudication",
        "recorded_trace_answer": answer,
        "recorded_trace_domain_judgment": checkpoint.get("judgment"),
        "source_review": {
            "classification": source_review["classification"],
            "authorship": "AI source-grounded review; not an independent human expert",
            "rationale": source_review["rationale"],
            "unresolved_facts": source_review["unresolved_facts"],
            "follow_up": source_review["follow_up"],
        },
        "rubric": {
            "primary_target": (
                "Determine whether the response compares the source-defined cumulative AE "
                "observation opportunity across groups and avoids treating common methods or "
                "scheduled visits as proof of equal cumulative observation when exposure differs."
            ),
            "preservation_target": (
                "For C-68, retain the distinction between a common fixed window with equal "
                "scheduled visits and intervention-only extra tests that can detect the event."
            ),
            "scoring": [
                "Score the target premise and stated uncertainty separately from the Domain label.",
                (
                    "Accept a qualified answer that identifies the time-at-risk or observation-"
                    "window issue and says per-arm attendance or its effect is not quantified."
                ),
                "Median exposure alone does not prove the magnitude or direction of bias.",
                (
                    "Do not score the final Domain label as wrong solely because it remains Low; "
                    "source-review impact is unresolved."
                ),
                "Reject a candidate that suppresses C-68's extra detection opportunity.",
            ],
        },
    }
    return context, evaluator_key


def _preservation_input(fixture: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    case = next(
        (item for item in fixture["model_inputs"] if item["case_id"] == "C-68"),
        None,
    )
    key = fixture["evaluator_key"]["case_expectations"].get("C-68")
    if case is None or key is None:
        raise ValueError("scientific premise fixture does not contain C-68 preservation case")
    prompt = case["model_input"].removeprefix("/rob2-assess ").rstrip()
    return prompt, key


def _fixed_context(context: dict[str, Any]) -> dict[str, Any]:
    fixed = json.loads(json.dumps(context, ensure_ascii=False))
    fixed["comparison_card"].pop("prompt", None)
    return fixed


def _arm_context(context: dict[str, Any], arm_prompt: str) -> dict[str, Any]:
    arm_context = json.loads(json.dumps(context, ensure_ascii=False))
    arm_context["comparison_card"]["prompt"] = arm_prompt
    return arm_context


def _render_latitude_prompt(context: dict[str, Any], guidance: str) -> str:
    return "\n\n".join(
        [
            USER_REQUEST,
            "## Saved Result, D4 questions, source excerpts, and comparison card",
            (
                "The following JSON is the captured assessment context. Assess the result from "
                "this context."
            ),
            "```json",
            json.dumps(context, ensure_ascii=False, indent=2),
            "```",
            "## Domain 4 reference guidance",
            guidance.rstrip(),
        ]
    ) + "\n"


def _render_preservation_prompt(
    case_input: str,
    guidance: str,
    arm_prompt: str,
) -> str:
    question = {
        "question_id": "sq:measurement:differential",
        "proposition": "Outcome measurement or detection could differ between groups.",
        "prompt": arm_prompt,
    }
    return "\n\n".join(
        [
            case_input,
            "## Domain 4 reference guidance",
            guidance.rstrip(),
            "## Active question and comparison card",
            json.dumps(question, ensure_ascii=False, indent=2),
        ]
    ) + "\n"


def _check_key_separation(prompt: str, key: dict[str, Any]) -> None:
    forbidden: list[str] = []
    recorded = key.get("recorded_trace_answer")
    review = key.get("source_review")
    if isinstance(recorded, dict):
        value = recorded.get("justification")
        if isinstance(value, str) and value:
            forbidden.append(value)
    if isinstance(review, dict):
        forbidden.extend(
            value for value in (review.get("classification"), review.get("rationale"))
            if isinstance(value, str) and value
        )
        rubric = key.get("rubric", {})
        if isinstance(rubric, dict):
            forbidden.extend(
                value for value in rubric.values() if isinstance(value, str) and value
            )
    expectation = key.get("expectation", {})
    if isinstance(expectation, dict):
        value = expectation.get("rationale")
        if isinstance(value, str) and value:
            forbidden.append(value)
    if any(value in prompt for value in forbidden):
        raise ValueError("evaluator-only text appeared in a model input")


def _build_plan(model: str, effort: str, repeats: int) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    sequence = 0
    for case_id in (LATITUDE_CASE, PRESERVATION_CASE):
        for repeat in range(1, repeats + 1):
            ordered = ARMS if repeat % 2 else tuple(reversed(ARMS))
            for arm in ordered:
                sequence += 1
                run_id = f"input-{sequence:02d}"
                plan.append(
                    {
                        "run_id": run_id,
                        "scenario": case_id,
                        "arm": arm,
                        "repeat": repeat,
                        "model": model,
                        "reasoning_effort": effort,
                        "input_file": f"inputs/{run_id}.txt",
                        "workspace": f"workspaces/{run_id}",
                        "jsonl_log": f"logs/{run_id}.jsonl",
                        "stderr_file": f"logs/{run_id}.stderr.txt",
                    }
                )
    return plan


def _cli_args(model: str, effort: str, workspace: Path) -> list[str]:
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
        "-c",
        'web_search="disabled"',
        "--json",
        "--ephemeral",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--cd",
        str(workspace.resolve()),
        "-",
    ]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_contrast(
    output_dir: Path,
    *,
    model: str = MODEL,
    effort: str = EFFORT,
    repeats: int = REPEATS,
    execute: bool = False,
) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    phase1, phase1_bytes = _load_trace(PHASE1_TRACE)
    phase2, phase2_bytes = _load_trace(PHASE2_TRACE)
    latitude, latitude_key = _latitude_context(phase1, phase2)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    preservation_input, preservation_key = _preservation_input(fixture)
    guidance = _git_show(FIXED_GUIDANCE_REVISION, MEASUREMENT_REFERENCE)
    prompts = {"baseline": BASELINE_PROMPT, "candidate": TESTED_D4_PROMPT_CANDIDATE}
    plan = _build_plan(model, effort, repeats)
    keys = {
        "schema": "rob2-kit.latitude-d4-card-prompt-contrast-key.v1",
        "cases": {
            LATITUDE_CASE: latitude_key,
            PRESERVATION_CASE: {
                "status": "provisional_fixture_expectation",
                "case_id": "C-68",
                "expectation": preservation_key,
            },
        },
    }

    if len(plan) != 4 * repeats:
        raise ValueError("unexpected number of planned runs")
    output_dir.mkdir(parents=True)
    for child in ("inputs", "logs", "workspaces"):
        (output_dir / child).mkdir()
    case_context_hashes = {
        LATITUDE_CASE: _sha256(
            json.dumps(_fixed_context(latitude), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ),
        PRESERVATION_CASE: _sha256(preservation_input.encode("utf-8")),
    }
    for row in plan:
        arm_prompt = prompts[row["arm"]]
        if row["scenario"] == LATITUDE_CASE:
            model_prompt = _render_latitude_prompt(
                _arm_context(latitude, arm_prompt), guidance
            )
        else:
            model_prompt = _render_preservation_prompt(
                preservation_input, guidance, arm_prompt
            )
        _check_key_separation(model_prompt, keys["cases"][row["scenario"]])
        payload = model_prompt.encode("utf-8")
        (output_dir / row["input_file"]).write_bytes(payload)
        row["input_sha256_at_render"] = _sha256(payload)
        (output_dir / row["workspace"]).mkdir()

    manifest: dict[str, Any] = {
        "schema": "rob2-kit.latitude-d4-card-prompt-contrast.v1",
        "purpose": "reasoning_only_diagnostic_not_public_lifecycle_evidence",
        "trace_files": {
            "phase-1.jsonl": str(PHASE1_TRACE),
            "phase-1.jsonl_sha256": _sha256(phase1_bytes),
            "phase-2.jsonl": str(PHASE2_TRACE),
            "phase-2.jsonl_sha256": _sha256(phase2_bytes),
        },
        "fixture": str(FIXTURE),
        "fixture_sha256": _sha256(FIXTURE.read_bytes()),
        "fixed_guidance_revision": FIXED_GUIDANCE_REVISION,
        "fixed_guidance_path": MEASUREMENT_REFERENCE.as_posix(),
        "fixed_guidance_sha256": _sha256(guidance.encode("utf-8")),
        "baseline_prompt": BASELINE_PROMPT,
        "candidate_prompt": TESTED_D4_PROMPT_CANDIDATE,
        "candidate_status": "frozen_test_candidate_not_production_guidance",
        "case_context_sha256_without_card_prompt": case_context_hashes,
        "model": model,
        "reasoning_effort": effort,
        "repeats": repeats,
        "run_count": len(plan),
        "strict_config": True,
        "shell_tool_disabled": True,
        "standalone_web_search_disabled": True,
        "web_search": "disabled",
        "sandbox": "read-only",
        "fresh_workspace_per_call": True,
        "evaluator_key_file": "evaluator-key.json",
        "model_inputs_exclude": [
            "evaluator key",
            "source-review classification and rationale",
            "recorded answer and Domain label",
            "expected answers and labels",
            "scenario IDs and arm names",
        ],
        "source_excerpt_count": len(latitude["source_excerpts"]),
        "execute": execute,
        "runs": plan,
    }
    _write_json(output_dir / "evaluator-key.json", keys)
    with (output_dir / "run-plan.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in plan:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    _write_json(output_dir / "manifest.json", manifest)

    if not execute:
        manifest["status"] = "prepared"
        _write_json(output_dir / "manifest.json", manifest)
        return manifest

    version = subprocess.run(
        ["codex", "--version"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    manifest["codex_version"] = version
    manifest["status"] = "running"
    _write_json(output_dir / "manifest.json", manifest)
    for row in plan:
        workspace = output_dir / row["workspace"]
        payload = (output_dir / row["input_file"]).read_bytes()
        launch_hash = _sha256(payload)
        if launch_hash != row["input_sha256_at_render"]:
            raise ValueError(f"input changed after render: {row['run_id']}")
        row["input_sha256_at_launch"] = launch_hash
        command = _cli_args(model, effort, workspace)
        row["cli_args"] = command
        completed = subprocess.run(command, cwd=workspace, input=payload, capture_output=True)
        (output_dir / row["jsonl_log"]).write_bytes(completed.stdout)
        (output_dir / row["stderr_file"]).write_bytes(completed.stderr)
        row["return_code"] = completed.returncode
        row["stdout_sha256"] = _sha256(completed.stdout)
        row["stderr_sha256"] = _sha256(completed.stderr)
        row["status"] = "completed" if completed.returncode == 0 else "failed"
        _write_json(output_dir / "manifest.json", manifest)
        if completed.returncode != 0:
            manifest["status"] = "failed"
            _write_json(output_dir / "manifest.json", manifest)
            raise subprocess.CalledProcessError(completed.returncode, command)
    manifest["status"] = "completed"
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare or run the paired LATITUDE D4 card-prompt diagnostic."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default=EFFORT)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--run", action="store_true", help="invoke Codex CLI for each prompt")
    args = parser.parse_args()
    manifest = run_contrast(
        args.output_dir.resolve(),
        model=args.model,
        effort=args.effort,
        repeats=args.repeats,
        execute=args.run,
    )
    print(
        json.dumps(
            {"run_count": manifest["run_count"], "status": manifest.get("status", "prepared")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
