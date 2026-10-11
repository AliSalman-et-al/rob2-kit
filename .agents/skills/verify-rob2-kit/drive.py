"""Drive the real rob2 MCP server through a synthetic scenario and keep the evidence.

usage: uv run python .agents/skills/verify-rob2-kit/drive.py SCENARIO [--keep-workspace]

Scenarios:
  assess        one low-risk trial: prepare, read, propose, approve with `rob2 review`,
                five Domains, close, finalize, then `rob2 verify` and scripts/verify_bundle.py
  codex-render  `rob2 mcp-codex`: render_page returns PNG pixels beside a text receipt
                that select_visual_evidence accepts

Evidence goes to .verify-evidence/<UTC time>-<scenario>/ in the repository:
  transcript.jsonl  every tool call: {"tool", "arguments", "result"}
  outcome.json      the scenario's observed end state
  *.rob2.zip        the finalized bundle (assess)
The temporary workspace is deleted unless --keep-workspace copies it there too.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "tests"), str(REPO)]

from e2e import trial  # noqa: E402
from e2e.agent import Agent, rob2  # noqa: E402
from e2e.test_assessment import OUTCOME, low_risk_answers, selection  # noqa: E402


def assess(workspace: Path, evidence: Path, agent: Agent) -> dict[str, Any]:
    agent.prepare(OUTCOME)
    agent.read_required()
    agent.propose(selection(agent))
    agent.approve()  # the researcher's `rob2 review` with "yes" on stdin
    agent.read_required()
    judgments = {}
    for domain_id, answers in low_risk_answers(agent).items():
        assert agent.context()["domain_id"] == domain_id
        saved = agent.save_domain(domain_id, answers)
        assert saved["outcome"] == "success", saved
        judgments[domain_id] = saved["data"]["checkpoint"]["judgment"]
    agent.close_trials()
    finalized = agent.finalize()
    bundle = workspace / finalized["data"]["artifact"]["path"]
    shutil.copy2(bundle, evidence / bundle.name)
    product = rob2(workspace, "verify", str(bundle))
    standalone = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(bundle)],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    return {
        "domain_judgments": judgments,
        "assessment_summary": finalized["data"]["assessment_summary"],
        "bundle": bundle.name,
        "rob2_verify": {"exit": product.returncode, "stdout": product.stdout.strip()},
        "standalone_verify": {"exit": standalone.returncode, "stdout": standalone.stdout.strip()},
        "status_phase": agent.ok("get_status")["head"]["phase"],
    }


def codex_render(workspace: Path, evidence: Path, agent: Agent) -> dict[str, Any]:
    agent.prepare(OUTCOME)
    source = agent.sources["main_article"]
    tool = agent.tools()["render_page"]
    result = agent.raw("render_page", {"trial_id": agent.trial_id, "source_id": source, "page": 2})
    blocks = [block.model_dump(mode="json", exclude={"data"}) for block in result.content]
    image = next(block for block in result.content if block.type == "image")
    (evidence / "page-2.png").write_bytes(__import__("base64").b64decode(image.data))
    receipt = json.loads(result.content[0].text)
    cited = agent.ok(
        "select_visual_evidence",
        {
            "trial_id": agent.trial_id,
            "source_id": source,
            "delivery_receipt": receipt["data"]["delivery_receipt"],
            "transcription": "Table 2: recurrent stroke 31/602 apixaban, 52/602 aspirin.",
        },
    )
    return {
        "advertised_output_schema": tool.output_schema,
        "structured_content": result.structured_content,
        "content_blocks": blocks,
        "visual_evidence_handle": cited["data"]["evidence"]["handle"],
    }


SCENARIOS = {"assess": ("mcp", assess), "codex-render": ("mcp-codex", codex_render)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = REPO / ".verify-evidence" / f"{stamp}-{args.scenario}"
    evidence.mkdir(parents=True)
    workspace = Path(tempfile.mkdtemp(prefix="rob2-verify-"))
    entrypoint, run = SCENARIOS[args.scenario]
    trial.build(workspace)
    agent = Agent(workspace, server=entrypoint)
    outcome: dict[str, Any] = {"scenario": args.scenario, "workspace": str(workspace)}
    try:
        outcome |= run(workspace, evidence, agent)
        outcome["passed"] = True
    except Exception as error:  # keep whatever was observed before the failure
        outcome |= {"passed": False, "error": f"{type(error).__name__}: {error}"}
    finally:
        agent.close()
        with (evidence / "transcript.jsonl").open("w", encoding="utf-8") as stream:
            for tool, arguments, result in agent.calls:
                record = {"tool": tool, "arguments": arguments, "result": result}
                stream.write(json.dumps(record) + "\n")
        (evidence / "outcome.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        if args.keep_workspace:
            shutil.copytree(workspace, evidence / "workspace")
        shutil.rmtree(workspace, ignore_errors=True)
    print(evidence)
    print("PASSED" if outcome["passed"] else f"FAILED: {outcome['error']}")
    return 0 if outcome["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
