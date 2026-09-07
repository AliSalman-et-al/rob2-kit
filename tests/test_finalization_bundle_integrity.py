from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _option_for,
    _prepared_evidence,
    _proposal_args,
    _result,
    _review,
    _standalone_verify,
    _workspace,
)
from test_assessment_review_gate import _complete_assessment

from rob2_kit.application import finalization
from rob2_kit.application._state import _commit_records, _identity, _state
from rob2_kit.application.contracts import WorkflowConflict
from rob2_kit.application.evidence import search_sources
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.application.intake import prepare_batch
from rob2_kit.interfaces.mcp.contracts import validate_output
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import TrialDeclaration


def _rewrite_rehashed(source: Path, target: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    with zipfile.ZipFile(source) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    canonical = json.loads(files["canonical.json"])
    mutate(canonical)
    files["canonical.json"] = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    manifest = json.loads(files["manifest.json"])
    manifest["identity"] = _identity({"schema": "rob2-kit.bundle.v0.3", "canonical": canonical})
    verification = json.loads(files["verification.json"])
    verification["manifest_identity"] = manifest["identity"]
    files["verification.json"] = json.dumps(
        verification, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    for row in manifest["files"]:
        row["sha256"] = "sha256:" + hashlib.sha256(files[row["path"]]).hexdigest()
    files["manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])


def _artifact(workspace: Path) -> Path:
    _workspace, _evidence, revision = _complete_assessment(workspace)
    result = finalization.finalize_batch(workspace, revision)
    assert result["outcome"] == "success", result
    return workspace / result["artifact"]["path"]


def test_search_receipt_verifiers_accept_within_source_bm25_order(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "alpha beta " + "filler " * 500)
    document.new_page().insert_text((72, 72), "alpha beta")
    document.new_page().insert_text((72, 72), "alpha beta alpha")
    (trial / "main.pdf").write_bytes(document.tobytes())
    document.close()
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )

    receipt = search_sources(tmp_path, "trial", "alpha beta")["search_receipt"]
    pages = [hit["page"] for hit in receipt["hits"]]
    assert pages != sorted(pages)

    state = _state(tmp_path)
    authoritative = {source["id"]: source for source in state["batch"]["trials"][0]["sources"]}
    assert finalization._valid_search_account(
        receipt,
        "trial",
        state["batch"]["identity"],
        authoritative,
        _identity,
    )
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert standalone["_valid_search_account"](
        receipt,
        "trial",
        state["batch"]["identity"],
        authoritative,
        _identity,
    )

    for mutation in ("session", "duplicate_rank", "noncontiguous_rank"):
        malformed = json.loads(json.dumps(receipt))
        if mutation == "session":
            malformed["session_id"] = "sha256:" + "a" * 65
            malformed["session_handle"] = "ss_" + "a" * 16
        elif mutation == "duplicate_rank":
            malformed["returned_candidates"][1]["rank"] = malformed["returned_candidates"][0][
                "rank"
            ]
        else:
            malformed["returned_candidates"][1]["rank"] += 10
        malformed["identity"] = _identity(
            {key: value for key, value in malformed.items() if key not in {"identity", "handle"}}
        )
        malformed["handle"] = "sr_" + malformed["identity"].removeprefix("sha256:")[:16]
        assert not finalization._valid_search_account(
            malformed,
            "trial",
            state["batch"]["identity"],
            authoritative,
            _identity,
        )
        assert not standalone["_valid_search_account"](
            malformed,
            "trial",
            state["batch"]["identity"],
            authoritative,
            _identity,
        )


def test_probable_limitation_domain_basis_finalizes_after_derivative_restart(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "The requested outcome was not reported; only an alternate endpoint was measured; "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was measured in the "
        "analyzed population.; risk; 1; events; 2.\n" + "context\n" * 12 + "requested outcome\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required"
    _review(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    search = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested outcome", "mode": "any", "limit": 10},
    )["data"]
    assert search["truncated"] is False and search["exhausted"] is True
    assert len(search["hits"]) >= 2
    assert len({(hit["source_id"], hit["page"]) for hit in search["hits"]}) == 1
    receipt = search["search_receipt"]
    first = _domain_draft("trial", "domain:randomization", revision, search_receipt=receipt)
    first["answers"][0]["option_id"] = _option_for(
        first["answers"][0]["question_id"], "probably_yes"
    )
    first["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "text": (
                "The report describes an apparently adequate process but omits enough detail "
                "for a definitive judgment."
            ),
            "search_receipt": receipt,
        }
    ]
    saved = _call(workspace, "save_domain_judgment", first)
    assert saved["outcome"] == "success", saved
    revision = int(saved["head"]["state_revision"])
    for domain_id in (
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    ):
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain_id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    (workspace / ".rob2-kit" / "derivative.sqlite3").unlink()
    finalized = _call(workspace, "finalize_batch", {"expected_revision": revision})
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / finalized["data"]["artifact"]["path"]
    assert verify_bundle(artifact)
    standalone = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(artifact)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert standalone.returncode == 0, standalone.stderr or standalone.stdout

    def firm_without_direct_evidence(canonical: dict[str, Any]) -> None:
        key = "trial:domain:randomization"
        record = canonical["domain_records"][key]
        old_identity = record["identity"]
        record["answers"][0]["answer"] = "yes"
        record["identity"] = _identity(
            {
                field: record[field]
                for field in (
                    "trial_id",
                    "domain_id",
                    "answers",
                    "supersedes",
                    "revision_basis",
                    "search_accounts",
                    "active_questions",
                    "inactive_questions",
                    "judgment",
                    "trace",
                )
            }
        )
        canonical["domain_history"][key][-1] = record["identity"]
        canonical["domain_history_records"][key][-1] = record
        snapshot = canonical["snapshots"]["trial"]
        snapshot["checkpoints"] = [
            record["identity"] if item == old_identity else item for item in snapshot["checkpoints"]
        ]
        snapshot["identity"] = _identity(
            {field: value for field, value in snapshot.items() if field != "identity"}
        )
        canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]
        canonical["snapshot_history_records"]["trial"][-1] = snapshot

    tampered = tmp_path / "firm-limitation-tamper.rob2.zip"
    _rewrite_rehashed(artifact, tampered, firm_without_direct_evidence)
    assert not verify_bundle(tampered)
    rejected = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(tampered)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1


def test_rehashed_historical_probable_basis_tampering_fails_both_verifiers(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    receipt = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source", "mode": "any"}
    )["data"]["search_receipt"]
    initial = _domain_draft("trial", "domain:randomization", revision, search_receipt=receipt)
    initial["answers"][0]["option_id"] = _option_for(
        initial["answers"][0]["question_id"], "probably_yes"
    )
    initial["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "text": (
                "The report suggests an adequate process but omits enough detail for certainty."
            ),
            "search_receipt": receipt,
        }
    ]
    saved = _call(workspace, "save_domain_judgment", initial)
    assert saved["outcome"] == "success", saved
    revision = int(saved["head"]["state_revision"])
    current = _state(workspace)["domain_records"]["trial:domain:randomization"]
    revised = _domain_draft("trial", "domain:randomization", revision, evidence)
    revised["supersedes"] = current["identity"]
    revised["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "The current checkpoint corrects the earlier uncertain judgment.",
    }
    saved = _call(workspace, "save_domain_judgment", revised)
    assert saved["outcome"] == "success", saved
    revision = int(saved["head"]["state_revision"])
    for domain_id in (
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    ):
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain_id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    finalized = _call(
        workspace,
        "finalize_batch",
        {"expected_revision": revision},
    )
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / finalized["data"]["artifact"]["path"]
    assert verify_bundle(artifact)
    assert (
        subprocess.run(
            [sys.executable, "scripts/verify_bundle.py", str(artifact)], check=False
        ).returncode
        == 0
    )

    def tamper_historical_checkpoint(canonical: dict[str, Any]) -> None:
        key = "trial:domain:randomization"
        history = canonical["domain_history_records"][key]
        historical = history[0]
        old_historical_identity = historical["identity"]
        historical["answers"][0]["answer"] = "yes"
        historical["identity"] = _identity(
            {
                field: historical[field]
                for field in (
                    "trial_id",
                    "domain_id",
                    "answers",
                    "supersedes",
                    "revision_basis",
                    "search_accounts",
                    "active_questions",
                    "inactive_questions",
                    "judgment",
                    "trace",
                )
            }
        )
        history[0] = historical
        canonical["domain_history"][key][0] = historical["identity"]

        active = canonical["domain_records"][key]
        assert active["supersedes"] == old_historical_identity
        old_active_identity = active["identity"]
        active["supersedes"] = historical["identity"]
        active["identity"] = _identity(
            {
                field: active[field]
                for field in (
                    "trial_id",
                    "domain_id",
                    "answers",
                    "supersedes",
                    "revision_basis",
                    "search_accounts",
                    "active_questions",
                    "inactive_questions",
                    "judgment",
                    "trace",
                )
            }
        )
        history[-1] = active
        canonical["domain_history"][key][-1] = active["identity"]

        snapshot = canonical["snapshots"]["trial"]
        snapshot["checkpoints"] = [
            active["identity"] if item == old_active_identity else item
            for item in snapshot["checkpoints"]
        ]
        snapshot["identity"] = _identity(
            {field: value for field, value in snapshot.items() if field != "identity"}
        )
        canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]
        canonical["snapshot_history_records"]["trial"][-1] = snapshot

    tampered = tmp_path / "historical-firm-limitation-tamper.rob2.zip"
    _rewrite_rehashed(artifact, tampered, tamper_historical_checkpoint)
    assert not verify_bundle(tampered)
    rejected = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(tampered)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1


def _refresh_snapshot(canonical: dict[str, Any], key: str, old: str, new: str) -> None:
    canonical["domain_history"][key][-1] = new
    snapshot = canonical["snapshots"]["trial"]
    snapshot["checkpoints"] = [new if item == old else item for item in snapshot["checkpoints"]]
    snapshot["identity"] = _identity(
        {field: value for field, value in snapshot.items() if field != "identity"}
    )
    canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]
    canonical["snapshot_history_records"]["trial"][-1] = snapshot


def test_finalization_retry_rebuilds_identical_bytes(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    first_bytes = artifact.read_bytes()
    artifact.unlink()
    retry = finalization.finalize_batch(tmp_path, 0)
    rebuilt = tmp_path / retry["artifact"]["path"]
    assert rebuilt.read_bytes() == first_bytes
    assert retry["artifact"]["identity"]


def test_finalize_response_projects_frozen_assessment_summary_and_retry(
    tmp_path: Path,
) -> None:
    _workspace, _evidence, revision = _complete_assessment(tmp_path)
    first = _call(tmp_path, "finalize_batch", {"expected_revision": revision})
    assert first["outcome"] == "success", first
    snapshot = _state(tmp_path)["snapshots"]["trial"]
    expected = {
        "trial": {
            "overall": snapshot["overall"],
            "domains": snapshot["domain_judgments"],
        }
    }
    assert first["data"]["assessment_summary"] == expected
    assert first["data"]["trial_dispositions"] == {"trial": "assessed"}

    retry = _call(tmp_path, "finalize_batch", {"expected_revision": revision})
    assert retry["data"]["assessment_summary"] == expected
    assert retry["data"]["trial_dispositions"] == first["data"]["trial_dispositions"]
    assert retry["data"]["retry"] is True

    malformed = json.loads(json.dumps(first))
    malformed["data"]["assessment_summary"]["trial"]["domains"].pop("domain:selection")
    with pytest.raises(ValidationError):
        validate_output("finalize_batch", malformed)


def test_finalized_bundle_binds_the_scientific_contract(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))

    descriptor = canonical["scientific_pack"]
    official_sources = {
        (question.guidance.official.version, question.guidance.official.source_sha256)
        for question in SCIENTIFIC_PACK.questions
    }
    assert len(official_sources) == 1
    official_version, official_sha256 = next(iter(official_sources))
    assert descriptor == {
        "id": SCIENTIFIC_PACK.id,
        "version": SCIENTIFIC_PACK.version,
        "content_hash": SCIENTIFIC_PACK.content_hash,
        "official_source": {
            "version": official_version,
            "source_sha256": official_sha256,
        },
    }
    assert _standalone_verify(artifact).returncode == 0


@pytest.mark.parametrize("mutation", ["missing", "pack_hash", "source_hash"])
def test_scientific_contract_tampering_is_rejected(tmp_path: Path, mutation: str) -> None:
    artifact = _artifact(tmp_path)

    def tamper(canonical: dict[str, Any]) -> None:
        if mutation == "missing":
            del canonical["scientific_pack"]
            return
        field = "content_hash" if mutation == "pack_hash" else "official_source"
        if field == "content_hash":
            canonical["scientific_pack"][field] = "sha256:" + "0" * 64
        else:
            canonical["scientific_pack"][field]["source_sha256"] = "0" * 64

    tampered = tmp_path / f"scientific-contract-{mutation}.rob2.zip"
    _rewrite_rehashed(artifact, tampered, tamper)
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1


def test_malformed_canonical_answer_is_rejected_by_both_verifiers(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)

    def tamper(canonical: dict[str, Any]) -> None:
        key = "trial:domain:randomization"
        record = canonical["domain_records"][key]
        old_identity = record["identity"]
        record["answers"][0]["answer"] = "probably_maybe"
        record["identity"] = _identity(
            {
                field: record[field]
                for field in (
                    "trial_id",
                    "domain_id",
                    "answers",
                    "supersedes",
                    "revision_basis",
                    "search_accounts",
                    "active_questions",
                    "inactive_questions",
                    "judgment",
                    "trace",
                )
            }
        )
        canonical["domain_history"][key][-1] = record["identity"]
        canonical["domain_history_records"][key][-1] = record
        snapshot = canonical["snapshots"]["trial"]
        snapshot["checkpoints"] = [
            record["identity"] if identity == old_identity else identity
            for identity in snapshot["checkpoints"]
        ]
        snapshot["identity"] = _identity(
            {field: value for field, value in snapshot.items() if field != "identity"}
        )
        canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]
        canonical["snapshot_history_records"]["trial"][-1] = snapshot

    tampered = tmp_path / "malformed-answer.rob2.zip"
    _rewrite_rehashed(artifact, tampered, tamper)
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1


def test_finalization_retry_rebuilds_a_corrupt_deterministic_target(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    first_bytes = artifact.read_bytes()
    artifact.write_bytes(b"not a zip archive")

    retry = finalization.finalize_batch(tmp_path, 0)
    rebuilt = tmp_path / retry["artifact"]["path"]
    assert rebuilt.read_bytes() == first_bytes
    assert verify_bundle(rebuilt)


def test_rehashed_revision_lineage_tampering_fails_both_verifiers(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)

    def tamper(canonical: dict[str, Any]) -> None:
        key = "trial:domain:randomization"
        record = canonical["domain_records"][key]
        old_identity = record["identity"]
        record["supersedes"] = "sha256:" + "0" * 64
        record["identity"] = _identity(
            {
                field: record[field]
                for field in (
                    "trial_id",
                    "domain_id",
                    "answers",
                    "supersedes",
                    "revision_basis",
                    "search_accounts",
                    "active_questions",
                    "inactive_questions",
                    "judgment",
                    "trace",
                )
            }
        )
        _refresh_snapshot(canonical, key, old_identity, record["identity"])
        canonical["domain_history_records"][key][-1] = record

    tampered = tmp_path / "lineage-tamper.rob2.zip"
    _rewrite_rehashed(artifact, tampered, tamper)
    assert not verify_bundle(tampered)
    assert (
        subprocess.run(
            [sys.executable, "scripts/verify_bundle.py", str(tampered)], check=False
        ).returncode
        == 1
    )


def test_rehashed_proposal_acknowledgment_tampering_fails_both_verifiers(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)

    def tamper(canonical: dict[str, Any]) -> None:
        acknowledgment = canonical["proposal_acknowledgment"]
        acknowledgment["workflow_basis"] += 1
        acknowledgment["identity"] = _identity(
            {key: value for key, value in acknowledgment.items() if key != "identity"}
        )

    tampered = tmp_path / "ack-tamper.rob2.zip"
    _rewrite_rehashed(artifact, tampered, tamper)
    assert not verify_bundle(tampered)
    assert (
        subprocess.run(
            [sys.executable, "scripts/verify_bundle.py", str(tampered)], check=False
        ).returncode
        == 1
    )


def test_finalization_conflict_removes_new_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace, _evidence, revision = _complete_assessment(tmp_path)
    monkeypatch.setattr(
        finalization,
        "_commit_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            WorkflowConflict(int(revision), int(revision) + 1)
        ),
    )
    with pytest.raises(WorkflowConflict):
        finalization.finalize_batch(tmp_path, revision)
    assert not list((tmp_path / ".rob2-kit" / "finalized").glob("*.rob2.zip"))


@pytest.mark.parametrize("field", ("proposal_review", "proposal_acknowledgment"))
def test_finalization_requires_direct_proposal_authorization(tmp_path: Path, field: str) -> None:
    workspace, _evidence, revision = _complete_assessment(tmp_path)
    state = _state(workspace)
    state.pop(field)
    state = _commit_records(workspace, state, revision, {})

    with pytest.raises(ValueError, match="Proposal Review|Proposal acknowledgment"):
        finalization.finalize_batch(workspace, state["revision"])
