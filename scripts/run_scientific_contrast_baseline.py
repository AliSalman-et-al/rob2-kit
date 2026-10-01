from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval/scientific-premise-contrasts-2026-09-27.json"
MODEL = "gpt-6-luna"
EFFORT = "medium"
DOMAIN_SOURCE = ROOT / "src/rob2_kit/application/domains.py"
FIXED_GUIDANCE = {
    "P-2": {
        "reference": ROOT / "src/rob2_kit/skills/rob2-assess/references/deviations.md",
        "question_id": "sq:deviations:context-deviations",
        "proposition": "The trial context caused the protocol-inconsistent change.",
    },
    "P-3": {
        "reference": ROOT / "src/rob2_kit/skills/rob2-assess/references/measurement.md",
        "question_id": "sq:measurement:differential",
        "proposition": "Outcome measurement or detection could differ between groups.",
    },
}
COMPARISON_CARD_PROMPT = (
    "Use the exact Result scope, passages, and quantities above. Classify only the "
    "remaining propositions; do not infer causation, availability, censoring, "
    "measurement influence, plan correspondence, or risk from metadata, arithmetic, "
    "or wording alone. An empty passage group is unopened, not a no-hit; inspect "
    "relevant Sources before recording an information limitation."
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_fixture(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("schema") != "rob2-kit.scientific-premise-contrasts.v1":
        raise ValueError("unexpected scientific contrast fixture schema")
    if fixture.get("model_access") != "model_input_only":
        raise ValueError("fixture does not restrict model access to model_input")
    return fixture


def _plan(
    fixture: dict[str, Any],
    repeats: int,
    model: str,
    effort: str,
    pair_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    inputs = {item["case_id"]: item["model_input"] for item in fixture["model_inputs"]}
    plan: list[dict[str, Any]] = []
    for contrast in fixture["evaluator_key"]["contrasts"]:
        if pair_ids is not None and contrast["pair_id"] not in pair_ids:
            continue
        cases = contrast["cases"]
        if len(cases) != 2 or any(case not in inputs for case in cases):
            raise ValueError(f"contrast {contrast['pair_id']} does not have two model inputs")
        for repeat in range(1, repeats + 1):
            ordered = cases if repeat % 2 else list(reversed(cases))
            for case_id in ordered:
                model_input = inputs[case_id]
                prefix = "/rob2-assess "
                if not model_input.startswith(prefix):
                    raise ValueError(f"{case_id} does not begin with the expected command")
                prompt = model_input.removeprefix(prefix)
                run_id = f"{contrast['pair_id'].lower()}-r{repeat}-{case_id.lower()}"
                plan.append(
                    {
                        "run_id": run_id,
                        "pair_id": contrast["pair_id"],
                        "case_id": case_id,
                        "repeat": repeat,
                        "model": model,
                        "reasoning_effort": effort,
                        "input_file": f"inputs/{run_id}.txt",
                        "workspace": f"workspaces/{run_id}",
                        "jsonl_log": f"logs/{run_id}.jsonl",
                        "stderr_file": f"logs/{run_id}.stderr.txt",
                        "prompt": prompt,
                    }
                )
    return plan


def _add_production_guidance(
    fixture: dict[str, Any], pair_ids: set[str]
) -> tuple[dict[str, Any], dict[str, str]]:
    guided = copy.deepcopy(fixture)
    contrasts = [
        contrast
        for contrast in guided["evaluator_key"]["contrasts"]
        if contrast["pair_id"] in pair_ids
    ]
    case_to_pair = {
        case_id: contrast["pair_id"]
        for contrast in contrasts
        for case_id in contrast["cases"]
    }
    model_inputs = [
        item for item in guided["model_inputs"] if item["case_id"] in case_to_pair
    ]
    hashes: dict[str, str] = {}
    for item in model_inputs:
        pair_id = case_to_pair[item["case_id"]]
        guidance = FIXED_GUIDANCE[pair_id]
        reference_path = Path(guidance["reference"])
        reference_bytes = reference_path.read_bytes()
        reference = reference_bytes.decode("utf-8")
        hashes[str(reference_path.relative_to(ROOT))] = _sha256(reference_bytes)
        prompt = item["model_input"].removeprefix("/rob2-assess ").rstrip()
        item["model_input"] = (
            "/rob2-assess "
            + prompt
            + "\n\n## Current Domain reference guidance\n"
            + reference.rstrip()
            + "\n\n## Active question and comparison card\n"
            + json.dumps(
                {
                    "question_id": guidance["question_id"],
                    "proposition": guidance["proposition"],
                    "prompt": COMPARISON_CARD_PROMPT,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    guided["model_inputs"] = model_inputs
    guided["evaluator_key"]["contrasts"] = contrasts
    used_cases = set(case_to_pair)
    guided["evaluator_key"]["case_expectations"] = {
        case_id: answer
        for case_id, answer in guided["evaluator_key"]["case_expectations"].items()
        if case_id in used_cases
    }
    return guided, hashes


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


def run_baseline(
    fixture_path: Path,
    output_dir: Path,
    *,
    model: str = MODEL,
    effort: str = EFFORT,
    repeats: int = 3,
    execute: bool = False,
    pair_ids: set[str] | None = None,
    include_production_guidance: bool = False,
) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    fixture = _load_fixture(fixture_path)
    guidance_hashes: dict[str, str] = {}
    if include_production_guidance:
        selected = pair_ids or set(FIXED_GUIDANCE)
        if not selected <= set(FIXED_GUIDANCE):
            raise ValueError("production guidance is available only for P-2 and P-3")
        fixture, guidance_hashes = _add_production_guidance(fixture, selected)
        pair_ids = selected
    plan = _plan(fixture, repeats, model, effort, pair_ids)
    output_dir.mkdir(parents=True)
    for child in ("inputs", "logs", "workspaces"):
        (output_dir / child).mkdir()

    manifest: dict[str, Any] = {
        "schema": "rob2-kit.scientific-contrast-baseline-run.v1",
        "purpose": "reasoning_only_diagnostic_not_public_lifecycle_evidence",
        "fixture": str(fixture_path),
        "fixture_sha256": _sha256(fixture_path.read_bytes()),
        "production_guidance": include_production_guidance,
        "production_guidance_sha256": guidance_hashes,
        "comparison_card_prompt": (
            COMPARISON_CARD_PROMPT if include_production_guidance else None
        ),
        "model": model,
        "reasoning_effort": effort,
        "repeats": repeats,
        "strict_config": True,
        "shell_tool_disabled": True,
        "standalone_web_search_disabled": True,
        "web_search": "disabled",
        "sandbox": "read-only",
        "fresh_workspace_per_call": True,
        "evaluator_key_file": "evaluator-key.json",
        "model_inputs_exclude": ["evaluator_key", "pair_id", "expected answers", "expected labels"],
        "execute": execute,
        "run_count": len(plan),
        "input_sha256_at_render": {},
        "runs": [],
    }

    for row in plan:
        prompt_bytes = row.pop("prompt").encode("utf-8")
        input_path = output_dir / row["input_file"]
        input_path.write_bytes(prompt_bytes)
        manifest["input_sha256_at_render"][row["run_id"]] = _sha256(prompt_bytes)
        row["input_sha256_at_render"] = _sha256(prompt_bytes)
        manifest["runs"].append(row)
        workspace = output_dir / row["workspace"]
        workspace.mkdir()

    _write_json(output_dir / "evaluator-key.json", fixture["evaluator_key"])
    with (output_dir / "run-plan.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in manifest["runs"]:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    _write_json(output_dir / "manifest.json", manifest)

    if not execute:
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

    for row in manifest["runs"]:
        workspace = output_dir / row["workspace"]
        input_bytes = (output_dir / row["input_file"]).read_bytes()
        launch_hash = _sha256(input_bytes)
        if launch_hash != row["input_sha256_at_render"]:
            raise ValueError(f"input changed after plan creation: {row['run_id']}")
        row["input_sha256_at_launch"] = launch_hash
        command = _cli_args(model, effort, workspace)
        row["cli_args"] = command
        completed = subprocess.run(
            command,
            cwd=workspace,
            input=input_bytes,
            capture_output=True,
            check=False,
        )
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
        description="Prepare or run a blinded scientific premise baseline comparison."
    )
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default=EFFORT)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pair", action="append", dest="pair_ids")
    parser.add_argument("--include-production-guidance", action="store_true")
    parser.add_argument("--run", action="store_true", help="invoke Codex CLI for each prompt")
    args = parser.parse_args()
    manifest = run_baseline(
        args.fixture.resolve(),
        args.output_dir.resolve(),
        model=args.model,
        effort=args.effort,
        repeats=args.repeats,
        execute=args.run,
        pair_ids=set(args.pair_ids) if args.pair_ids else None,
        include_production_guidance=args.include_production_guidance,
    )
    print(
        json.dumps(
            {"run_count": manifest["run_count"], "status": manifest.get("status", "prepared")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
