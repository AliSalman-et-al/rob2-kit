"""Small immutable references to canonical detail records.

Detail references carry identity and a stable resource-shaped locator only.
They never embed Source text, captured paths, or canonical record bodies.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from rob2_kit.models import StrictModel


class DetailReference(StrictModel):
    kind: Literal[
        "batch",
        "proposal",
        "trial",
        "result",
        "domain",
        "judgment",
        "synthesis",
        "terminal",
        "proposal_review",
        "approved_batch",
        "review_ack",
        "work_packet",
    ]
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    uri: str = Field(
        pattern=r"^rob2://detail/(batch|proposal|trial|result|domain|judgment|synthesis|terminal|proposal_review|approved_batch|review_ack|work_packet)/sha256:[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def uri_matches_kind_and_identity(self) -> DetailReference:
        if self.uri != f"rob2://detail/{self.kind}/{self.identity}":
            raise ValueError("detail URI does not match kind and identity")
        return self


_URI = re.compile(
    r"^rob2://detail/(?P<kind>batch|proposal|trial|result|domain|judgment|synthesis|terminal|proposal_review|approved_batch|review_ack|work_packet)/(?P<identity>sha256:[0-9a-f]{64})$"
)


def detail_reference(kind: str, identity: str) -> DetailReference:
    """Create an allowlisted reference without embedding record content."""

    reference = DetailReference(
        kind=cast(
            Literal[
                "batch",
                "proposal",
                "trial",
                "result",
                "domain",
                "judgment",
                "synthesis",
                "terminal",
                "proposal_review",
                "approved_batch",
                "review_ack",
                "work_packet",
            ],
            kind,
        ),
        identity=identity,
        uri=f"rob2://detail/{kind}/{identity}",
    )
    return reference


def parse_detail_uri(uri: str) -> DetailReference:
    match = _URI.fullmatch(uri)
    if match is None:
        raise ValueError("unsupported detail URI")
    return detail_reference(match.group("kind"), match.group("identity"))


def resource_link(reference: DetailReference) -> Any:
    """Return an MCP ResourceLink when MCP is installed, otherwise a typed fallback."""

    try:
        from mcp.types import ResourceLink

        return ResourceLink(
            name=f"rob2-{reference.kind}",
            uri=reference.uri,
            mimeType="application/json",
            type="resource_link",
        )
    except ImportError:
        return {
            "type": "resource_link",
            "name": f"rob2-{reference.kind}",
            "uri": reference.uri,
            "mimeType": "application/json",
        }


def _record_names(reference: DetailReference) -> tuple[str, ...]:
    identity = reference.identity
    if reference.kind == "proposal":
        return (f"proposal_version:{identity}",)
    if reference.kind == "proposal_review":
        return (f"application:proposal_review-{identity.removeprefix('sha256:')}.json",)
    if reference.kind == "approved_batch":
        return ("application:approved_batch.json",)
    if reference.kind == "review_ack":
        return ("application:proposal_ack.json", "application:review_ack.json")
    if reference.kind == "work_packet":
        return (f"application:domain-packet-{identity.removeprefix('sha256:')}.json",)
    return (f"detail:{reference.kind}:{identity}",)


def _verified_payload(reference: DetailReference, payload: bytes) -> dict[str, object]:
    """Parse one closed Detail kind and recompute its content identity."""

    from pydantic import ValidationError

    try:
        if reference.kind in {"proposal_review", "approved_batch", "review_ack", "work_packet"}:
            import json

            decoded = json.loads(payload.decode("utf-8"))
            if not isinstance(decoded, dict) or decoded.get("identity") != reference.identity:
                raise ValueError("application Detail identity mismatch")
            from rob2_kit.application._state import identity as application_identity

            if reference.kind == "proposal_review":
                from rob2_kit.application.proposal import ProposalReview

                review = ProposalReview.model_validate(decoded)
                content = review.model_dump(
                    mode="json", exclude={"identity", "review", "transition", "kind"}
                )
                if application_identity(content) != reference.identity:
                    raise ValueError("Proposal Review Detail identity mismatch")
            elif reference.kind == "approved_batch":
                content = {
                    key: value for key, value in decoded.items() if key not in {"kind", "identity"}
                }
                if application_identity(content) != reference.identity:
                    raise ValueError("approved Batch Detail identity mismatch")
            elif reference.kind == "work_packet":
                content = {key: value for key, value in decoded.items() if key != "identity"}
                if (
                    decoded.get("kind") != "work_packet"
                    or application_identity(content) != reference.identity
                ):
                    raise ValueError("work packet Detail identity mismatch")
            else:
                content = {key: value for key, value in decoded.items() if key != "identity"}
                if application_identity(content) != reference.identity:
                    raise ValueError("review acknowledgment Detail identity mismatch")
            return decoded
        if reference.kind == "proposal":
            from rob2_kit.batch import ProposalVersion, _version_identity

            record = ProposalVersion.model_validate_json(payload)
            if (
                record.version_hash != reference.identity
                or _version_identity(record) != reference.identity
            ):
                raise ValueError("proposal version identity mismatch")
        elif reference.kind == "domain":
            from rob2_kit.packets import ApprovedWorkPacket, verify_approved_work_packet

            record = verify_approved_work_packet(ApprovedWorkPacket.model_validate_json(payload))
            if record.packet_hash != reference.identity:
                raise ValueError("Domain packet identity mismatch")
        elif reference.kind == "synthesis":
            from rob2_kit.packets import TrialSynthesisPacket, verify_trial_synthesis_packet

            record = verify_trial_synthesis_packet(
                TrialSynthesisPacket.model_validate_json(payload)
            )
            if record.packet_hash != reference.identity:
                raise ValueError("synthesis packet identity mismatch")
        elif reference.kind == "judgment":
            from rob2_kit.judgment_models import DomainJudgment
            from rob2_kit.judgments import _verified_checkpoint

            record = _verified_checkpoint(DomainJudgment.model_validate_json(payload))
            if record.checkpoint_hash != reference.identity:
                raise ValueError("Domain judgment identity mismatch")
        elif reference.kind == "trial":
            from rob2_kit.finish import AssessmentSnapshot, _verified

            record = _verified(AssessmentSnapshot.model_validate_json(payload))
            if record.snapshot_hash != reference.identity:
                raise ValueError("Trial snapshot identity mismatch")
        elif reference.kind == "terminal":
            from rob2_kit.batch_summary import ProblemTerminal, verified_terminal
            from rob2_kit.finish import AssessmentSnapshot, _verified

            try:
                record = _verified(AssessmentSnapshot.model_validate_json(payload))
                identity = record.snapshot_hash
            except (ValidationError, ValueError):
                record = verified_terminal(ProblemTerminal.model_validate_json(payload))
                identity = record.terminal_hash
            if identity != reference.identity:
                raise ValueError("Trial terminal identity mismatch")
        elif reference.kind == "batch":
            from rob2_kit.assessment import CapturedBatch, captured_batch_hash
            from rob2_kit.batch import ApprovedBatch, frozen_batch_hash
            from rob2_kit.batch_summary import BatchSummary, verified_summary

            try:
                record = CapturedBatch.model_validate_json(payload)
                identity = captured_batch_hash(record)
                if record.content_hash != identity:
                    raise ValueError("Captured Batch embedded identity mismatch")
            except ValidationError:
                try:
                    record = ApprovedBatch.model_validate_json(payload)
                    identity = frozen_batch_hash(record.proposal, record.pack_identities)
                    if record.frozen_hash != identity:
                        raise ValueError("Approved Batch embedded identity mismatch")
                except ValidationError:
                    record = verified_summary(BatchSummary.model_validate_json(payload))
                    identity = record.summary_hash
            if identity != reference.identity:
                raise ValueError("Batch Detail identity mismatch")
        else:
            raise ValueError("unsupported Detail kind")
    except (ValidationError, TypeError, KeyError) as error:
        raise ValueError(f"{reference.kind} Detail record is corrupt") from error
    return cast(dict[str, object], record.model_dump(mode="json"))


def read_record(
    workspace: str | Path,
    reference: DetailReference | str,
) -> object:
    """Read one allowlisted canonical record and verify identity/parent binding."""

    ref = parse_detail_uri(reference) if isinstance(reference, str) else reference
    if ref.uri != f"rob2://detail/{ref.kind}/{ref.identity}":
        raise ValueError("detail reference URI does not match identity")
    root = Path(workspace).resolve(strict=True)
    path = root / ".rob2-kit" / "active-batch.sqlite3"
    if not path.exists():
        raise ValueError("detail record is unavailable")
    connection = sqlite3.connect(path)
    try:
        row = None
        for name in _record_names(ref):
            row = connection.execute("SELECT payload FROM records WHERE name=?", (name,)).fetchone()
            if row is not None:
                break
        if row is None:
            raise ValueError("detail record is unavailable")
        payload = bytes(row[0])
    finally:
        connection.close()
    value = _verified_payload(ref, payload)
    parent = value.get("approved_batch_hash") or value.get("captured_batch_hash")
    if parent is not None:
        if not isinstance(parent, str) or parent == ref.identity:
            raise ValueError("detail record parent mismatch")
        parent_ref = detail_reference("batch", parent)
        parent_value = cast(dict[str, object], read_record(workspace, parent_ref))
        parent_identity = (
            parent_value.get("frozen_hash")
            or parent_value.get("content_hash")
            or parent_value.get("summary_hash")
        )
        if parent_identity != parent:
            raise ValueError("detail record parent mismatch")
    if ref.kind in {"domain", "synthesis"}:
        from rob2_kit.recovery import recovery_progress

        progress = recovery_progress(workspace)
        if progress.status != "approved" or progress.summary_committed:
            raise ValueError("packet Detail is outside its availability window")
        trial = value.get("trial")
        if not isinstance(trial, dict) or not isinstance(trial.get("id"), str):
            raise ValueError("packet Detail Trial binding is corrupt")
        trial_progress = next(
            (item for item in progress.trials if item.trial_id == trial["id"]), None
        )
        if trial_progress is None:
            raise ValueError("packet Detail Trial binding is unavailable")
        if ref.kind == "domain":
            correction_refs = tuple(
                item.packet_ref for item in trial_progress.correction_packet_refs
            )
            if (
                trial_progress.status != "pending"
                or ref not in correction_refs
                and trial_progress.recommended_packet_ref != ref
            ):
                raise ValueError("Domain packet Detail is stale")
        elif trial_progress.synthesis_ref != ref:
            raise ValueError("synthesis packet Detail is stale")
    return value


__all__ = [
    "DetailReference",
    "detail_reference",
    "parse_detail_uri",
    "read_record",
    "resource_link",
]
