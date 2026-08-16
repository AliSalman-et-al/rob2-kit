from pathlib import Path

import pymupdf

from rob2_kit.assessment import (
    Arm,
    Comparison,
    OutcomeTarget,
    ProposalDraft,
    ProposalSaved,
    Randomization,
    ResultDraft,
)
from rob2_kit.batch import (
    ApprovedBatch,
    approve_proposal,
    current_batch,
    read_proposal_version,
    save_proposal_draft,
)
from rob2_kit.ingestion import ingest_batch, publish_captured_batch
from rob2_kit.judgment_models import (
    DomainAnswerDraft,
    DomainDraft,
    DomainDraftCommitOperation,
    DomainDraftOperation,
    DomainDraftValidated,
    DomainEvidenceUseDraft,
)
from rob2_kit.judgments import commit_domain_draft, validate_domain_draft
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.registry import RegistryCandidateRecord, RegistryMatch, RegistryStatus
from rob2_kit.retrieval import (
    EvidenceRetrievalBatch,
    TextQuoteSelection,
    TextSelectionResult,
    retrieve_batch,
)
from rob2_kit.sources import Source, SourceInput, SourceRole, TrialInput

_ANSWERS = {
    "domain:randomization": {"sequence": "yes", "concealment": "yes", "baseline-imbalance": "no"},
    "domain:deviations": {
        "participants-aware": "no",
        "personnel-aware": "no",
        "appropriate-analysis": "yes",
    },
    "domain:missing": {"data-available": "yes"},
    "domain:measurement": {
        "method-inappropriate": "no",
        "differential": "no",
        "assessor-aware": "no",
    },
    "domain:selection": {
        "prespecified-analysis": "yes",
        "multiple-measurements": "no",
        "multiple-analyses": "no",
    },
}


def approved_workspace(tmp_path: Path) -> tuple[Path, Source]:
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "random concealed balanced anchor")
        document.save(tmp_path / "main.pdf")
    finally:
        document.close()
    source_input = SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main")
    trial_input = TrialInput(id="t", label="T", sources=(source_input,))
    ingested = ingest_batch(tmp_path, (trial_input,))
    captured = publish_captured_batch(
        tmp_path,
        (trial_input,),
        ingested,
        {
            "t": RegistryCandidateRecord(
                trial_id="t", match=RegistryMatch(status=RegistryStatus.NOT_FOUND)
            )
        },
    )
    source = captured.trials[0].sources[0]
    selected = (
        retrieve_batch(
            tmp_path,
            EvidenceRetrievalBatch(
                trial_id="t",
                operations=(
                    TextQuoteSelection(
                        caller_id="anchor", source_id=source.id, page_number=1, quote="random"
                    ),
                ),
            ),
            (source,),
        )
        .operations[0]
        .result
    )
    assert isinstance(selected, TextSelectionResult)
    draft = ProposalDraft(
        outcome_target=OutcomeTarget(id="o", label="O", description="D"),
        results=(
            ResultDraft(
                result_id="r",
                randomization=Randomization(id="random", description="R"),
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
                anchor={"handle_id": selected.handle.handle_id},
            ),
        ),
    )
    saved = save_proposal_draft(tmp_path, draft)
    assert isinstance(saved, ProposalSaved)
    version = read_proposal_version(tmp_path, saved.version_hash)
    assert version is not None
    approved = approve_proposal(tmp_path, version.proposal_hash)
    assert approved.status == "approved"
    return tmp_path, source


def approved_two_trial_workspace(tmp_path: Path) -> tuple[Path, Source, Source]:
    inputs = []
    for trial_id in ("a", "b"):
        document = pymupdf.open()
        try:
            page = document.new_page()
            page.insert_text((72, 72), f"random concealed balanced anchor {trial_id}")
            document.save(tmp_path / f"{trial_id}.pdf")
        finally:
            document.close()
        inputs.append(
            TrialInput(
                id=trial_id,
                label=trial_id.upper(),
                sources=(
                    SourceInput(
                        role=SourceRole.MAIN_ARTICLE,
                        path=f"{trial_id}.pdf",
                        label=f"Main {trial_id}",
                    ),
                ),
            )
        )
    trial_inputs = tuple(inputs)
    ingested = ingest_batch(tmp_path, trial_inputs)
    captured = publish_captured_batch(
        tmp_path,
        trial_inputs,
        ingested,
        {
            trial_id: RegistryCandidateRecord(
                trial_id=trial_id, match=RegistryMatch(status=RegistryStatus.NOT_FOUND)
            )
            for trial_id in ("a", "b")
        },
    )
    sources = tuple(trial.sources[0] for trial in captured.trials)
    results = []
    for trial_id, source in zip(("a", "b"), sources, strict=True):
        selected = (
            retrieve_batch(
                tmp_path,
                EvidenceRetrievalBatch(
                    trial_id=trial_id,
                    operations=(
                        TextQuoteSelection(
                            caller_id="anchor",
                            source_id=source.id,
                            page_number=1,
                            quote="random",
                        ),
                    ),
                ),
                (source,),
            )
            .operations[0]
            .result
        )
        assert isinstance(selected, TextSelectionResult)
        results.append(
            ResultDraft(
                result_id="result",
                randomization=Randomization(id="random", description="R"),
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
                anchor={"handle_id": selected.handle.handle_id},
            )
        )
    saved = save_proposal_draft(
        tmp_path,
        ProposalDraft(
            outcome_target=OutcomeTarget(id="o", label="O", description="D"),
            results=tuple(results),
        ),
    )
    assert isinstance(saved, ProposalSaved)
    version = read_proposal_version(tmp_path, saved.version_hash)
    assert version is not None
    assert approve_proposal(tmp_path, version.proposal_hash).status == "approved"
    return tmp_path, sources[0], sources[1]


def domain_operation(
    workspace: Path,
    source: Source,
    approved: ApprovedBatch,
    domain_id: str,
    predecessor: str | None = None,
    *,
    limitation: str | None = None,
    trial_id: str = "t",
    result_id: str = "r",
) -> DomainDraftOperation:
    selected = (
        retrieve_batch(
            workspace,
            EvidenceRetrievalBatch(
                trial_id=trial_id,
                operations=(
                    TextQuoteSelection(
                        caller_id="evidence", source_id=source.id, page_number=1, quote="random"
                    ),
                ),
            ),
            (source,),
        )
        .operations[0]
        .result
    )
    assert isinstance(selected, TextSelectionResult)
    prefix = domain_id.split(":", 1)[1]
    answers = tuple(
        DomainAnswerDraft(
            question_id=f"sq:{prefix}:{name}",
            answer=value,
            rationale="reported",
            evidence_uses=(
                DomainEvidenceUseDraft(
                    relationship="supporting",
                    claim="reported",
                    rationale="direct text",
                    handle_ids=(selected.handle.token,),
                ),
            ),
        )
        for name, value in _ANSWERS[domain_id].items()
    )
    return DomainDraftOperation(
        approved_batch_hash=approved.frozen_hash,
        trial_id=trial_id,
        result_id=result_id,
        domain_id=domain_id,
        actor="researcher",
        expected_predecessor_hash=predecessor,
        draft=DomainDraft(
            active_answers=answers,
            limitations=() if limitation is None else (limitation,),
        ),
    )


def completed_workspace(tmp_path: Path) -> tuple[Path, Source]:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    for domain in SCIENTIFIC_PACK.domains:
        operation = domain_operation(workspace, source, approved, domain.id)
        validated = validate_domain_draft(workspace, operation)
        assert isinstance(validated, DomainDraftValidated)
        committed = commit_domain_draft(
            workspace,
            DomainDraftCommitOperation(
                **operation.model_dump(),
                validation_receipt=validated.receipt,
                reviewed_candidate_hash=validated.candidate_hash,
            ),
        )
        assert committed.status == "committed"
    return workspace, source
