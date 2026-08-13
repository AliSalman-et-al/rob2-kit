"""The model-free FastMCP boundary."""

import json
import os
import re
from datetime import datetime
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict

from rob2_kit.assessment import Proposal
from rob2_kit.batch import ApproveBatchResult, SaveProposalResult, approve_batch, save_proposal
from rob2_kit.batch import current_batch as load_current_batch
from rob2_kit.finish import FinishTrialResult, finish_trial
from rob2_kit.judgment_models import ActiveAnswer, InactiveQuestion, Override
from rob2_kit.judgments import SaveDomainJudgmentResult, save_domain_judgment
from rob2_kit.models import Judgment
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.registry import RegistryNotCaptured, read_captured_registry


class CurrentBatch(BaseModel):
    """The initial state before batch ingestion exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_batch: Literal[None] = None


mcp = FastMCP("rob2-kit")


@mcp.resource("rob2://current-batch")
def current_batch() -> str:
    """Return the active batch, if one exists."""
    workspace = os.environ.get("ROB2_WORKSPACE")
    return (
        CurrentBatch().model_dump_json()
        if not workspace
        else load_current_batch(workspace).model_dump_json()
    )


@mcp.tool(name="save_proposal")
def save_batch_proposal(proposal: Proposal) -> SaveProposalResult:
    """Save a replaceable complete batch proposal."""
    workspace = os.environ["ROB2_WORKSPACE"]
    return save_proposal(workspace, proposal)


@mcp.tool(name="approve_batch")
def approve_batch_proposal() -> ApproveBatchResult:
    """Atomically approve the one complete current proposal."""
    return approve_batch(os.environ["ROB2_WORKSPACE"])


@mcp.tool(name="save_domain_judgment")
def save_one_domain_judgment(
    trial_id: str,
    result_id: str,
    domain_id: str,
    active_answers: tuple[ActiveAnswer, ...],
    inactive_questions: tuple[InactiveQuestion, ...],
    final_judgment: Judgment | None,
    override: Override | None,
    limitations: tuple[str, ...],
    actor: str,
    observed_at: datetime,
) -> SaveDomainJudgmentResult:
    """Insert one evidence-grounded, immutable Domain checkpoint."""
    return save_domain_judgment(
        os.environ["ROB2_WORKSPACE"],
        trial_id,
        result_id,
        domain_id,
        active_answers,
        inactive_questions,
        final_judgment,
        override,
        limitations,
        actor,
        observed_at,
    )


@mcp.tool(name="finish_trial")
def finish_one_trial(
    trial_id: str,
    final_judgment: Judgment | None,
    override: Override | None,
    combined_concerns: bool | None,
    limitations: tuple[str, ...],
    actor: str,
    observed_at: datetime,
) -> FinishTrialResult:
    """Atomically finish one Trial after all five Domain checkpoints are valid."""
    return finish_trial(
        os.environ["ROB2_WORKSPACE"],
        trial_id,
        final_judgment,
        override,
        combined_concerns,
        limitations,
        actor,
        observed_at,
    )


@mcp.resource("rob2://domain-guidance/{domain_id}")
def domain_guidance(domain_id: str) -> str:
    """Return pinned Domain questions and the separate maintainer-policy identity."""
    domain = next((item for item in SCIENTIFIC_PACK.domains if item.id == domain_id), None)
    if domain is None:
        raise ValueError("unknown domain")
    return json.dumps(
        {
            "domain": domain,
            "questions": [q for q in SCIENTIFIC_PACK.questions if q.id in domain.question_ids],
            "scientific_pack": {
                "id": SCIENTIFIC_PACK.id,
                "version": SCIENTIFIC_PACK.version,
                "content_hash": SCIENTIFIC_PACK.content_hash,
            },
            "policy_pack": {
                "id": MAINTAINER_POLICY_PACK.id,
                "version": MAINTAINER_POLICY_PACK.version,
                "content_hash": MAINTAINER_POLICY_PACK.content_hash,
            },
        },
        default=lambda item: item.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


@mcp.resource("rob2://registry/{trial_id}")
def registry_record(trial_id: str) -> str:
    """Read a validated captured ClinicalTrials.gov record for one Trial."""
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", trial_id) is None:
        raise ValueError("invalid trial identifier")
    workspace = os.environ.get("ROB2_WORKSPACE")
    if not workspace:
        return RegistryNotCaptured(trial_id=trial_id, status="not_captured").model_dump_json()
    return read_captured_registry(workspace, trial_id).model_dump_json()


def main() -> None:
    """Run the stdio MCP server."""
    mcp.run()
