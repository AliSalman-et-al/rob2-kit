from pathlib import Path
from threading import Event, Thread
from typing import Any

import pymupdf
import pytest

from rob2_kit import batch, storage
from rob2_kit.assessment import (
    Arm,
    BatchRequest,
    Comparison,
    OutcomeTarget,
    Proposal,
    Randomization,
    ResultAnchor,
    ResultSpec,
    Trial,
)
from rob2_kit.batch import PackIdentity, StaleBatch, approve_batch, current_batch, save_proposal
from rob2_kit.ingestion import ingest_batch
from rob2_kit.models import sha256
from rob2_kit.sources import SourceInput, SourceRole, TrialInput
from rob2_kit.storage import load_state, transaction


def proposal(tmp_path: Path):
    article = tmp_path / "main.pdf"
    if not article.exists():
        document = pymupdf.open()
        try:
            page = document.new_page()
            page.insert_text((72, 72), "anchor beta")
            document.save(article)
        finally:
            document.close()
    input_source = SourceInput(
        role=SourceRole.MAIN_ARTICLE,
        path="main.pdf",
        label="Main article",
    )

    ingested = ingest_batch(
        str(tmp_path),
        (TrialInput(id="t", label="T", sources=(input_source,)),),
    )

    source = ingested.trials[0].sources[0]
    spec = ResultSpec(
        id="r",
        trial=Trial(id="t", label="T"),
        randomization=Randomization(id="r", description="random"),
        arms=(Arm(id="a", label="A"), Arm(id="b", label="B")),
        comparison=Comparison(intervention_arm_id="a", comparator_arm_id="b"),
        effect_of_interest="assignment",
        outcome_definition="outcome",
        measurement="measure",
        time_point="time",
        population="all",
        analysis_method="method",
        analysis_choices=("choice",),
        effect_measure="RR",
        anchor=ResultAnchor(
            source_id=source.id,
            source_sha256=source.sha256,
            page_number=1,
            start=0,
            end=6,
            quote="anchor",
        ),
    )
    return Proposal(
        request=BatchRequest(
            outcome_target=OutcomeTarget(id="o", label="O", description="D"),
            trial_inputs=(
                TrialInput(
                    id="t",
                    label="T",
                    sources=(input_source,),
                ),
            ),
        ),
        trials=(Trial(id="t", label="T"),),
        result_specs=(spec,),
        sources=(source,),
    )


def proposal_b(tmp_path: Path) -> Proposal:
    draft = proposal(tmp_path)
    spec = draft.result_specs[0].model_copy(
        update={
            "id": "r_b",
            "anchor": draft.result_specs[0].anchor.model_copy(
                update={"start": 7, "end": 11, "quote": "beta"}
            ),
        }
    )
    return draft.model_copy(update={"result_specs": (spec,)})


def test_proposal_replace_approve_restart(tmp_path: Path):
    assert current_batch(tmp_path).status == "no_active"
    assert save_proposal(tmp_path, proposal(tmp_path)).state.status == "proposal"
    approved = approve_batch(tmp_path)
    assert approved.state.status == "approved" and approved.state.frozen_hash
    assert current_batch(tmp_path) == approved.state
    rejected = save_proposal(tmp_path, proposal(tmp_path))
    assert rejected.state.status == "stale"
    assert rejected.state.problems[0].code == "batch_already_approved"


def test_pack_identity_change_is_typed_stale(tmp_path: Path):
    save_proposal(tmp_path, proposal(tmp_path))
    approved = approve_batch(tmp_path)
    assert approved.state.status == "approved"
    changed = tuple(
        PackIdentity(id=item.id, version=item.version, content_hash="changed")
        for item in approved.state.pack_identities
    )
    stale = current_batch(tmp_path, pack_identities=changed)
    assert isinstance(stale, StaleBatch) and stale.problems[0].code == "pack_stale"


def test_current_batch_aggregates_source_and_pack_staleness_without_rewriting(tmp_path: Path):
    save_proposal(tmp_path, proposal(tmp_path))
    approved = approve_batch(tmp_path).state
    assert approved.status == "approved"
    stored = load_state(tmp_path)
    assert stored is not None
    captured = tmp_path / approved.proposal.sources[0].captured_path
    captured.write_bytes(b"changed")
    changed = tuple(
        PackIdentity(id=item.id, version=item.version, content_hash="changed")
        for item in approved.pack_identities
    )
    stale = current_batch(tmp_path, pack_identities=changed)
    assert isinstance(stale, StaleBatch)
    assert {problem.code for problem in stale.problems} >= {
        "source_inventory_invalid",
        "pack_stale",
    }
    assert load_state(tmp_path) == stored


def test_database_symlink_is_rejected(tmp_path: Path):
    import os

    outside = tmp_path.parent / "outside.sqlite3"
    outside.write_bytes(b"")
    internal = tmp_path / ".rob2-kit"
    internal.mkdir()
    try:
        os.symlink(outside, internal / "active-batch.sqlite3")
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    with pytest.raises(ValueError):
        current_batch(tmp_path)


def test_transaction_begin_failure_does_not_issue_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[str] = []

    class FailingConnection:
        def execute(self, command: str) -> None:
            commands.append(command)
            if command == "BEGIN IMMEDIATE":
                raise RuntimeError("begin failed")

        def close(self) -> None:
            commands.append("close")

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FailingConnection())
    with pytest.raises(RuntimeError, match="begin failed"):
        with transaction(tmp_path):
            pass
    assert "ROLLBACK" not in commands
    assert commands[-1] == "close"


@pytest.mark.parametrize(
    ("change", "code"),
    (
        ("path", "source_declarations_mismatch"),
        ("role", "source_declarations_mismatch"),
        ("label", "source_declarations_mismatch"),
        ("omission", "source_declarations_mismatch"),
    ),
)
def test_request_source_declaration_mismatch_is_structured(
    tmp_path: Path, change: str, code: str
) -> None:
    draft = proposal(tmp_path)
    source = draft.request.trial_inputs[0].sources[0]
    changed_sources: tuple[SourceInput, ...]
    if change == "omission":
        changed_sources = ()
    else:
        changed = source.model_copy(
            update={
                change: {"path": "other.pdf", "role": SourceRole.SUPPLEMENT, "label": "Other"}[
                    change
                ]
            }
        )
        changed_sources = (changed,)
    request = draft.request.model_copy(
        update={
            "trial_inputs": (
                draft.request.trial_inputs[0].model_copy(update={"sources": changed_sources}),
            )
        }
    )
    saved = save_proposal(tmp_path, draft.model_copy(update={"request": request}))
    assert saved.state.status == "proposal"
    assert any(problem.code == code for problem in saved.state.problems)


def test_proposal_rejects_public_local_source_records(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        Proposal.model_validate(
            {**proposal(tmp_path).model_dump(mode="json"), "local_source_records": []}
        )


def test_main_supplement_and_registry_are_the_exact_inventory(tmp_path: Path) -> None:
    from rob2_kit.registry import TrialFacts, capture_registry_source, match_registry

    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "anchor")
        document.save(tmp_path / "main.pdf")
    finally:
        document.close()
    (tmp_path / "supplement.txt").write_text("supplement")
    inputs = (
        SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main"),
        SourceInput(role=SourceRole.SUPPLEMENT, path="supplement.txt", label="Supplement"),
    )
    sources = (
        ingest_batch(tmp_path, (TrialInput(id="t", label="T", sources=inputs),)).trials[0].sources
    )
    main = next(source for source in sources if source.role is SourceRole.MAIN_ARTICLE)
    registry = capture_registry_source(
        str(tmp_path),
        "t",
        match_registry(
            TrialFacts(title="Example", randomized=True),
            lambda _: {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000001", "officialTitle": "Example"},
                    "designModule": {"designInfo": {"allocation": "RANDOMIZED"}},
                }
            },
            supplied_nct="NCT00000001",
        ),
    )
    draft = Proposal(
        request=BatchRequest(
            outcome_target=OutcomeTarget(id="o", label="O", description="D"),
            trial_inputs=(TrialInput(id="t", label="T", sources=inputs),),
        ),
        trials=(Trial(id="t", label="T"),),
        result_specs=(
            ResultSpec(
                id="r",
                trial=Trial(id="t", label="T"),
                randomization=Randomization(id="random", description="Random"),
                arms=(Arm(id="a", label="A"), Arm(id="b", label="B")),
                comparison=Comparison(intervention_arm_id="a", comparator_arm_id="b"),
                effect_of_interest="assignment",
                outcome_definition="outcome",
                measurement="measure",
                time_point="time",
                population="all",
                analysis_method="method",
                analysis_choices=("choice",),
                effect_measure="RR",
                anchor=ResultAnchor(
                    source_id=main.id,
                    source_sha256=main.sha256,
                    page_number=1,
                    start=0,
                    end=6,
                    quote="anchor",
                ),
            ),
        ),
        sources=sources + (registry,),
    )
    saved = save_proposal(tmp_path, draft)
    assert saved.state.status == "proposal"
    assert saved.state.problems == ()
    assert approve_batch(tmp_path).state.status == "approved"


@pytest.mark.parametrize("replacement_first", (False, True))
def test_replace_and_approval_serialize_a_real_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement_first: bool
) -> None:
    first = proposal(tmp_path)
    second = proposal_b(tmp_path)
    assert save_proposal(tmp_path, first).state.status == "proposal"
    entered = Event()
    release = Event()
    original = batch._problems

    def paused(workspace: str | Path, draft: Proposal) -> tuple[Any, ...]:
        target = second if replacement_first else first
        if draft == target and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(workspace, draft)

    monkeypatch.setattr(batch, "_problems", paused)
    results: dict[str, Any] = {}

    def replace() -> None:
        results["replace"] = save_proposal(tmp_path, second)

    def approve() -> None:
        results["approve"] = approve_batch(tmp_path)

    first_thread = Thread(target=replace if replacement_first else approve)
    second_thread = Thread(target=approve if replacement_first else replace)
    first_thread.start()
    assert entered.wait(5)
    second_thread.start()
    release.set()
    first_thread.join(5)
    second_thread.join(5)
    assert not first_thread.is_alive() and not second_thread.is_alive()
    approved = current_batch(tmp_path)
    assert approved.status == "approved"
    expected = second if replacement_first else first
    assert approved.proposal == expected
    assert approved.frozen_hash == sha256(
        {"proposal": approved.proposal, "packs": approved.pack_identities}
    )
    if replacement_first:
        assert results["replace"].state.status == "proposal"
    else:
        assert results["replace"].state.problems[0].code == "batch_already_approved"
