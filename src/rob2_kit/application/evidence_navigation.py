"""Project-local persistence for the active v3 Evidence-navigation state."""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import model_validator

from rob2_kit.application.contracts import EVIDENCE_NAVIGATION_CONTRACT_VERSION
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.evidence.workflow import V3EvidenceWorkflowState

EVIDENCE_NAVIGATION_STATE_VERSION = "evidence-navigation-state:3.0.0"


class IncompatibleEvidenceNavigationState(ValueError):
    """Persisted state cannot authorize a request under the current attempt identities."""


class ConcurrentEvidenceNavigationUpdate(ValueError):
    """A competing writer changed the state before this mutation could commit."""


class V3EvidenceNavigationState(FrozenModel):
    """Content-hashed v3 state, intentionally incompatible with v2 JSON."""

    state_version: str = EVIDENCE_NAVIGATION_STATE_VERSION
    contract_version: str = EVIDENCE_NAVIGATION_CONTRACT_VERSION
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    workflow: V3EvidenceWorkflowState
    content_hash: ContentHash

    @model_validator(mode="after")
    def validate_identity(self) -> V3EvidenceNavigationState:
        if self.state_version != EVIDENCE_NAVIGATION_STATE_VERSION:
            raise ValueError("unsupported Evidence-navigation state version; supersede Preparation")
        if self.contract_version != EVIDENCE_NAVIGATION_CONTRACT_VERSION:
            raise ValueError("unsupported Evidence-navigation contract; supersede Preparation")
        if (self.run_id, self.result_id, self.domain_id, self.question_id) != (
            self.workflow.run_id,
            self.workflow.result_id,
            self.workflow.domain_id,
            self.workflow.question_id,
        ):
            raise ValueError("v3 persisted state does not bind its workflow identities")
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        if self.content_hash != canonical_hash(payload):
            raise ValueError("v3 evidence navigation state content hash does not bind its payload")
        return self


def new_v3_navigation_state(*, workflow: V3EvidenceWorkflowState) -> V3EvidenceNavigationState:
    unsigned = V3EvidenceNavigationState.model_construct(
        state_version=EVIDENCE_NAVIGATION_STATE_VERSION,
        contract_version=EVIDENCE_NAVIGATION_CONTRACT_VERSION,
        run_id=workflow.run_id,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        question_id=workflow.question_id,
        workflow=workflow,
        content_hash="",
    )
    payload = unsigned.model_dump(mode="json")
    payload["content_hash"] = None
    return V3EvidenceNavigationState.model_validate(
        payload | {"content_hash": canonical_hash(payload)}
    )


class V3EvidenceNavigationStore:
    """Atomic persistence for v3; its path namespace prevents in-place v2 reuse."""

    def __init__(self, root: Path) -> None:
        self.root = (root / ".rob2" / "evidence-navigation-v3").resolve()

    def _path(
        self,
        run_id: Identifier,
        result_id: Identifier,
        domain_id: Identifier,
        question_id: Identifier,
        obligation_hash: ContentHash,
        inventory_snapshot_hash: ContentHash,
    ) -> Path:
        key = {
            "run_id": run_id,
            "result_id": result_id,
            "domain_id": domain_id,
            "question_id": question_id,
            "obligation_hash": obligation_hash,
            "inventory_snapshot_hash": inventory_snapshot_hash,
        }
        path = (
            self.root
            / f"{canonical_hash({'v': EVIDENCE_NAVIGATION_STATE_VERSION, 'key': key})[7:]}.json"
        ).resolve()
        if path.parent != self.root:
            raise ValueError("v3 evidence navigation state path escaped project storage")
        return path

    def load(
        self,
        *,
        run_id: Identifier,
        result_id: Identifier,
        domain_id: Identifier,
        question_id: Identifier,
        obligation_hash: ContentHash,
        inventory_snapshot_hash: ContentHash,
    ) -> V3EvidenceNavigationState | None:
        path = self._path(
            run_id,
            result_id,
            domain_id,
            question_id,
            obligation_hash,
            inventory_snapshot_hash,
        )
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_bytes())
        except (OSError, ValueError, UnicodeDecodeError) as error:
            raise IncompatibleEvidenceNavigationState(
                "stored Evidence-navigation state is malformed for the current contract"
            ) from error
        if not isinstance(raw, dict):
            raise IncompatibleEvidenceNavigationState(
                "stored Evidence-navigation state is malformed for the current contract"
            )
        if raw.get("state_version") != EVIDENCE_NAVIGATION_STATE_VERSION or raw.get(
            "contract_version"
        ) != EVIDENCE_NAVIGATION_CONTRACT_VERSION:
            raise IncompatibleEvidenceNavigationState(
                "stored Evidence-navigation identity is unsupported "
                f"(state_version={raw.get('state_version')!r}, "
                f"contract_version={raw.get('contract_version')!r}; expected "
                f"state_version={EVIDENCE_NAVIGATION_STATE_VERSION!r}, "
                f"contract_version={EVIDENCE_NAVIGATION_CONTRACT_VERSION!r}); "
                "supersede Preparation"
            )
        try:
            state = V3EvidenceNavigationState.model_validate(raw)
        except ValueError as error:
            raise IncompatibleEvidenceNavigationState(
                "stored current-version Evidence-navigation state is malformed"
            ) from error
        if (
            state.run_id,
            state.result_id,
            state.domain_id,
            state.question_id,
            state.workflow.obligation_hash,
            state.workflow.inventory_snapshot_hash,
        ) != (run_id, result_id, domain_id, question_id, obligation_hash, inventory_snapshot_hash):
            raise IncompatibleEvidenceNavigationState(
                "stored v3 Evidence navigation identities are stale; supersede Preparation"
            )
        return state

    @contextmanager
    def _mutation_lock(self, path: Path):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(".lock")
        owner = f"{os.getpid()}:{uuid.uuid4().hex}"
        deadline = time.monotonic() + 5.0
        while True:
            try:
                with lock.open("x", encoding="utf-8") as handle:
                    handle.write(owner)
                    handle.flush()
                    os.fsync(handle.fileno())
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ConcurrentEvidenceNavigationUpdate(
                        "v3 navigation state is busy; reload and retry"
                    ) from None
                time.sleep(0.025)
        try:
            yield
        finally:
            try:
                if lock.read_text(encoding="utf-8") == owner:
                    lock.unlink()
            except OSError:
                pass

    def save(
        self, state: V3EvidenceNavigationState, *, expected_content_hash: ContentHash | None = None
    ) -> None:
        path = self._path(
            state.run_id,
            state.result_id,
            state.domain_id,
            state.question_id,
            state.workflow.obligation_hash,
            state.workflow.inventory_snapshot_hash,
        )
        temporary = path.with_suffix(".json.tmp")
        with self._mutation_lock(path):
            if expected_content_hash is None:
                if path.exists():
                    raise ConcurrentEvidenceNavigationUpdate(
                        "v3 navigation state already exists; reload before creating state"
                    )
            else:
                try:
                    prior = V3EvidenceNavigationState.model_validate_json(path.read_bytes())
                except (OSError, ValueError) as error:
                    raise ConcurrentEvidenceNavigationUpdate(
                        "v3 navigation state changed or became unreadable; reload and retry"
                    ) from error
                if prior.content_hash != expected_content_hash:
                    raise ConcurrentEvidenceNavigationUpdate(
                        "v3 navigation state changed; reload and retry"
                    )
            try:
                with temporary.open("xb") as handle:
                    handle.write(canonical_json_bytes(state))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except OSError:
                temporary.unlink(missing_ok=True)
                raise
