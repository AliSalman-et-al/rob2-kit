import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Thread

import pymupdf
import pytest

from rob2_kit.assessment import (
    Arm,
    CapturedBatch,
    Comparison,
    OutcomeTarget,
    ProposalDraft,
    Randomization,
    ResultDraft,
)
from rob2_kit.batch import (
    ApprovedBatch,
    approve_proposal,
    current_batch,
    read_proposal_detail,
    read_proposal_version,
    save_proposal_draft,
)
from rob2_kit.detail import read_record
from rob2_kit.ingestion import ingest_batch, publish_captured_batch, read_captured_batch
from rob2_kit.models import canonical_json_bytes
from rob2_kit.recovery import current_batch_projection
from rob2_kit.registry import RegistryCandidateRecord, RegistryMatch, RegistryStatus
from rob2_kit.retrieval import (
    EvidenceRetrievalBatch,
    TextQuoteSelection,
    TextSelectionResult,
    retrieve_batch,
)
from rob2_kit.sources import SourceInput, SourceRole, TrialInput


def _draft(workspace: Path) -> ProposalDraft:
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "anchor beta")
        document.save(workspace / "main.pdf")
    finally:
        document.close()
    trial_input = TrialInput(
        id="trial",
        label="Trial",
        sources=(SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main"),),
    )
    ingested = ingest_batch(workspace, (trial_input,))
    registry = RegistryCandidateRecord(
        trial_id="trial", match=RegistryMatch(status=RegistryStatus.NOT_FOUND)
    )
    captured = publish_captured_batch(
        workspace,
        (trial_input,),
        ingested,
        {"trial": registry},
    )
    source = captured.trials[0].sources[0]
    retrieval = retrieve_batch(
        workspace,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                TextQuoteSelection(
                    caller_id="anchor",
                    source_id=source.id,
                    page_number=1,
                    quote="anchor",
                ),
            ),
        ),
        (source,),
    )
    outcome = retrieval.operations[0].result
    assert isinstance(outcome, TextSelectionResult)
    handle = outcome.handle
    return ProposalDraft(
        outcome_target=OutcomeTarget(id="outcome", label="Outcome", description="Description"),
        results=(
            ResultDraft(
                randomization=Randomization(id="random", description="Randomization"),
                arms=(Arm(id="a", label="A"), Arm(id="b", label="B")),
                comparison=Comparison(intervention_arm_id="a", comparator_arm_id="b"),
                effect_of_interest="effect",
                outcome_definition="definition",
                measurement="measure",
                time_point="time",
                population="population",
                analysis_method="method",
                analysis_choices=("choice",),
                effect_measure="RR",
                anchor={"handle_id": handle.handle_id},
            ),
        ),
    )


def test_v2_draft_is_immutable_and_approval_is_exact(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    saved = save_proposal_draft(tmp_path, draft)
    assert saved.status == "saved"
    assert saved.version_hash is not None
    version = read_proposal_version(tmp_path, saved.version_hash)
    assert version is not None
    assert read_proposal_detail(tmp_path, saved.version_hash) == version.proposal
    mismatch = approve_proposal(tmp_path, "sha256:" + "0" * 64)
    assert mismatch.status == "condition"
    approved = approve_proposal(tmp_path, version.proposal_hash)
    assert approved.status == "approved"
    assert approved.first_packet_ref is not None
    assert approved.first_packet_ref.kind == "domain"
    packet = read_record(tmp_path, approved.first_packet_ref)
    assert isinstance(packet, dict)
    assert packet["packet_hash"] == approved.first_packet_ref.identity
    assert "result_specs" not in approved.model_dump_json()


def test_saved_proposal_recovery_exposes_verified_active_version(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    first = save_proposal_draft(tmp_path, draft)
    assert first.status == "saved"
    first_projection = current_batch_projection(tmp_path)
    captured = read_captured_batch(tmp_path)
    assert captured is not None
    assert first_projection.phase == "proposal"
    assert first_projection.captured_batch_ref is not None
    assert first_projection.captured_batch_ref.identity == captured.content_hash
    assert first_projection.proposal_ref is not None
    assert first_projection.proposal_ref.identity == first.version_hash
    assert first_projection.next_action == "read_record"
    assert "proposal" not in first_projection.model_dump()

    revised = draft.model_copy(
        update={"outcome_target": draft.outcome_target.model_copy(update={"label": "Revised"})}
    )
    second = save_proposal_draft(tmp_path, revised)
    assert second.status == "saved"
    restarted = current_batch_projection(tmp_path)
    assert restarted.proposal_ref is not None
    assert restarted.proposal_ref.identity == second.version_hash
    assert restarted.proposal_ref.identity != first.version_hash


@pytest.mark.parametrize("corruption", ["missing", "malformed"])
def test_saved_proposal_recovery_fails_closed_on_active_version_corruption(
    tmp_path: Path, corruption: str
) -> None:
    saved = save_proposal_draft(tmp_path, _draft(tmp_path))
    assert saved.status == "saved"
    from rob2_kit.storage import transaction

    with transaction(tmp_path) as connection:
        key = f"proposal_version:{saved.version_hash}"
        if corruption == "missing":
            connection.execute("DELETE FROM records WHERE name=?", (key,))
        else:
            connection.execute("UPDATE records SET payload=? WHERE name=?", (b"{}", key))
    projection = current_batch_projection(tmp_path)
    assert projection.phase == "stale"
    assert projection.next_action == "discard"
    assert projection.conditions[0].code in {
        "corrupt_proposal_version",
        "proposal_version_unavailable",
    }


def test_corrupt_captured_source_is_shared_condition_without_repairs_or_writes(
    tmp_path: Path,
) -> None:
    draft = _draft(tmp_path)
    captured = read_captured_batch(tmp_path)
    assert captured is not None
    source = captured.trials[0].sources[0]
    path = tmp_path / source.captured_path
    path.write_bytes(path.read_bytes() + b"corrupt")
    from rob2_kit.storage import transaction

    with transaction(tmp_path) as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM records WHERE name LIKE 'proposal_version:%'"
        ).fetchone()[0]
    result = save_proposal_draft(tmp_path, draft)
    assert result.status == "condition"
    assert "repairs" not in result.model_dump()
    with transaction(tmp_path) as connection:
        after = connection.execute(
            "SELECT COUNT(*) FROM records WHERE name LIKE 'proposal_version:%'"
        ).fetchone()[0]
    assert after == before


def test_approval_freezes_proposal_and_intake_pointers(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    first = save_proposal_draft(tmp_path, draft)
    assert first.status == "saved"
    version = read_proposal_version(tmp_path, first.version_hash)
    assert version is not None
    approved = approve_proposal(tmp_path, version.proposal_hash)
    assert approved.status == "approved"
    before = current_batch(tmp_path)
    captured_before = read_captured_batch(tmp_path)

    changed = draft.model_copy(
        update={"outcome_target": draft.outcome_target.model_copy(update={"label": "Changed"})}
    )
    assert save_proposal_draft(tmp_path, changed).status == "condition"
    assert approve_proposal(tmp_path, "sha256:" + "0" * 64).status == "condition"
    with pytest.raises(ValueError, match="frozen"):
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="trial",
                    label="Trial",
                    sources=(
                        SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main"),
                    ),
                ),
            ),
        )
    assert current_batch(tmp_path) == before
    assert read_captured_batch(tmp_path) == captured_before


def test_intake_publication_and_proposal_save_have_one_consistent_winner(
    tmp_path: Path, monkeypatch
) -> None:
    draft = _draft(tmp_path)
    captured_before = read_captured_batch(tmp_path)
    assert captured_before is not None
    trial_input = captured_before.trial_inputs[0]
    alternate_ingest = ingest_batch(tmp_path, (trial_input,))
    alternate_registry = RegistryCandidateRecord(
        trial_id="trial", match=RegistryMatch(status=RegistryStatus.UNAVAILABLE)
    )

    import rob2_kit.batch as batch_module
    import rob2_kit.ingestion.service as ingestion_service

    barrier = Barrier(2)
    batch_transaction = batch_module.transaction
    ingestion_transaction = ingestion_service.transaction

    @contextmanager
    def synchronized_batch(workspace):
        barrier.wait()
        with batch_transaction(workspace) as connection:
            yield connection

    @contextmanager
    def synchronized_ingestion(workspace):
        barrier.wait()
        with ingestion_transaction(workspace) as connection:
            yield connection

    monkeypatch.setattr(batch_module, "transaction", synchronized_batch)
    monkeypatch.setattr(ingestion_service, "transaction", synchronized_ingestion)
    outcomes: list[object] = []

    def save() -> None:
        outcomes.append(save_proposal_draft(tmp_path, draft))

    def publish() -> None:
        try:
            outcomes.append(
                publish_captured_batch(
                    tmp_path,
                    (trial_input,),
                    alternate_ingest,
                    {"trial": alternate_registry},
                )
            )
        except ValueError as error:
            outcomes.append(error)

    threads = (Thread(target=save), Thread(target=publish))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    captured_after = read_captured_batch(tmp_path)
    saved = read_proposal_version(tmp_path)
    if saved is not None:
        assert captured_after is not None
        assert saved.captured_batch_hash == captured_after.content_hash
    assert len(outcomes) == 2


def test_invalid_anchor_returns_repairs_without_version(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    bad = draft.model_copy(
        update={
            "results": (
                draft.results[0].model_copy(
                    update={
                        "anchor": draft.results[0].anchor.model_copy(
                            update={"handle_id": "sha256:" + "0" * 64}
                        )
                    }
                ),
            )
        }
    )
    result = save_proposal_draft(tmp_path, bad)
    assert result.status == "repair"
    assert not hasattr(result, "version_hash")
    assert read_proposal_version(tmp_path) is None


def test_batch_detail_rejects_forged_embedded_identities(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    saved = save_proposal_draft(tmp_path, draft)
    assert saved.status == "saved"
    version = read_proposal_version(tmp_path)
    assert version is not None
    approved = approve_proposal(tmp_path, version.proposal_hash)
    assert approved.status == "approved"
    path = tmp_path / ".rob2-kit" / "active-batch.sqlite3"
    connection = sqlite3.connect(path)
    try:
        for identity, model, field in (
            (version.captured_batch_hash, CapturedBatch, "content_hash"),
            (approved.approved_batch_hash, ApprovedBatch, "frozen_hash"),
        ):
            key = f"detail:batch:{identity}"
            payload = connection.execute(
                "SELECT payload FROM records WHERE name=?", (key,)
            ).fetchone()
            assert payload is not None
            record = model.model_validate_json(bytes(payload[0]))
            forged = record.model_copy(update={field: "sha256:" + "0" * 64})
            connection.execute(
                "UPDATE records SET payload=? WHERE name=?", (canonical_json_bytes(forged), key)
            )
            connection.commit()
            with pytest.raises(ValueError, match="embedded identity mismatch"):
                read_record(tmp_path, f"rob2://detail/batch/{identity}")
            connection.execute("UPDATE records SET payload=? WHERE name=?", (payload[0], key))
            connection.commit()
    finally:
        connection.close()
