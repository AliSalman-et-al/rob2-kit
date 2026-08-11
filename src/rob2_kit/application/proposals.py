"""Pure projections and validation helpers for Run proposal revisions.

The durable proposal keeps the complete immutable discovery snapshot so the
engine can validate references and provenance.  Harnesses should instead use
the compact projection in this module: it exposes one row per requested
Trial × Outcome target without copying parser output into the conversation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from rob2_kit.application.contracts import (
    RunProposalPair,
)
from rob2_kit.domain.sources import (
    SourceAvailability,
    SourceDescriptor,
    SourceProcessing,
    SourceRole,
)
from rob2_kit.ingestion.project import OutcomeTarget, PageExtraction, ResultCandidate
from rob2_kit.storage.artifacts import ArtifactStore

if TYPE_CHECKING:
    from rob2_kit.application.contracts import RunProposal
    from rob2_kit.domain.sources import PageCoverage
    from rob2_kit.ingestion.project import ProjectInitialization


def _coverage_counts(coverage: tuple[PageCoverage, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for page in coverage:
        state = page.state.value
        counts[state] = counts.get(state, 0) + 1
    return counts


def _preferred_candidate(
    proposal: RunProposal,
    candidates: tuple[ResultCandidate, ...],
) -> tuple[ResultCandidate | None, str | None]:
    """Choose one explicitly metadata-ranked candidate, if uniquely grounded.

    Result labels and free-form provenance prose are deliberately ignored.
    Preference is available only when a ResultSpec declares a typed priority
    and binds its basis to an acquired protocol/SAP Source.
    """

    if not candidates:
        return None, None
    result_specs = {item.result.result_id: item for item in proposal.initialization.result_specs}
    trials = {item.trial_id: item for item in proposal.initialization.trials}
    scored: list[tuple[int, ResultCandidate]] = []
    for candidate in candidates:
        result_id = candidate.result_id
        spec = result_specs.get(result_id)
        trial = trials.get(candidate.trial_id)
        if spec is None or trial is None or spec.analysis_priority is None:
            continue
        preference_locator = spec.preference_source_locator
        if preference_locator is None:
            continue
        preference_sources = tuple(
            source
            for source in trial.inventory.sources
            if SourceRole.PROTOCOL in source.roles
            or SourceRole.STATISTICAL_ANALYSIS_PLAN in source.roles
        )
        if not any(
            _source_is_readable(source) and _locator_binds_source(preference_locator, source)
            for source in preference_sources
        ):
            continue
        priority = 2 if spec.analysis_priority == "protocol_primary" else 1
        scored.append((priority, candidate))
    if not scored:
        return None, None
    best_priority = max(item[0] for item in scored)
    best = tuple(item[1] for item in scored if item[0] == best_priority)
    if len(best) != 1:
        return None, None
    candidate = best[0]
    policy = (
        "protocol-defined primary analysis or prespecified cutoff is preferred "
        "from explicit protocol/SAP metadata; alternatives remain visible"
    )
    return candidate, policy


def _pairing_for_target(
    proposal: RunProposal,
    trial_id: str,
    target: OutcomeTarget,
) -> RunProposalPair:
    """Derive one complete Trial × Outcome disposition in one place."""

    target_id = target.target_id
    pair_candidates = tuple(
        item
        for item in proposal.result_candidates
        if item.trial_id == trial_id and item.outcome_target_id == target_id
    )
    selected = tuple(
        item
        for item in proposal.selections
        if item.trial_id == trial_id and item.outcome_target_id == target_id
    )
    removed = tuple(item for item in selected if item.removed)
    accepted = tuple(item for item in selected if item.accepted and not item.removed)
    excluded = tuple(item for item in selected if not item.accepted and not item.removed)
    preferred_candidate, selection_policy = _preferred_candidate(
        proposal,
        pair_candidates if target.time_point is None else (),
    )
    if removed:
        disposition = "removed"
        result_id = None
        preferred_result_id = None
        reason = removed[-1].exclusion_reason
    elif excluded:
        disposition = "excluded"
        result_id = None
        preferred_result_id = None
        reason = excluded[-1].exclusion_reason
    else:
        preferred_result_id = (
            preferred_candidate.result_id
            if preferred_candidate is not None and preferred_candidate.status == "resolved"
            else None
        )
        # A single Result candidate is never auto-bound: applicability requires
        # an explicit accepted selection even when it is the only candidate.
        result_id = next(
            (item.result_id for item in accepted if item.result_id is not None),
            None,
        )
        disposition = "selected" if result_id is not None else "unresolved"
        reason = None
    differences = ()
    if len({item.result_id for item in pair_candidates if item.result_id}) > 1:
        differences = ("Competing Result analyses could change selection; choose one explicitly.",)
    return RunProposalPair(
        trial_id=trial_id,
        outcome_target_id=target_id,
        candidate_ids=tuple(item.candidate_id for item in pair_candidates),
        result_id=result_id,
        preferred_result_id=preferred_result_id,
        selection_policy=selection_policy,
        disposition=disposition,
        exclusion_reason=reason,
        differences=differences,
    )


def proposal_pairings(proposal: RunProposal) -> tuple[RunProposalPair, ...]:
    """Project every requested Trial × Outcome target and its disposition."""

    targets = tuple(proposal.initialization.manifest.outcome_target_specs)
    return tuple(
        _pairing_for_target(proposal, trial.trial_id, target)
        for trial in proposal.initialization.trials
        for target in targets
    )


def effective_result_ids(proposal: RunProposal) -> tuple[str, ...]:
    """Return the Result identities included by a complete proposal revision.

    The same Trial × Outcome disposition projection used by the compact
    proposal drives the durable definition.  This prevents the wire summary
    and confirmation path from silently applying different default-selection
    rules.
    """

    if not proposal.outcome_targets:
        # Pre-target projects remain a supported migration shape. Their
        # declared Results are already exact Trial-specific assessment units.
        return proposal.result_ids
    selected = tuple(
        dict.fromkeys(
            pairing.result_id
            for pairing in proposal_pairings(proposal)
            if pairing.disposition == "selected" and pairing.result_id is not None
        )
    )
    # Explicit rob2.yaml Result declarations remain exact, pre-resolved input
    # inventory.  They must not disappear merely because a later proposal
    # revision has no source-derived candidate row for the declaration.
    # An explicit excluded/removed pairing is an intentional empty scope, not
    # an invitation to silently restore every inventoried Result.
    if any(
        pairing.disposition in {"selected", "excluded", "removed"}
        for pairing in proposal_pairings(proposal)
    ):
        return selected
    return proposal.result_ids


def compact_proposal_payload(proposal: RunProposal) -> dict[str, object]:
    """Return the bounded human proposal payload used by MCP responses."""

    targets = tuple(proposal.initialization.manifest.outcome_target_specs)
    trials = tuple(proposal.initialization.trials)
    result_specs = {item.result.result_id: item for item in proposal.initialization.result_specs}
    discovery_empty = not proposal.reported_endpoint_candidates
    return {
        "proposal_id": proposal.proposal_id,
        "proposal_token": proposal.proposal_token,
        "run_id": proposal.run_id,
        "supported_scope": proposal.supported_scope,
        "method_version": proposal.initialization.manifest.method_version,
        "effect_of_interest": proposal.initialization.manifest.effect_of_interest,
        "trial_ids": proposal.trial_ids,
        "result_ids": proposal.result_ids,
        "input_snapshot_hash": proposal.input_snapshot_hash,
        "outcome_targets": tuple(item.model_dump(mode="json") for item in targets),
        "pairings": tuple(item.model_dump(mode="json") for item in proposal_pairings(proposal)),
        "trials": tuple(
            {
                "trial_id": trial.trial_id,
                "status": trial.status,
                "inventory_id": trial.inventory.inventory_id,
                "source_count": len(trial.inventory.sources),
                "coverage_limitations": trial.inventory.coverage_limitations,
                "missing_sources": tuple(
                    {
                        "source_id": source.source_id,
                        "relative_path": source.relative_path,
                        "title": source.title,
                        "criticality": source.criticality,
                        "availability": source.availability,
                        "processing": source.processing,
                        "failure_category": source.failure_category,
                    }
                    for source in trial.inventory.sources
                    if source.availability is not SourceAvailability.ACQUIRED
                    or source.processing is SourceProcessing.FAILED
                ),
                "source_previews": tuple(
                    {
                        "source_id": source.source_id,
                        "title": source.title,
                        "relative_path": source.relative_path,
                        "roles": source.roles,
                        "criticality": source.criticality,
                        "availability": source.availability,
                        "processing": source.processing,
                        "coverage": {
                            state: count
                            for state, count in _coverage_counts(source.coverage).items()
                        },
                        "page_count": len(source.coverage),
                    }
                    for source in trial.inventory.sources
                ),
            }
            for trial in trials
        ),
        "registry_candidates": tuple(
            {
                "candidate_id": item.candidate_id,
                "trial_id": item.trial_id,
                "nct_id": item.nct_id,
                "status": item.status,
                "explicit": item.explicit,
                "source": item.source,
                "locator": item.locator,
            }
            for item in proposal.registry_candidates
        ),
        "result_candidates": tuple(
            {
                "candidate_id": item.candidate_id,
                "trial_id": item.trial_id,
                "outcome_target_id": item.outcome_target_id,
                "result_id": item.result_id,
                "label": item.label,
                "source_locator": item.source_locator,
                "status": item.status,
                "result_details": (
                    {
                        "randomization_id": result_specs[item.result_id].result.randomization_id,
                        "comparison": result_specs[item.result_id].result.comparison.model_dump(
                            mode="json"
                        ),
                        "effect_of_interest": (
                            result_specs[item.result_id].result.effect_of_interest
                        ),
                        "definition": result_specs[item.result_id].result.outcome_construct,
                        "measurement": result_specs[item.result_id].result.measurement_instrument,
                        "population": result_specs[item.result_id].result.analysis_population,
                        "analysis": result_specs[item.result_id].result.analysis_model,
                        "time_point": result_specs[item.result_id].result.time_point,
                        "effect_measure": result_specs[item.result_id].result.effect_measure,
                        "source_locator": result_specs[item.result_id].result.source_locator,
                        "provenance": result_specs[item.result_id].provenance_note,
                        "analysis_priority": result_specs[item.result_id].analysis_priority,
                        "preference_source_locator": (
                            result_specs[item.result_id].preference_source_locator
                        ),
                    }
                    if item.result_id in result_specs
                    else None
                ),
            }
            for item in proposal.result_candidates
        ),
        "result_details": tuple(
            {
                "result_id": result_id,
                "trial_id": spec.result.trial_id,
                "randomization_id": spec.result.randomization_id,
                "comparison": spec.result.comparison.model_dump(mode="json"),
                "effect_of_interest": spec.result.effect_of_interest,
                "definition": spec.result.outcome_construct,
                "measurement": spec.result.measurement_instrument,
                "population": spec.result.analysis_population,
                "analysis": spec.result.analysis_model,
                "time_point": spec.result.time_point,
                "effect_measure": spec.result.effect_measure,
                "source_locator": spec.result.source_locator,
                "provenance": spec.provenance_note,
                "analysis_priority": spec.analysis_priority,
                "preference_source_locator": spec.preference_source_locator,
            }
            for result_id, spec in sorted(result_specs.items())
        ),
        # Discovery is deliberately compacted, not hidden.  These are the
        # identifiers and source-bound observations a Harness needs for the
        # next promotion/mapping action; exact text remains behind the
        # token-scoped indexed read route.
        "reported_endpoint_candidates": tuple(
            item.model_dump(mode="json") for item in proposal.reported_endpoint_candidates
        ),
        "reported_randomization_candidates": tuple(
            item.model_dump(mode="json")
            for item in proposal.reported_randomization_candidates
        ),
        "reported_arm_candidates": tuple(
            item.model_dump(mode="json") for item in proposal.reported_arm_candidates
        ),
        "proposal_discovery_receipts": tuple(
            item.model_dump(mode="json") for item in proposal.proposal_discovery_receipts
        ),
        "limitations": tuple(item.model_dump(mode="json") for item in proposal.limitations),
        "promoted_design_bindings": {
            "randomizations": tuple(proposal.randomization_bindings),
            "arms": tuple(proposal.arm_bindings),
        },
        "promotion_batches": tuple(
            item.model_dump(mode="json") for item in proposal.promotion_batches
        ),
        "empty_state_diagnostic": (
            {
                "kind": "no_reported_endpoint_candidates",
                "detail": (
                    "No reported endpoint candidates were surfaced by completed "
                    "proposal discovery. Review the receipts and indexed source text."
                ),
                "receipt_ids": tuple(
                    item.receipt_id for item in proposal.proposal_discovery_receipts
                ),
            }
            if discovery_empty
            else None
        ),
        "ambiguities": tuple(item.model_dump(mode="json") for item in proposal.ambiguities),
        "source_limitations": proposal.source_limitations,
        "supersedes_proposal_id": proposal.supersedes_proposal_id,
        "semantic_diff": proposal.semantic_diff,
    }


def semantic_diff(before: RunProposal, after: RunProposal) -> tuple[str, ...]:
    """Describe meaning-level changes between two immutable proposals."""

    differences: list[str] = []
    if before.supported_scope != after.supported_scope:
        differences.append(
            f"Method scope changed from {before.supported_scope} to {after.supported_scope}."
        )
    if before.trial_ids != after.trial_ids:
        differences.append(f"Trial grouping changed from {before.trial_ids} to {after.trial_ids}.")
    before_pairs = {
        (item.trial_id, item.outcome_target_id): item for item in proposal_pairings(before)
    }
    after_pairs = {
        (item.trial_id, item.outcome_target_id): item for item in proposal_pairings(after)
    }
    for key in sorted(set(before_pairs) | set(after_pairs)):
        previous = before_pairs.get(key)
        current = after_pairs.get(key)
        label = f"{key[0]} × {key[1]}"
        if previous is None:
            differences.append(f"Added requested pairing {label}.")
            continue
        if current is None:
            differences.append(f"Removed requested pairing {label}.")
            continue
        if previous.result_id != current.result_id:
            differences.append(
                f"{label}: Result changed from {previous.result_id or 'unresolved'} "
                f"to {current.result_id or 'unresolved'}."
            )
        if previous.disposition != current.disposition:
            differences.append(
                f"{label}: disposition changed from {previous.disposition} "
                f"to {current.disposition}."
            )
        if previous.exclusion_reason != current.exclusion_reason:
            differences.append(f"{label}: exclusion reason changed.")
        if previous.differences != current.differences:
            differences.append(f"{label}: competing Result alternatives changed.")
    before_ambiguities = {item.ambiguity_id: item for item in before.ambiguities}
    after_ambiguities = {item.ambiguity_id: item for item in after.ambiguities}
    for ambiguity_id in sorted(set(before_ambiguities) | set(after_ambiguities)):
        old = before_ambiguities.get(ambiguity_id)
        new = after_ambiguities.get(ambiguity_id)
        if old is None and new is not None:
            differences.append(f"Added ambiguity: {new.detail}")
        elif old is not None and new is None:
            differences.append(f"Removed ambiguity: {old.detail}")
        elif old is not None and new is not None and old.resolved != new.resolved:
            differences.append(
                f"Ambiguity {ambiguity_id} changed to "
                f"{'resolved' if new.resolved else 'unresolved'}."
            )
    if (
        before.initialization.manifest.outcome_target_specs
        != after.initialization.manifest.outcome_target_specs
    ):
        differences.append("Outcome-target rules changed.")
    before_specs = {item.result.result_id: item for item in before.initialization.result_specs}
    after_specs = {item.result.result_id: item for item in after.initialization.result_specs}
    result_fields = (
        ("Trial", "trial_id"),
        ("Randomization", "randomization_id"),
        ("Comparison", "comparison"),
        ("effect of interest", "effect_of_interest"),
        ("definition", "outcome_construct"),
        ("measurement", "measurement_instrument"),
        ("population", "analysis_population"),
        ("analysis", "analysis_model"),
        ("time point", "time_point"),
        ("effect measure", "effect_measure"),
        ("source locator", "source_locator"),
    )
    for result_id in sorted(set(before_specs) | set(after_specs)):
        previous = before_specs.get(result_id)
        current = after_specs.get(result_id)
        if previous is None or current is None:
            differences.append(
                f"Result definition {result_id} was {'added' if previous is None else 'removed'}."
            )
            continue
        for label, field_name in result_fields:
            old_value = getattr(previous.result, field_name)
            new_value = getattr(current.result, field_name)
            if old_value != new_value:
                differences.append(
                    f"Result {result_id} {label} changed from {old_value!r} to {new_value!r}."
                )
        if previous.provenance_note != current.provenance_note:
            differences.append(f"Result {result_id} provenance changed.")
        if previous.analysis_priority != current.analysis_priority:
            differences.append(f"Result {result_id} analysis preference changed.")
        if previous.preference_source_locator != current.preference_source_locator:
            differences.append(f"Result {result_id} preference source changed.")
    return tuple(differences)


def validate_result_sources(
    initialization: ProjectInitialization,
    result_ids: Iterable[str],
    *,
    artifacts: ArtifactStore | None = None,
) -> tuple[str, ...]:
    """Return readable-source errors for included Result identities.

    Registry projections and metadata-only entries can orient a proposal but
    never satisfy the compulsory user-provided result-bearing full-text rule.
    """

    errors: list[str] = []
    specs = {item.result.result_id: item for item in initialization.result_specs}
    trials = {item.trial_id: item for item in initialization.trials}
    for result_id in dict.fromkeys(result_ids):
        spec = specs.get(result_id)
        if spec is None:
            # Engine-issued unresolved IDs receive their Source validation at
            # submit_result_resolution, after the ResultSpec is supplied.
            continue
        result = spec.result
        trial = trials.get(result.trial_id)
        if trial is None:
            errors.append(f"Result {result_id} references unknown Trial {result.trial_id}.")
            continue
        if trial.status == "trial_failed":
            # The Run will carry a diagnostic terminal outcome for an
            # unassessable Trial; it is not an included scientific Result.
            continue
        readable = False
        for source in trial.inventory.sources:
            if not set(source.roles).intersection(
                {
                    SourceRole.PRIMARY_REPORT,
                    SourceRole.SECONDARY_REPORT,
                    SourceRole.CLINICAL_STUDY_REPORT,
                    SourceRole.REGULATORY_DOCUMENT,
                }
            ):
                continue
            if source.availability is not SourceAvailability.ACQUIRED:
                continue
            if source.processing is SourceProcessing.FAILED:
                continue
            if source.artifact_hash is None or not source.parse_records:
                continue
            usable_page_numbers = {
                page.page_number for page in source.coverage if page.state.value == "text_usable"
            }
            pages = _source_pages(source, artifacts)
            if pages is None:
                continue
            page_number = _locator_page(result.source_locator)
            if page_number is not None:
                if page_number not in usable_page_numbers:
                    continue
                page = next((item for item in pages if item.page_number == page_number), None)
                if page is None or not page.text.strip():
                    continue
            elif len(pages) != 1:
                # A path-only locator cannot bind an exact canonical unit in a
                # multi-page report.  Require page precision rather than
                # treating arbitrary pages as evidence for the Result.
                continue
            elif not usable_page_numbers or not pages[0].text.strip():
                continue
            if _locator_binds_source(result.source_locator, source):
                readable = True
                break
        if not readable:
            errors.append(
                f"Result {result_id} for {result.trial_id} lacks a sufficiently readable "
                "user-provided result-bearing full text."
            )
    return tuple(errors)


def _locator_binds_source(locator: str, source: SourceDescriptor) -> bool:
    """Accept only an exact source token plus a bounded locator suffix."""

    normalized = _normalize_locator(locator)
    source_tokens = (
        source.source_id.casefold(),
        source.relative_path.casefold().replace("\\", "/"),
        source.title.casefold(),
    )
    for token in source_tokens:
        if normalized == token or normalized.startswith(token + "#"):
            return True
        if normalized.startswith(token + " "):
            return True
        if normalized.startswith(token + "/"):
            suffix = normalized[len(token) + 1 :]
            if suffix.startswith(("table:", "row:", "section:", "result:")):
                return True
    if SourceRole.PRIMARY_REPORT in source.roles and normalized.startswith("report:primary"):
        suffix = normalized.removeprefix("report:primary")
        return suffix in {"", "/table:1", "/table:2"} or suffix.startswith(
            ("/table:", "/row:", "#", " ")
        )
    return False


def _source_is_readable(source: SourceDescriptor) -> bool:
    """Require inspected local bytes before using a Source to rank Results."""

    return (
        source.availability is SourceAvailability.ACQUIRED
        and source.processing in {SourceProcessing.USABLE, SourceProcessing.COVERAGE_LIMITED}
        and source.artifact_hash is not None
        and bool(source.parse_records)
        and any(page.state.value == "text_usable" for page in source.coverage)
    )


def _normalize_locator(locator: str) -> str:
    return " ".join(locator.casefold().replace("\\", "/").split())


def _locator_page(locator: str) -> int | None:
    match = re.search(r"(?:^|[#/\s])p(?:age)?\s*[.:=]?\s*(\d+)\b", locator, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _source_pages(
    source: SourceDescriptor,
    artifacts: ArtifactStore | None,
) -> tuple[PageExtraction, ...] | None:
    if artifacts is None:
        return None
    record = next(
        (
            item
            for item in source.parse_records
            if not item.ocr_enabled and item.page_artifact_hash is not None
        ),
        None,
    )
    if record is None or record.page_artifact_hash is None:
        return None
    try:
        payload = json.loads(artifacts.read(record.page_artifact_hash))
    except (ValueError, TypeError, RuntimeError):
        return None
    if not isinstance(payload, list):
        return None
    try:
        return tuple(PageExtraction.model_validate(item) for item in payload)
    except (TypeError, ValueError):
        return None


__all__ = [
    "compact_proposal_payload",
    "effective_result_ids",
    "proposal_pairings",
    "semantic_diff",
    "validate_result_sources",
]
