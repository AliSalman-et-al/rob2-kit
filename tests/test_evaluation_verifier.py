import json
from hashlib import sha256
from pathlib import Path

import pytest

from rob2_kit.evaluation.manifest import CHAARTED_MANIFEST
from rob2_kit.evaluation.verifier import _Bundle, _sources_and_evidence, verify_artifact


def _write_artifact(root: Path) -> None:
    records = root / "records"
    records.mkdir(parents=True)
    proposal = {
        "kind": "proposal_review",
        "results": [
            {
                "outcome_definition": (
                    "time to biochemical, symptomatic, or radiographic progression"
                ),
                "measurement": "median time to progression",
                "time_point": "follow-up analysis",
                "form": "comparative_effect",
            }
        ],
    }
    (records / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
    (records / "evidence.json").write_text(json.dumps({"kind": "evidence"}), encoding="utf-8")
    for number in range(5):
        (records / f"checkpoint-{number}.json").write_text(
            json.dumps({"kind": "domain_checkpoint"}), encoding="utf-8"
        )
    (records / "snapshot.json").write_text(
        json.dumps({"kind": "assessment_snapshot"}), encoding="utf-8"
    )
    summary = {"trials": [{"disposition": "assessed"}]}
    (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    rows = []
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        data = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": "sha256:" + sha256(data).hexdigest(),
            }
        )
    base = {"summary_hash": "sha256:test", "files": rows}
    manifest_hash = (
        "sha256:"
        + sha256(json.dumps(base, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    (root / "manifest.json").write_text(
        json.dumps({**base, "manifest_hash": manifest_hash}), encoding="utf-8"
    )


def test_verifier_demands_objective_facts_and_durable_artifacts(tmp_path: Path):
    _write_artifact(tmp_path)
    result = verify_artifact(tmp_path, CHAARTED_MANIFEST, "pfs")
    assert not result.ok
    assert result.failures


def _canonical(value: object) -> str:
    return (
        "sha256:"
        + sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )


def _ref(kind: str, identity: str) -> dict[str, str]:
    return {"kind": kind, "identity": identity, "uri": f"rob2://detail/{kind}/{identity}"}


@pytest.mark.parametrize(
    ("conditions", "authority", "caller", "valid"),
    (
        ([], "host", "host:adapter", True),
        (["review_required"], "researcher", "cli:researcher", True),
        (["review_required"], "host", "host:adapter", False),
        ([], "researcher", "cli:researcher", False),
    ),
)
def test_verifier_binds_intake_ack_authority_to_plan_conditions(
    tmp_path: Path, conditions: list[str], authority: str, caller: str, valid: bool
) -> None:
    plan_base = {
        "preflight": _ref("source_preflight", "sha256:" + "a" * 64),
        "entries": [],
        "blockers": [],
        "conditions": conditions,
    }
    plan_id = _canonical(plan_base)
    plan = {"kind": "intake_plan", "identity": plan_id, **plan_base}
    ack_base = {
        "record": _ref("intake_plan", plan_id),
        "authority": authority,
        "purpose": "intake",
        "caller": caller,
        "observed_at": "2026-08-21T00:00:00+00:00",
    }
    ack_id = _canonical(ack_base)
    ack = {"kind": "review_ack", "identity": ack_id, **ack_base}
    captured_base = {"plan": plan_id, "acknowledgment": ack_id, "sources": []}
    captured = {"kind": "captured_batch", "identity": _canonical(captured_base), **captured_base}
    failures: list[str] = []
    bundle = _Bundle(tmp_path, failures)
    bundle.names = {
        "captured_batch.json": captured,
        "intake_plan.json": plan,
        "review_ack.json": ack,
    }
    _sources_and_evidence(bundle, {"captured_batch": _ref("captured_batch", captured["identity"])})
    assert (not failures) is valid


def _ae_result() -> dict[str, object]:
    return {
        "form": "single_group_category_profile",
        "group_id": "docetaxel cohort",
        "categories": [
            {"label": "Grade 3", "value": "65 (16.7%)"},
            {"label": "Grade 4", "value": "49 (12.6%)"},
            {"label": "Grade 5", "value": "1 (0.3%)"},
        ],
        "outcome_definition": "adverse events during the docetaxel-containing regimen",
        "measurement": "CTCAE severity grade",
        "time_point": "during docetaxel-containing regimen follow-up",
        "intended_population": (
            "390 patients receiving the docetaxel-containing regimen with follow-up data"
        ),
        "source_table_meaning": (
            "single-group docetaxel-cohort Grade 3/4/5 category profile; "
            "no ADT-alone comparator coverage"
        ),
        "comparator_coverage": "unavailable",
    }


def _write_coherent_ae_bundle(
    root: Path,
    *,
    authority: str = "researcher",
    purpose: str = "proposal",
    terminal_ack: str | None = None,
    ack_record: dict[str, str] | None = None,
    presentation_summary: str | None = None,
) -> None:
    captured = _ref("captured_batch", "sha256:" + "c" * 64)
    proposal_base = {
        "captured_batch": captured,
        "outcome_statement": "adverse events",
        "results": [_ae_result()],
        "needs_input": [{"trial_id": "trial", "reason": "comparator_unavailable"}],
    }
    proposal_id = _canonical(proposal_base)
    proposal = {"kind": "proposal_review", "identity": proposal_id, **proposal_base}
    ack_base = {
        "record": ack_record or _ref("proposal_review", proposal_id),
        "authority": authority,
        "purpose": purpose,
        "caller": "cli:researcher",
        "observed_at": "2026-08-21T00:00:00+00:00",
    }
    ack_id = _canonical(ack_base)
    ack = {
        "kind": "review_ack",
        "identity": ack_id,
        "uri": f"rob2://detail/review_ack/{ack_id}",
        **ack_base,
    }
    approved_base = {
        "review": proposal_id,
        "acknowledgment": ack_id,
        "dispositions": [["trial", "needs_input"]],
    }
    approved_id = _canonical(approved_base)
    approved = {"kind": "approved_batch", "identity": approved_id, **approved_base}
    terminal_base = {
        "trial_id": "trial",
        "disposition": "needs_input",
        "reason": "comparator_unavailable",
        "missing_facts": ["ADT-alone comparator coverage"],
        "evidence": [],
        "acknowledgment": _ref("review_ack", terminal_ack or ack_id),
    }
    terminal_id = _canonical(terminal_base)
    terminal = {"kind": "trial_terminal", "identity": terminal_id, **terminal_base}
    counts = {"total": 1, "pending": 0, "assessed": 0, "needs_input": 1, "failed": 0}
    presentation = {
        "code": "finalized_zero_assessed",
        "headline": "Batch finalized",
        "summary": presentation_summary
        or "Batch finalized. No RoB 2 assessments were completed. 1 Trial needs researcher input.",
    }
    summary_base = {
        "approved_batch": _ref("approved_batch", approved_id),
        "counts": counts,
        "trials": [
            {
                "trial_id": "trial",
                "disposition": "needs_input",
                "outcome": _ref("trial_outcome", terminal_id),
                "snapshot": None,
            }
        ],
        "presentation": presentation,
    }
    summary_id = _canonical(summary_base)
    summary = {
        "kind": "finalization",
        "identity": summary_id,
        "observed_at": "2026-08-21T00:00:00+00:00",
        **summary_base,
    }
    receipt_base = {"summary": summary_id, "outcome": "committed"}
    receipt = {"kind": "finalization_receipt", "identity": _canonical(receipt_base), **receipt_base}
    records = root / "records"
    records.mkdir(parents=True)
    for name, value in {
        "proposal_review.json": proposal,
        "proposal_ack.json": ack,
        "approved_batch.json": approved,
        "trial-outcome-trial.json": terminal,
        "finalization-receipt.json": receipt,
    }.items():
        (records / name).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    (root / "report.html").write_text(
        f"<html>{presentation['summary']}</html>", encoding="utf-8"
    )
    files = []
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": "sha256:" + sha256(path.read_bytes()).hexdigest(),
            }
        )
    base = {"summary_hash": summary_id, "files": files}
    (root / "manifest.json").write_text(
        json.dumps({**base, "manifest_hash": _canonical(base)}, sort_keys=True), encoding="utf-8"
    )


def test_verifier_rejects_coherently_rehashed_ae_ack_authority_and_purpose(tmp_path: Path):
    authority_root = tmp_path / "authority"
    _write_coherent_ae_bundle(authority_root, authority="host")
    authority_result = verify_artifact(authority_root, CHAARTED_MANIFEST, "adverse_events")
    assert not authority_result.ok
    assert any("acknowledgment" in failure.casefold() for failure in authority_result.failures)

    purpose_root = tmp_path / "purpose"
    _write_coherent_ae_bundle(purpose_root, purpose="domain")
    result = verify_artifact(purpose_root, CHAARTED_MANIFEST, "adverse_events")
    assert not result.ok
    assert any("acknowledgment" in failure.casefold() for failure in result.failures)


def test_verifier_rejects_coherently_rehashed_ae_terminal_ack_binding(tmp_path: Path):
    _write_coherent_ae_bundle(tmp_path, terminal_ack="sha256:" + "d" * 64)
    result = verify_artifact(tmp_path, CHAARTED_MANIFEST, "adverse_events")
    assert not result.ok
    assert any("terminal identity" in failure for failure in result.failures)


def test_verifier_rejects_coherently_rehashed_proposal_ack_record(tmp_path: Path):
    _write_coherent_ae_bundle(
        tmp_path,
        ack_record=_ref("proposal_review", "sha256:" + "e" * 64),
    )
    result = verify_artifact(tmp_path, CHAARTED_MANIFEST, "adverse_events")
    assert not result.ok
    assert any("acknowledgment" in failure.casefold() for failure in result.failures)


def test_verifier_rejects_coherently_rehashed_presentation_and_report(tmp_path: Path):
    _write_coherent_ae_bundle(
        tmp_path, presentation_summary="Batch finalized. Everything succeeded."
    )
    result = verify_artifact(tmp_path, CHAARTED_MANIFEST, "adverse_events")
    assert not result.ok
    assert any("summary" in failure.casefold() for failure in result.failures)
