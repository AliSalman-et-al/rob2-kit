"""Isolated-run and one-attempt release-gate bookkeeping.

The harness only creates metadata. Hosts run separately; this keeps private
Sources, prompts, and host credentials outside the retained public evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

EXPECTED_TOOLS = (
    "preflight_sources",
    "inspect_candidate_sources",
    "save_intake_plan",
    "capture_batch",
    "list_sources",
    "retrieve_evidence",
    "render_page",
    "save_proposal",
    "approve_batch",
    "validate_domain_judgment",
    "commit_domain_judgment",
    "prepare_trial_finish",
    "finish_trial",
    "finalize_batch",
    "read_record",
)
EXPECTED_RESOURCES = (
    "rob2://current-batch",
    "rob2://detail/{kind}/{identity}",
    "rob2://registry/{trial_id}",
    "rob2://render/{identity}",
)
RESTART_DOSSIER_FILES = (
    "preflight.json",
    "intake_plan.json",
    "captured_batch.json",
    "proposal_review.json",
)


def _hash(value: object) -> str:
    return (
        "sha256:"
        + sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


@dataclass(frozen=True)
class ZeroSourceAttestation:
    wheel_hash: str
    mcp_identity: str
    tool_names: tuple[str, ...]
    resource_uris: tuple[str, ...]
    skill_names: tuple[str, ...]
    state_empty: bool
    observed_model: str

    def verify(self, expected_wheel_hash: str | None = None) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.wheel_hash.startswith("sha256:"):
            failures.append("installed wheel hash is missing")
        if expected_wheel_hash is not None and self.wheel_hash != expected_wheel_hash:
            failures.append("installed wheel hash differs from candidate")
        if not self.mcp_identity:
            failures.append("MCP identity is missing")
        if tuple(self.tool_names) != EXPECTED_TOOLS:
            failures.append("zero-source attestation has an unexpected MCP tool contract")
        if tuple(self.resource_uris) != EXPECTED_RESOURCES:
            failures.append("zero-source attestation has an unexpected MCP resource contract")
        if set(self.skill_names) != {"rob2-workflow", "rob2-signalling"}:
            failures.append("zero-source attestation requires both packaged skills")
        if not self.state_empty:
            failures.append("workspace was not empty before Source access")
        if "haiku" not in self.observed_model.casefold():
            failures.append("observed model is not Haiku")
        return tuple(failures)


@dataclass(frozen=True)
class IsolatedRun:
    outcome: str
    workspace_id: str
    project_id: str
    server_id: str
    mcp_identity: str
    source_hashes: tuple[str, ...]
    config_before_hash: str
    config_after_hash: str | None = None
    restart_dossier: tuple[tuple[str, str], ...] = ()
    proposal_review: str | None = None
    review_authority_required: str | None = None
    transition: str | None = None
    continuation: str | None = None

    @classmethod
    def create(
        cls,
        outcome: str,
        source_hashes: tuple[str, ...],
        config: object,
        *,
        restart_dossier: dict[str, str] | None = None,
        proposal_review: str | None = None,
        review_authority_required: str | None = None,
        transition: str | None = None,
        continuation: str | None = None,
    ) -> IsolatedRun:
        dossier = tuple(sorted((restart_dossier or {}).items()))
        if tuple(name for name, _digest in dossier) != tuple(sorted(RESTART_DOSSIER_FILES)):
            raise ValueError("restart dossier must contain the exact four workflow records")
        if not all(
            isinstance(value, str) and value.startswith("sha256:")
            for _name, value in dossier
        ) or not all((proposal_review, review_authority_required, transition, continuation)):
            raise ValueError("restart dossier is missing required review authority or continuation")
        nonce = uuid4().hex
        return cls(
            outcome,
            f"workspace-{nonce}",
            f"project-{nonce}",
            f"server-{nonce}",
            f"rob2-{nonce}",
            tuple(sorted(source_hashes)),
            _hash(config),
            restart_dossier=dossier,
            proposal_review=proposal_review,
            review_authority_required=review_authority_required,
            transition=transition,
            continuation=continuation,
        )

    def complete(self, config: object) -> IsolatedRun:
        return IsolatedRun(
            outcome=self.outcome,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            server_id=self.server_id,
            mcp_identity=self.mcp_identity,
            source_hashes=self.source_hashes,
            config_before_hash=self.config_before_hash,
            config_after_hash=_hash(config),
            restart_dossier=self.restart_dossier,
            proposal_review=self.proposal_review,
            review_authority_required=self.review_authority_required,
            transition=self.transition,
            continuation=self.continuation,
        )

    def restart_reference(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "mcp_identity": self.mcp_identity,
            "source_hashes": self.source_hashes,
            "restart_dossier": self.restart_dossier,
            "proposal_review": self.proposal_review,
            "review_authority_required": self.review_authority_required,
            "transition": self.transition,
            "continuation": self.continuation,
        }

    def verify_restart(self, reference: dict[str, object]) -> tuple[str, ...]:
        expected = self.restart_reference()
        return tuple(
            f"restart {key} does not rehydrate the exact run"
            for key, value in expected.items()
            if reference.get(key) != value
        )


class AttemptLedger:
    """Durable one-retry ledger for interruptions proven before host behaviour."""

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("attempt ledger is corrupt")
        return value

    def start(self, outcome: str) -> str:
        rows = self._read()
        prior = [row for row in rows if row.get("outcome") == outcome]
        if len(prior) >= 2 or (
            prior
            and not all(
                row.get("external_interruption") is True
                and row.get("before_behavior") is True
                for row in prior
            )
        ):
            raise ValueError(f"one clean attempt already exists for {outcome}")
        attempt_id = uuid4().hex
        rows.append(
            {
                "attempt_id": attempt_id,
                "outcome": outcome,
                "external_interruption": None,
                "before_behavior": None,
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")
        return attempt_id

    def record_external_interruption(self, attempt_id: str, before_behavior: bool) -> None:
        """Record the only retryable failure class on an already-started attempt."""
        if not before_behavior:
            raise ValueError("an interruption after behavior cannot permit a retry")
        rows = self._read()
        matches = [row for row in rows if row.get("attempt_id") == attempt_id]
        if len(matches) != 1:
            raise ValueError("attempt is unavailable")
        row = matches[0]
        if row.get("external_interruption") is not None:
            raise ValueError("attempt interruption is already recorded")
        row["external_interruption"] = True
        row["before_behavior"] = True
        self.path.write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")


def verify_run_matrix(runs: tuple[IsolatedRun, ...]) -> tuple[str, ...]:
    """Require exactly the three isolated outcomes and one shared source inventory."""

    failures: list[str] = []
    expected = {"pfs", "overall_survival", "adverse_events"}
    if {run.outcome for run in runs} != expected or len(runs) != 3:
        failures.append(
            "release gate requires exactly PFS, overall survival, and adverse-events runs"
        )
    for field in ("workspace_id", "project_id", "server_id", "mcp_identity"):
        if len({getattr(run, field) for run in runs}) != len(runs):
            failures.append(f"release runs do not have unique {field}")
    if runs and any(run.source_hashes != runs[0].source_hashes for run in runs[1:]):
        failures.append("release runs do not retain identical source hashes")
    return tuple(failures)
