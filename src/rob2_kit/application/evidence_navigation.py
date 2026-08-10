"""Project-local durable state for the v2 Evidence navigation boundary."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import model_validator

from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.evidence.workflow import V2EvidenceWorkflowState

EVIDENCE_NAVIGATION_STATE_VERSION = "evidence-navigation-state:2.0.0"


class IncompatibleEvidenceNavigationState(ValueError):
    """Persisted state cannot authorize a request under the current attempt identities."""


class ConcurrentEvidenceNavigationUpdate(ValueError):
    """A competing writer changed the state before this mutation could commit."""


class EvidenceNavigationState(FrozenModel):
    """Hash-validated v2 audit state bound to one Result x Domain."""

    state_version: str = EVIDENCE_NAVIGATION_STATE_VERSION
    contract_version: str = "2.0.0"
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    snapshot_hash: ContentHash
    search_policy_id: Identifier
    search_policy_hash: ContentHash
    read_policy_id: Identifier
    read_policy_hash: ContentHash
    workflow: V2EvidenceWorkflowState
    content_hash: ContentHash

    @model_validator(mode="after")
    def validate_identity(self) -> EvidenceNavigationState:
        if (self.workflow.result_id, self.workflow.domain_id, self.workflow.snapshot_hash) != (
            self.result_id,
            self.domain_id,
            self.snapshot_hash,
        ):
            raise ValueError(
                "workflow state does not bind the persisted Result, Domain, and snapshot"
            )
        if (
            self.workflow.search_policy_id,
            self.workflow.search_policy_hash,
        ) != (self.search_policy_id, self.search_policy_hash):
            raise ValueError("workflow state does not bind the persisted search policy")
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        if self.content_hash != canonical_hash(payload):
            raise ValueError("evidence navigation state content hash does not bind its payload")
        return self


def new_navigation_state(
    *,
    run_id: Identifier,
    workflow: V2EvidenceWorkflowState,
    read_policy_id: Identifier,
    read_policy_hash: ContentHash,
) -> EvidenceNavigationState:
    # Serialize through the persisted model shape before hashing so nested
    # enum/model normalization cannot make the constructor's raw payload
    # differ from the validator's canonical payload.
    unsigned = EvidenceNavigationState.model_construct(
        state_version=EVIDENCE_NAVIGATION_STATE_VERSION,
        contract_version="2.0.0",
        run_id=run_id,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        snapshot_hash=workflow.snapshot_hash,
        search_policy_id=workflow.search_policy_id,
        search_policy_hash=workflow.search_policy_hash,
        read_policy_id=read_policy_id,
        read_policy_hash=read_policy_hash,
        workflow=workflow,
        content_hash="",
    )
    canonical_payload = unsigned.model_dump(mode="json")
    canonical_payload["content_hash"] = None
    return EvidenceNavigationState.model_validate(
        canonical_payload | {"content_hash": canonical_hash(canonical_payload)}
    )


class EvidenceNavigationStore:
    """Atomic JSON persistence with exact path containment on Windows and POSIX."""

    def __init__(self, root: Path) -> None:
        self.root = (root / ".rob2" / "evidence-navigation").resolve()

    def _path(self, run_id: Identifier, result_id: Identifier, domain_id: Identifier) -> Path:
        safe = "|".join((run_id, result_id, domain_id))
        filename = canonical_hash({"v": EVIDENCE_NAVIGATION_STATE_VERSION, "key": safe})[7:]
        path = (self.root / f"{filename}.json").resolve()
        if path.parent != self.root:
            raise ValueError("evidence navigation state path escaped project storage")
        return path

    def load(
        self,
        *,
        run_id: Identifier,
        result_id: Identifier,
        domain_id: Identifier,
        snapshot_hash: ContentHash,
        search_policy_id: Identifier,
        search_policy_hash: ContentHash,
        read_policy_id: Identifier,
        read_policy_hash: ContentHash,
    ) -> EvidenceNavigationState | None:
        path = self._path(run_id, result_id, domain_id)
        if not path.exists():
            return None
        try:
            state = EvidenceNavigationState.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as error:
            raise IncompatibleEvidenceNavigationState(
                "stored v2 Evidence navigation state is unreadable; supersede Preparation"
            ) from error
        actual = (
            state.run_id,
            state.result_id,
            state.domain_id,
            state.snapshot_hash,
            state.search_policy_id,
            state.search_policy_hash,
            state.read_policy_id,
            state.read_policy_hash,
        )
        expected = (
            run_id,
            result_id,
            domain_id,
            snapshot_hash,
            search_policy_id,
            search_policy_hash,
            read_policy_id,
            read_policy_hash,
        )
        if actual != expected:
            raise IncompatibleEvidenceNavigationState(
                "stored v2 Evidence navigation identities are stale; supersede Preparation"
            )
        return state

    @contextmanager
    def _mutation_lock(self, path: Path):
        """Acquire an ownership-proven short-lived lock without deleting stale locks."""

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
                        "navigation state is busy; reload and retry the request"
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
        self,
        state: EvidenceNavigationState,
        *,
        expected_content_hash: ContentHash | None = None,
    ) -> None:
        path = self._path(state.run_id, state.result_id, state.domain_id)
        temporary = path.with_suffix(".json.tmp")
        if temporary.parent != self.root:
            raise ValueError("evidence navigation temporary path escaped project storage")
        with self._mutation_lock(path):
            if expected_content_hash is not None:
                try:
                    existing = EvidenceNavigationState.model_validate_json(path.read_bytes())
                except (OSError, ValueError) as error:
                    raise ConcurrentEvidenceNavigationUpdate(
                        "navigation state changed or became unreadable; reload and retry"
                    ) from error
                if existing.content_hash != expected_content_hash:
                    raise ConcurrentEvidenceNavigationUpdate(
                        "navigation state changed; reload and retry the request"
                    )
            elif path.exists():
                raise ConcurrentEvidenceNavigationUpdate(
                    "navigation state already exists; reload before creating state"
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

    def supersede_run(
        self, run_id: Identifier, *, result_ids: tuple[Identifier, ...] | None = None
    ) -> None:
        """Retain obsolete navigation artifacts after an audited Preparation supersession."""

        if not self.root.exists():
            return
        archive = (self.root / "superseded").resolve()
        if archive.parent != self.root:
            raise ValueError("evidence navigation archive path escaped project storage")
        for path in self.root.glob("*.json"):
            try:
                state = EvidenceNavigationState.model_validate_json(path.read_bytes())
            except (OSError, ValueError):
                continue
            if state.run_id != run_id or (
                result_ids is not None and state.result_id not in result_ids
            ):
                continue
            archive.mkdir(parents=True, exist_ok=True)
            archived = (archive / f"{path.stem}-{state.content_hash[7:]}.json").resolve()
            if archived.parent != archive:
                raise ValueError("evidence navigation archived state path escaped project storage")
            if archived.exists():
                path.unlink()
            else:
                os.replace(path, archived)
