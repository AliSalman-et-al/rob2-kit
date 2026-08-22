"""CLI adapter; all workflow facts come from the shared application status."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from getpass import getuser
from pathlib import Path

from rob2_kit.application._state import read_json
from rob2_kit.application.contracts import (
    RecordKind,
    RecordReference,
    ResearcherReviewContinuation,
    ReviewAuthority,
    TransitionReference,
)
from rob2_kit.application.finalization import (
    FinalizationResult,
    finalize_batch,
    verify_finalization_result,
)
from rob2_kit.application.intake import acknowledge_intake
from rob2_kit.application.proposal import acknowledge_proposal
from rob2_kit.application.status import current_status, status_json
from rob2_kit.application.trials import (
    TrialFinishCandidate,
    TrialFinishRequest,
    acknowledge_trial_finish,
    finish_trial,
    prepare_trial_finish,
)
from rob2_kit.launcher import launch_assessment
from rob2_kit.recovery import (
    DiscardActiveBatchRequest,
    current_batch_projection,
    discard_active_batch,
)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="rob2")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("status", "review", "finish", "finalize", "assess", "discard", "mcp"),
        default="status",
    )
    parser.add_argument("--workspace", default=os.environ.get("ROB2_WORKSPACE", "."))
    parser.add_argument("--host", choices=("codex", "claude-code"))
    parser.add_argument("--model")
    parser.add_argument("--prompt-file")
    args = parser.parse_args(argv)
    if args.command == "assess":
        if args.host is None:
            parser.error("assess requires --host codex or --host claude-code")
        prompt = (
            Path(args.prompt_file).read_text(encoding="utf-8")
            if args.prompt_file
            else sys.stdin.read()
        )
        result = launch_assessment(args.workspace, args.host, args.model, prompt)
        if result.output:
            print(result.output, end="")
        if result.error:
            print(result.error, file=sys.stderr)
        return result.exit_code
    if args.command == "discard":
        projection = current_batch_projection(args.workspace)
        reference = projection.approved_batch_ref
        if reference is None:
            parser.error("no unfinished frozen Batch is available to discard")
        confirmation = "I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH"
        confirmation_prompt = (
            f"Discard active Batch {reference.identity}? Type the exact confirmation literal: "
        )
        if input(confirmation_prompt) != confirmation:
            return 1
        reason = input("Reason for researcher discard: ").strip()
        if not reason:
            return 1
        result = discard_active_batch(
            args.workspace,
            DiscardActiveBatchRequest(
                expected_frozen_hash=reference.identity,
                confirmation=confirmation,
                actor=f"cli:{getuser()}",
                observed_at=datetime.now(UTC),
                reason=reason,
            ),
        )
        print(result.model_dump_json())
        return 0 if result.status == "discarded" else 1
    if args.command == "mcp":
        from rob2_kit.interfaces.mcp.server import main as run_mcp

        run_mcp()
        return 0
    if args.command == "review":
        status = current_status(args.workspace)
        continuation = status.continuation
        proposal = read_json(args.workspace, "proposal_review.json")
        if (
            proposal is not None
            and isinstance(continuation, ResearcherReviewContinuation)
            and continuation.purpose == "proposal"
        ):
            reference = RecordReference(
                kind=RecordKind.PROPOSAL_REVIEW,
                identity=proposal["identity"],
                uri=f"rob2://detail/proposal_review/{proposal['identity']}",
            )
            if (
                input("Acknowledge this exact Proposal Review as researcher? [yes/no] ").casefold()
                != "yes"
            ):
                return 1
            acknowledge_proposal(args.workspace, reference, caller=f"cli:{getuser()}")
            print(status_json(args.workspace))
            return 0
        state = read_json(args.workspace, "state.json") or {}
        if (
            isinstance(continuation, ResearcherReviewContinuation)
            and continuation.purpose == "trial_finish"
        ):
            transition = state.get("trial_finish_transition")
            if not isinstance(transition, dict):
                parser.error("no pending Trial finish transition is available")
            if input("Acknowledge this exact Trial terminal? [yes/no] ").casefold() != "yes":
                return 1
            acknowledge_trial_finish(
                args.workspace,
                TransitionReference.model_validate(transition),
                caller=f"cli:{getuser()}",
            )
            print(status_json(args.workspace))
            return 0
        approved_identity = state.get("approved_batch_identity")
        if (
            isinstance(approved_identity, str)
            and not state.get("trial_finish_transition")
            and status.phase.value in {"assessment", "ready_to_finalize"}
        ):
            disposition_text = input("Terminal disposition (needs_input/failed): ").strip()
            if disposition_text not in {"needs_input", "failed"}:
                parser.error("review only prepares needs_input or failed Trial terminals")
            code = input(
                "Reason code: comparator_unavailable, outcome_definition_unclear, "
                "source_evidence_insufficient, verified_server_failure, or researcher_abandonment: "
            ).strip()
            missing_facts = tuple(
                item.strip()
                for item in input("Concrete missing facts, separated by ';': ").split(";")
                if item.strip()
            )
            if not missing_facts:
                return 1
            approved = RecordReference(
                kind=RecordKind.APPROVED_BATCH,
                identity=approved_identity,
                uri=f"rob2://detail/approved_batch/{approved_identity}",
            )
            prepared = prepare_trial_finish(
                args.workspace,
                approved,
                TrialFinishCandidate(
                    disposition=disposition_text,
                    reason=code if disposition_text == "needs_input" else None,
                    failure_cause=code if disposition_text == "failed" else None,
                    missing_facts=missing_facts,
                ),
                caller=f"cli:{getuser()}",
                authority=ReviewAuthority.RESEARCHER,
            )
            print(prepared.candidate.model_dump_json() if prepared.candidate else "")
            if input("Accept this exact Trial terminal? [yes/no] ").casefold() != "yes":
                return 1
            if prepared.transition is None:
                parser.error("Trial finish preparation did not return a transition")
            acknowledge_trial_finish(args.workspace, prepared.transition, caller=f"cli:{getuser()}")
            print(status_json(args.workspace))
            return 0
        plan = read_json(args.workspace, "intake_plan.json")
        if plan is None:
            parser.error("no Intake plan is available")
        reference = RecordReference(
            kind=RecordKind.INTAKE_PLAN,
            identity=plan["identity"],
            uri=f"rob2://detail/intake_plan/{plan['identity']}",
        )
        if input("Acknowledge this exact Intake plan as researcher? [yes/no] ").casefold() != "yes":
            return 1
        acknowledge_intake(
            args.workspace,
            reference,
            ReviewAuthority.RESEARCHER,
            caller=f"cli:{getuser()}",
        )
        print(status_json(args.workspace))
        return 0
    if args.command == "finish":
        state = read_json(args.workspace, "state.json") or {}
        synthesis_identity = str(state.get("synthesis_identity", "")).removeprefix("sha256:")
        synthesis = read_json(args.workspace, f"synthesis-{synthesis_identity}.json")
        if synthesis is None:
            parser.error("no pending Trial synthesis is available")
        transition_raw = state.get("trial_finish_transition")
        if not isinstance(transition_raw, dict):
            parser.error("no pending Trial finish transition is available")
        transition = TransitionReference.model_validate(transition_raw)
        candidate = state.get("trial_finish_candidate")
        if candidate is None:
            parser.error("the pending Trial finish candidate is unavailable")
        print(json.dumps(candidate, sort_keys=True))
        if input("Accept this exact Trial finish candidate? [yes/no] ").casefold() != "yes":
            return 1
        acknowledgment = acknowledge_trial_finish(
            args.workspace, transition, caller=f"cli:{getuser()}"
        )
        finish_trial(
            args.workspace,
            TrialFinishRequest(transition=transition, acknowledgment=acknowledgment),
            caller=f"cli:{getuser()}",
        )
        print(status_json(args.workspace))
        return 0
    if args.command == "finalize":
        result = finalize_batch(args.workspace)
        print(result.model_dump_json())
        if result.outcome != "success":
            return 1
        saved = FinalizationResult.model_validate(result)
        return 0 if verify_finalization_result(args.workspace, saved) else 1
    print(status_json(args.workspace))
    return 0


if __name__ == "__main__":
    sys.exit(main())
