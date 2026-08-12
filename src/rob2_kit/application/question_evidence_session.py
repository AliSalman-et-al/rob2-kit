"""Durable private session state for v3 question-scoped evidence work.

The RunEngine still owns Run lifecycle transitions and public work tokens.  This
module deliberately owns neither.  It is the revision-keyed seam between that
lifecycle and the independently durable v3 evidence navigation state: a
session persists the full answer/diagnostic history and deterministically
re-materializes context for only the current active questions.
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import Field, model_validator

from rob2_kit.application.active_question_frontier import (
    ActiveQuestionFrontier,
    ActiveQuestionLedger,
    QuestionAnswerCommitStep,
    QuestionAnswerCorrection,
    QuestionDiagnosticStop,
    active_question_frontier,
    append_question_answer,
    append_question_correction,
    append_question_diagnostic_stop,
    new_active_question_ledger,
)
from rob2_kit.application.evidence_context import (
    EvidenceContextInventory,
    MaterializedEvidenceContext,
    materialize_evidence_context,
)
from rob2_kit.application.evidence_navigation import (
    ConcurrentEvidenceNavigationUpdate,
    V3EvidenceNavigationState,
    V3EvidenceNavigationStore,
)
from rob2_kit.application.evidence_runtime import (
    V3EvidenceNavigationRuntime,
    V3EvidenceSearchDependency,
)
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.evidence.obligations import EvidenceSearchObligation
from rob2_kit.evidence.search import EvidenceReadPolicy, EvidenceSearchPolicy
from rob2_kit.evidence.visual import VisualInspectionPolicy
from rob2_kit.evidence.workflow import (
    V3EvidenceWorkflowState,
    provision_v3_scope_acquisition_receipts,
)
from rob2_kit.logic.packs import LogicPack

QUESTION_EVIDENCE_SESSION_VERSION = "question-evidence-session:1.0.0"
V3_VISUAL_POLICY_ID = "policy:visual-inspection-1.0.0"


class QuestionEvidenceSessionError(ValueError):
    """A requested internal session transition is not authorized."""


class StaleQuestionEvidenceSession(QuestionEvidenceSessionError):
    """The caller used a session revision superseded by another writer."""


class QuestionEvidenceSessionContextMismatch(QuestionEvidenceSessionError):
    """A context, workflow, or revision does not bind this exact session."""


class EvidenceContextFactory(Protocol):
    """Pure factory used to bind an accepted obligation to an inventory revision."""

    def __call__(
        self, obligation: EvidenceSearchObligation, inventory: EvidenceContextInventory
    ) -> MaterializedEvidenceContext: ...


class QuestionEvidenceSession(FrozenModel):
    """One immutable, revision-keyed question-progress history.

    ``ledger`` is deliberately persisted in full.  A frontier is a derived
    projection and must never replace the prior committed answer/diagnostic
    history that makes conditional activation reproducible.
    """

    state_version: str = QUESTION_EVIDENCE_SESSION_VERSION
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    logic_pack_release_id: str
    logic_pack_hash: ContentHash
    guidance_release_id: str
    guidance_obligations_hash: ContentHash
    obligation_revision_id: Identifier
    inventory_revision_id: Identifier
    inventory_revision_hash: ContentHash
    inventory: EvidenceContextInventory
    obligations: tuple[EvidenceSearchObligation, ...] = Field(min_length=1)
    ledger: ActiveQuestionLedger
    content_hash: ContentHash

    @model_validator(mode="after")
    def validate_session(self) -> QuestionEvidenceSession:
        if self.state_version != QUESTION_EVIDENCE_SESSION_VERSION:
            raise ValueError("unsupported question evidence session state version")
        if (self.ledger.run_id, self.ledger.result_id, self.ledger.domain_id) != (
            self.run_id,
            self.result_id,
            self.domain_id,
        ):
            raise ValueError("question evidence ledger does not bind the session scope")
        if (
            self.ledger.logic_pack.release_id,
            self.ledger.logic_pack.content_hash,
        ) != (self.logic_pack_release_id, self.logic_pack_hash):
            raise ValueError("question evidence session changed Logic pack identity")
        if self.inventory_revision_hash != _model_hash(self.inventory):
            raise ValueError("inventory revision hash does not bind the exact inventory")
        if self.guidance_obligations_hash != _obligations_hash(self.obligations):
            raise ValueError("guidance obligations hash does not bind the exact obligations")
        question_ids = [item.question_id for item in self.obligations]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question evidence session cannot repeat an obligation")
        domain = next(
            (item for item in self.ledger.logic_pack.domains if item.id == self.domain_id), None
        )
        if domain is None:
            raise ValueError("question evidence session names an unknown Logic domain")
        if set(question_ids) != set(domain.question_ids):
            raise ValueError("session obligations must cover exactly the Logic domain questions")
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        if self.content_hash != canonical_hash(payload):
            raise ValueError("question evidence session content hash does not bind its payload")
        return self


def new_question_evidence_session(
    *,
    run_id: Identifier,
    result_id: Identifier,
    domain_id: Identifier,
    logic_pack: LogicPack,
    guidance_release_id: str,
    obligations: tuple[EvidenceSearchObligation, ...],
    obligation_revision_id: Identifier,
    inventory_revision_id: Identifier,
    inventory: EvidenceContextInventory,
) -> QuestionEvidenceSession:
    """Create a new immutable session for one exact source/pack revision set."""

    unsigned = QuestionEvidenceSession.model_construct(
        run_id=run_id,
        result_id=result_id,
        domain_id=domain_id,
        logic_pack_release_id=logic_pack.release_id,
        logic_pack_hash=logic_pack.content_hash,
        guidance_release_id=guidance_release_id,
        guidance_obligations_hash=_obligations_hash(obligations),
        obligation_revision_id=obligation_revision_id,
        inventory_revision_id=inventory_revision_id,
        inventory_revision_hash=_model_hash(inventory),
        inventory=inventory,
        obligations=obligations,
        ledger=new_active_question_ledger(
            logic_pack, run_id=run_id, result_id=result_id, domain_id=domain_id
        ),
        content_hash="",
    )
    payload = unsigned.model_dump(mode="json")
    payload["content_hash"] = None
    return QuestionEvidenceSession.model_validate(
        payload | {"content_hash": canonical_hash(payload)}
    )


def _model_hash(value: FrozenModel) -> ContentHash:
    """Hash a model through its canonical JSON projection, never its Python object."""

    return canonical_hash(value.model_dump(mode="json"))


def _obligations_hash(obligations: tuple[EvidenceSearchObligation, ...]) -> ContentHash:
    return canonical_hash(tuple(item.model_dump(mode="json") for item in obligations))


class QuestionEvidenceSessionStore:
    """Atomic revision-keyed persistence which never overwrites a prior revision."""

    def __init__(self, root: Path) -> None:
        self.root = (root / ".rob2" / "question-evidence-sessions").resolve()

    def _path(self, session: QuestionEvidenceSession) -> Path:
        key = {
            "run_id": session.run_id,
            "result_id": session.result_id,
            "domain_id": session.domain_id,
            "logic_pack_hash": session.logic_pack_hash,
            "guidance_obligations_hash": session.guidance_obligations_hash,
            "obligation_revision_id": session.obligation_revision_id,
            "inventory_revision_id": session.inventory_revision_id,
            "inventory_revision_hash": session.inventory_revision_hash,
        }
        path = (
            self.root
            / f"{canonical_hash({'v': QUESTION_EVIDENCE_SESSION_VERSION, 'key': key})[7:]}.json"
        ).resolve()
        if path.parent != self.root:
            raise ValueError("question evidence session path escaped project storage")
        return path

    def _transition_path(
        self, session: QuestionEvidenceSession, predecessor_session_hash: ContentHash
    ) -> Path:
        directory = (self.root / "transitions").resolve()
        if directory.parent != self.root:
            raise ValueError("question evidence transition path escaped project storage")
        key = {
            "session": self._path(session).stem,
            "predecessor_session_hash": predecessor_session_hash,
        }
        return (directory / f"{canonical_hash(key)[7:]}.json").resolve()

    @contextmanager
    def _lock(self, path: Path):
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
                    raise StaleQuestionEvidenceSession(
                        "question evidence session is busy; reload and retry"
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

    def load(self, session: QuestionEvidenceSession) -> QuestionEvidenceSession | None:
        path = self._path(session)
        if not path.exists():
            return None
        try:
            persisted = QuestionEvidenceSession.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as error:
            raise QuestionEvidenceSessionContextMismatch(
                "stored question evidence session is unreadable"
            ) from error
        if self._path(persisted) != path:
            raise QuestionEvidenceSessionContextMismatch(
                "stored question evidence session has a stale revision key"
            )
        return persisted

    def save(
        self,
        session: QuestionEvidenceSession,
        *,
        expected_content_hash: ContentHash | None = None,
    ) -> None:
        path = self._path(session)
        temporary = path.with_suffix(".json.tmp")
        with self._lock(path):
            if expected_content_hash is None:
                if path.exists():
                    raise StaleQuestionEvidenceSession(
                        "question evidence session already exists; reload before creating"
                    )
            else:
                try:
                    prior = QuestionEvidenceSession.model_validate_json(path.read_bytes())
                except (OSError, ValueError) as error:
                    raise StaleQuestionEvidenceSession(
                        "question evidence session changed or became unreadable; reload and retry"
                    ) from error
                if prior.content_hash != expected_content_hash:
                    raise StaleQuestionEvidenceSession(
                        "question evidence session changed; reload and retry"
                    )
            try:
                with temporary.open("xb") as handle:
                    handle.write(canonical_json_bytes(session))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except OSError:
                temporary.unlink(missing_ok=True)
                raise

    def load_transition(
        self, session: QuestionEvidenceSession, predecessor_session_hash: ContentHash
    ) -> QuestionEvidenceTransitionReceipt | None:
        path = self._transition_path(session, predecessor_session_hash)
        if not path.exists():
            return None
        try:
            return QuestionEvidenceTransitionReceipt.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as error:
            raise QuestionEvidenceSessionContextMismatch(
                "stored question evidence transition receipt is unreadable"
            ) from error

    def save_transition(
        self, session: QuestionEvidenceSession, receipt: QuestionEvidenceTransitionReceipt
    ) -> None:
        path = self._transition_path(session, receipt.predecessor_session_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        with self._lock(path):
            if path.exists():
                existing = self.load_transition(session, receipt.predecessor_session_hash)
                if existing != receipt:
                    raise StaleQuestionEvidenceSession(
                        "question evidence transition token was replayed with different content"
                    )
                return
            try:
                with temporary.open("xb") as handle:
                    handle.write(canonical_json_bytes(receipt))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except OSError:
                temporary.unlink(missing_ok=True)
                raise


class QuestionEvidenceRuntimeIdentity(FrozenModel):
    question_id: Identifier
    context_id: Identifier
    context_hash: ContentHash
    navigation_state_hash: ContentHash | None = None


class ActiveQuestionEvidenceContext(FrozenModel):
    """One active frontier entry with all engine-owned v3 navigation identity."""

    question_id: Identifier
    frontier_entry_hash: ContentHash
    context: MaterializedEvidenceContext
    runtime: QuestionEvidenceRuntimeIdentity


class QuestionEvidenceSessionProjection(FrozenModel):
    session_content_hash: ContentHash
    frontier: ActiveQuestionFrontier
    active_contexts: tuple[ActiveQuestionEvidenceContext, ...] = ()

    @property
    def status(self) -> str:
        return self.frontier.status


class QuestionEvidenceTransitionReceipt(FrozenModel):
    """Replay key for the session half of a later Run-ledger checkpoint."""

    predecessor_session_hash: ContentHash
    successor_session_hash: ContentHash
    kind: str = Field(pattern=r"^(answer|correction|diagnostic_stop)$")
    transition_content_hash: ContentHash


class QuestionEvidenceSessionTransition(FrozenModel):
    receipt: QuestionEvidenceTransitionReceipt
    projection: QuestionEvidenceSessionProjection
    replayed: bool = False


@dataclass(frozen=True)
class QuestionEvidenceRuntime:
    """Internal v3 runtime paired with the exact context used to make it."""

    context: MaterializedEvidenceContext
    runtime: V3EvidenceNavigationRuntime
    state: V3EvidenceNavigationState


class QuestionEvidenceSessionService:
    """Coordinates persisted question history with revision-keyed v3 navigation.

    The service intentionally does not issue tokens or write Run lifecycle
    events.  Callers later bridge its committed transition and projection to
    their own Run ledger transaction.
    """

    def __init__(
        self,
        *,
        session: QuestionEvidenceSession,
        store: QuestionEvidenceSessionStore,
        navigation_store: V3EvidenceNavigationStore,
        search: V3EvidenceSearchDependency,
        context_factory: EvidenceContextFactory = materialize_evidence_context,
        search_policy: EvidenceSearchPolicy | None = None,
        read_policy: EvidenceReadPolicy | None = None,
        visual_policy: VisualInspectionPolicy | None = None,
    ) -> None:
        self._seed = session
        self._store = store
        self._navigation_store = navigation_store
        self._search = search
        self._context_factory = context_factory
        self._search_policy = search_policy or EvidenceSearchPolicy()
        self._read_policy = read_policy or EvidenceReadPolicy()
        self._visual_policy = visual_policy or VisualInspectionPolicy()

    def initialize(self) -> QuestionEvidenceSessionProjection:
        """Persist the exact session once and provision its active v3 runtimes."""

        # Validate every active materialization before any durable write.
        self.project(self._seed)
        existing = self._store.load(self._seed)
        if existing is None:
            self._store.save(self._seed)
            state = self._seed
        elif existing == self._seed:
            state = existing
        else:
            raise StaleQuestionEvidenceSession(
                "question evidence session revision already exists with different history"
            )
        self._provision_active_runtimes(state)
        return self.project(state)

    def load(self) -> QuestionEvidenceSession:
        state = self._store.load(self._seed)
        if state is None:
            raise QuestionEvidenceSessionError("question evidence session has not been initialized")
        return state

    def reconcile_transition(
        self,
        *,
        predecessor_session_hash: ContentHash,
        kind: str,
        transition_content_hash: ContentHash,
    ) -> QuestionEvidenceSessionTransition:
        """Return only the exact durable transition left before a Run checkpoint.

        The RunEngine uses this after a crash between the session write and
        its own ledger write.  Matching the predecessor alone is insufficient:
        callers must also prove the transition kind and fully bound immutable
        step/stop hash.
        """

        state = self.load()
        receipt = self._store.load_transition(state, predecessor_session_hash)
        if (
            receipt is None
            or receipt.kind != kind
            or receipt.transition_content_hash != transition_content_hash
            or receipt.successor_session_hash != state.content_hash
        ):
            raise QuestionEvidenceSessionContextMismatch(
                "no exact durable question evidence transition is available for reconciliation"
            )
        return QuestionEvidenceSessionTransition(
            receipt=receipt, projection=self.project(state), replayed=True
        )

    def project(
        self, session: QuestionEvidenceSession | None = None
    ) -> QuestionEvidenceSessionProjection:
        state = session or self.load()
        frontier = active_question_frontier(state.ledger)
        contexts = tuple(
            self._active_context(state, entry.question_id, entry.entry_hash)
            for entry in frontier.entries
        )
        return QuestionEvidenceSessionProjection(
            session_content_hash=state.content_hash,
            frontier=frontier,
            active_contexts=contexts,
        )

    def runtime_for_question(self, question_id: Identifier) -> QuestionEvidenceRuntime:
        """Create or load exactly one question's context-bound v3 runtime."""

        state = self.load()
        frontier = active_question_frontier(state.ledger)
        entry = next((item for item in frontier.entries if item.question_id == question_id), None)
        if entry is None:
            raise QuestionEvidenceSessionError("question is not on the current active frontier")
        context = self._context_for_question(state, question_id)
        runtime = self._runtime_for_context(state, context)
        navigation = self._load_or_initialize_runtime(state, context, runtime)
        return QuestionEvidenceRuntime(context=context, runtime=runtime, state=navigation)

    def runtime_for_committed_question(self, question_id: Identifier) -> QuestionEvidenceRuntime:
        """Load the durable v3 workflow that authorized an earlier answer.

        A correction may target a completed or currently inactive question.
        It may never invent a workflow: the exact persisted runtime is still
        required even though the question is not on the current frontier.
        """

        state = self.load()
        if not any(item.question_id == question_id for item in state.ledger.steps):
            raise QuestionEvidenceSessionError("correction names no committed question answer")
        context = self._context_for_question(state, question_id)
        runtime = self._runtime_for_context(state, context)
        if not self._navigation_exists(state, context):
            raise QuestionEvidenceSessionContextMismatch(
                "correction requires the committed question's persisted v3 workflow"
            )
        return QuestionEvidenceRuntime(context=context, runtime=runtime, state=runtime.load())

    def runtime_for_diagnostic_question(self, question_id: Identifier) -> QuestionEvidenceRuntime:
        """Load the exact persisted workflow behind an immutable diagnostic stop."""

        state = self.load()
        if not any(item.question_id == question_id for item in state.ledger.diagnostic_stops):
            raise QuestionEvidenceSessionError("question has no committed diagnostic stop")
        context = self._context_for_question(state, question_id)
        runtime = self._runtime_for_context(state, context)
        if not self._navigation_exists(state, context):
            raise QuestionEvidenceSessionContextMismatch(
                "diagnostic recovery requires the stopped question's persisted v3 workflow"
            )
        return QuestionEvidenceRuntime(context=context, runtime=runtime, state=runtime.load())

    def commit_answer(
        self,
        *,
        expected_content_hash: ContentHash,
        step: QuestionAnswerCommitStep,
        workflow: V3EvidenceWorkflowState,
    ) -> QuestionEvidenceSessionTransition:
        replay = self._replay_if_applied(expected_content_hash, "answer", step.content_hash)
        if replay is not None:
            return replay
        state = self._current(expected_content_hash)
        self._require_persisted_workflow(state, step.question_id, workflow)
        successor = self._replace_ledger(
            state, append_question_answer(state.ledger, step, workflow)
        )
        projection = self.project(successor)
        receipt = QuestionEvidenceTransitionReceipt(
            predecessor_session_hash=state.content_hash,
            successor_session_hash=successor.content_hash,
            kind="answer",
            transition_content_hash=step.content_hash,
        )
        self._store.save_transition(state, receipt)
        self._store.save(successor, expected_content_hash=state.content_hash)
        self._provision_active_runtimes(successor)
        return QuestionEvidenceSessionTransition(receipt=receipt, projection=projection)

    def commit_diagnostic_stop(
        self,
        *,
        expected_content_hash: ContentHash,
        stop: QuestionDiagnosticStop,
        workflow: V3EvidenceWorkflowState,
    ) -> QuestionEvidenceSessionTransition:
        replay = self._replay_if_applied(
            expected_content_hash, "diagnostic_stop", stop.content_hash
        )
        if replay is not None:
            return replay
        state = self._current(expected_content_hash)
        self._require_persisted_workflow(state, stop.question_id, workflow)
        successor = self._replace_ledger(
            state, append_question_diagnostic_stop(state.ledger, stop, workflow)
        )
        projection = self.project(successor)
        receipt = QuestionEvidenceTransitionReceipt(
            predecessor_session_hash=state.content_hash,
            successor_session_hash=successor.content_hash,
            kind="diagnostic_stop",
            transition_content_hash=stop.content_hash,
        )
        self._store.save_transition(state, receipt)
        self._store.save(successor, expected_content_hash=state.content_hash)
        self._provision_active_runtimes(successor)
        return QuestionEvidenceSessionTransition(receipt=receipt, projection=projection)

    def commit_correction(
        self, *, expected_content_hash: ContentHash, correction: QuestionAnswerCorrection
    ) -> QuestionEvidenceSessionTransition:
        replay = self._replay_if_applied(
            expected_content_hash, "correction", correction.content_hash
        )
        if replay is not None:
            return replay
        state = self._current(expected_content_hash)
        successor = self._replace_ledger(
            state, append_question_correction(state.ledger, correction)
        )
        projection = self.project(successor)
        receipt = QuestionEvidenceTransitionReceipt(
            predecessor_session_hash=state.content_hash,
            successor_session_hash=successor.content_hash,
            kind="correction",
            transition_content_hash=correction.content_hash,
        )
        self._store.save_transition(state, receipt)
        self._store.save(successor, expected_content_hash=state.content_hash)
        self._provision_active_runtimes(successor)
        return QuestionEvidenceSessionTransition(receipt=receipt, projection=projection)

    def _active_context(
        self,
        state: QuestionEvidenceSession,
        question_id: Identifier,
        entry_hash: ContentHash,
    ) -> ActiveQuestionEvidenceContext:
        context = self._context_for_question(state, question_id)
        persisted = self._navigation_store.load(
            run_id=state.run_id,
            result_id=state.result_id,
            domain_id=state.domain_id,
            question_id=question_id,
            obligation_hash=context.obligation_hash,
            inventory_snapshot_hash=context.inventory_snapshot_hash,
        )
        return ActiveQuestionEvidenceContext(
            question_id=question_id,
            frontier_entry_hash=entry_hash,
            context=context,
            runtime=QuestionEvidenceRuntimeIdentity(
                question_id=question_id,
                context_id=context.context_id,
                context_hash=context.materialization_hash,
                navigation_state_hash=(persisted.content_hash if persisted is not None else None),
            ),
        )

    def _open_for(
        self, state: QuestionEvidenceSession, question_id: Identifier
    ) -> QuestionEvidenceRuntime:
        context = self._context_for_question(state, question_id)
        runtime = self._runtime_for_context(state, context)
        navigation = self._load_or_initialize_runtime(state, context, runtime)
        return QuestionEvidenceRuntime(context=context, runtime=runtime, state=navigation)

    def _provision_active_runtimes(self, state: QuestionEvidenceSession) -> None:
        """Perform the explicit write phase for the current frontier only."""

        for entry in active_question_frontier(state.ledger).entries:
            self._open_for(state, entry.question_id)

    def _load_or_initialize_runtime(
        self,
        state: QuestionEvidenceSession,
        context: MaterializedEvidenceContext,
        runtime: V3EvidenceNavigationRuntime,
    ) -> V3EvidenceNavigationState:
        if self._navigation_exists(state, context):
            return runtime.load()
        try:
            return runtime.initialize()
        except ConcurrentEvidenceNavigationUpdate:
            # An exact concurrent provision is idempotent; ``load`` verifies
            # that it did not cross a context/workflow revision boundary.
            return runtime.load()

    def _context_for_question(
        self, state: QuestionEvidenceSession, question_id: Identifier
    ) -> MaterializedEvidenceContext:
        obligation = next(
            (item for item in state.obligations if item.question_id == question_id), None
        )
        if obligation is None:
            raise QuestionEvidenceSessionContextMismatch(
                "active question has no accepted obligation"
            )
        context = self._context_factory(obligation, state.inventory)
        if (
            context.question_id != question_id
            or context.obligation != obligation
            or context.obligation_hash != canonical_hash(obligation)
            or context.inventory_id != state.inventory.inventory_id
        ):
            raise QuestionEvidenceSessionContextMismatch(
                "context factory returned a context outside the exact session revision"
            )
        return context

    def _runtime_for_context(
        self, state: QuestionEvidenceSession, context: MaterializedEvidenceContext
    ) -> V3EvidenceNavigationRuntime:
        workflow = provision_v3_scope_acquisition_receipts(
            V3EvidenceWorkflowState(
                run_id=state.run_id,
                result_id=state.result_id,
                domain_id=state.domain_id,
                question_id=context.question_id,
                snapshot_hash=state.inventory_revision_hash,
                obligation_revision_id=state.obligation_revision_id,
                obligation=context.obligation,
                obligation_hash=context.obligation_hash,
                inventory_snapshot_hash=context.inventory_snapshot_hash,
                authorized_inventory=context.authorized_inventory,
                search_policy_id=self._search_policy.policy_id,
                search_policy_hash=canonical_hash(self._search_policy),
                read_policy_id=self._read_policy.policy_id,
                read_policy_hash=canonical_hash(self._read_policy),
                visual_policy_id=V3_VISUAL_POLICY_ID,
                visual_policy_hash=canonical_hash(self._visual_policy),
                stage_scopes=context.stage_scopes,
            )
        )
        return V3EvidenceNavigationRuntime(
            context=context,
            workflow=workflow,
            store=self._navigation_store,
            search=self._search,
            search_policy=self._search_policy,
        )

    def _navigation_exists(
        self, state: QuestionEvidenceSession, context: MaterializedEvidenceContext
    ) -> bool:
        return (
            self._navigation_store.load(
                run_id=state.run_id,
                result_id=state.result_id,
                domain_id=state.domain_id,
                question_id=context.question_id,
                obligation_hash=context.obligation_hash,
                inventory_snapshot_hash=context.inventory_snapshot_hash,
            )
            is not None
        )

    def _require_persisted_workflow(
        self,
        state: QuestionEvidenceSession,
        question_id: Identifier,
        workflow: V3EvidenceWorkflowState,
    ) -> None:
        context = self._context_for_question(state, question_id)
        persisted = self._navigation_store.load(
            run_id=state.run_id,
            result_id=state.result_id,
            domain_id=state.domain_id,
            question_id=question_id,
            obligation_hash=context.obligation_hash,
            inventory_snapshot_hash=context.inventory_snapshot_hash,
        )
        if persisted is None or persisted.workflow != workflow:
            raise QuestionEvidenceSessionContextMismatch(
                "question transition requires the exact current persisted v3 workflow"
            )
        expected = self._runtime_for_context(state, context).expected_workflow
        if (
            workflow.snapshot_hash != expected.snapshot_hash
            or workflow.obligation_revision_id != expected.obligation_revision_id
            or workflow.obligation != expected.obligation
            or workflow.obligation_hash != expected.obligation_hash
            or workflow.inventory_snapshot_hash != expected.inventory_snapshot_hash
            or workflow.authorized_inventory != expected.authorized_inventory
            or workflow.stage_scopes != expected.stage_scopes
            or workflow.search_policy_id != expected.search_policy_id
            or workflow.search_policy_hash != expected.search_policy_hash
            or workflow.read_policy_id != expected.read_policy_id
            or workflow.read_policy_hash != expected.read_policy_hash
            or workflow.visual_policy_id != expected.visual_policy_id
            or workflow.visual_policy_hash != expected.visual_policy_hash
        ):
            raise QuestionEvidenceSessionContextMismatch(
                "v3 workflow identity does not match the active session context"
            )

    def _current(self, expected_content_hash: ContentHash) -> QuestionEvidenceSession:
        state = self.load()
        if state.content_hash != expected_content_hash:
            raise StaleQuestionEvidenceSession(
                "question evidence session changed; reload and retry"
            )
        return state

    def _replay_if_applied(
        self,
        predecessor_session_hash: ContentHash,
        kind: str,
        transition_content_hash: ContentHash,
    ) -> QuestionEvidenceSessionTransition | None:
        """Recover exactly one saved session transition after a later bridge crash."""

        current = self.load()
        if current.content_hash == predecessor_session_hash:
            return None
        receipt = self._store.load_transition(self._seed, predecessor_session_hash)
        if (
            receipt is None
            or receipt.kind != kind
            or receipt.transition_content_hash != transition_content_hash
            or receipt.successor_session_hash != current.content_hash
        ):
            return None
        return QuestionEvidenceSessionTransition(
            receipt=receipt, projection=self.project(current), replayed=True
        )

    @staticmethod
    def _replace_ledger(
        state: QuestionEvidenceSession, ledger: ActiveQuestionLedger
    ) -> QuestionEvidenceSession:
        unsigned = state.model_copy(update={"ledger": ledger, "content_hash": ""})
        payload = unsigned.model_dump(mode="json")
        payload["content_hash"] = None
        return QuestionEvidenceSession.model_validate(
            payload | {"content_hash": canonical_hash(payload)}
        )
