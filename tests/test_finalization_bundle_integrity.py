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
    _answer_value,
    _assessed_artifact,
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
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
    revision = _close_trials(workspace, revision)
    result = finalization.finalize_batch(workspace, revision)
    assert result["outcome"] == "success", result
    return workspace / result["artifact"]["path"]


def _close_trials(workspace: Path, expected_revision: int) -> int:
    status = _call(workspace, "get_status", {})
    assert status["head"]["state_revision"] == expected_revision
    while True:
        action = status["head"]["next_action"]
        assert isinstance(action, dict)
        operation = action.get("operation")
        if operation == "finalize_batch":
            return int(status["head"]["state_revision"])
        if operation == "review_trial":
            request = {
                "trial_id": action["trial_id"],
                "expected_revision": action["expected_revision"],
            }
        elif operation == "close_trial":
            request = {
                "trial_id": action["trial_id"],
                "expected_revision": action["expected_revision"],
                "review_reference": action["review_reference"],
            }
        else:
            raise AssertionError(f"cannot close Trials while next action is {operation!r}")
        receipt = _call(workspace, operation, request)
        assert receipt["outcome"] == "success", receipt
        status = _call(workspace, "get_status", {})


def _convert_group_bound_result_to_legacy(canonical: dict[str, Any]) -> None:
    payload = canonical["proposal"]["payload"]
    result = payload["results"][0]
    reported = result["reported"]
    if reported.get("form") != "group_bound_values":
        return
    reported["values"] = reported.pop("group_values")
    for binding in result["bindings"]:
        path = binding["field"]["path"]
        binding["field"]["path"] = path.replace("/reported/group_values/", "/reported/values/")
    proposal = canonical["proposal"]
    proposal["identity"] = _identity(payload)
    review = canonical["proposal_review"]
    review["candidate"]["proposal"] = payload
    review["candidate"]["identity"] = proposal["identity"]
    review["identity"] = _identity(
        {key: value for key, value in review.items() if key != "identity"}
    )
    acknowledgment = canonical["proposal_acknowledgment"]
    acknowledgment["review_identity"] = review["identity"]
    acknowledgment["identity"] = _identity(
        {key: value for key, value in acknowledgment.items() if key != "identity"}
    )
    proposal_history = canonical.get("proposal_history")
    if isinstance(proposal_history, list) and proposal_history:
        latest = proposal_history[-1]
        latest_proposal = latest["proposal"]
        latest_proposal["payload"] = payload
        latest_proposal["identity"] = proposal["identity"]
        latest["review"] = json.loads(json.dumps(review))
        latest["acknowledgment"] = json.loads(json.dumps(acknowledgment))
    _strip_result_bound_domain_lineage(canonical)


def _strip_result_bound_domain_lineage(canonical: dict[str, Any]) -> None:
    """Model pre-v0.8 records, which predate Result-bound Domain identities."""
    domain_fields = (
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
    identity_map: dict[str, str] = {}
    for key, records in canonical["domain_history_records"].items():
        legacy_records = []
        for record in records:
            old_identity = record["identity"]
            record.pop("result_identity", None)
            record["identity"] = _identity({field: record[field] for field in domain_fields})
            identity_map[old_identity] = record["identity"]
            legacy_records.append(record)
        canonical["domain_history_records"][key] = legacy_records
        canonical["domain_history"][key] = [
            identity_map.get(identity, identity) for identity in canonical["domain_history"][key]
        ]
        canonical["domain_records"][key] = legacy_records[-1]

    snapshot_identity_map: dict[str, str] = {}
    for trial_id, records in canonical["snapshot_history_records"].items():
        for snapshot in records:
            old_identity = snapshot["identity"]
            snapshot["checkpoints"] = [
                identity_map.get(identity, identity) for identity in snapshot["checkpoints"]
            ]
            snapshot.pop("result_identity", None)
            snapshot["identity"] = _identity(
                {field: value for field, value in snapshot.items() if field != "identity"}
            )
            snapshot_identity_map[old_identity] = snapshot["identity"]
        canonical["snapshot_history"][trial_id] = [
            snapshot_identity_map.get(identity, identity)
            for identity in canonical["snapshot_history"][trial_id]
        ]
        canonical["snapshot_history_records"][trial_id] = records
        canonical["snapshots"][trial_id] = records[-1]

    current_results = {
        result["trial_id"]: result for result in canonical["proposal"]["payload"]["results"]
    }
    for trial_id, review in canonical.get("trial_reviews", {}).items():
        # Trial attribution was introduced after the v0.7 bundle contract.
        # Remove it when converting a current artifact into a historical
        # fixture so its checkpoint references do not outlive the legacy
        # identity rewrite below.
        review.pop("domain_attribution", None)
        review["result_identity"] = _identity(current_results[trial_id])
        review["checkpoint_ids"] = [
            identity_map.get(checkpoint, checkpoint) for checkpoint in review["checkpoint_ids"]
        ]
        review["identity"] = _identity(
            {key: value for key, value in review.items() if key != "identity"}
        )
        closure = canonical["trial_closures"][trial_id]
        closure["review_identity"] = review["identity"]
        closure["identity"] = _identity(
            {key: value for key, value in closure.items() if key != "identity"}
        )


def test_search_receipt_verifiers_accept_global_bm25_order(tmp_path: Path) -> None:
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
    _read_required_main_reports(workspace)
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
    first["answers"][0]["answer"] = _answer_value(
        first["answers"][0]["question_id"], "probably_yes"
    )
    first["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "unresolved_premise": (
                "The report describes an apparently adequate process but omits enough detail "
                "for a definitive judgment."
            ),
            "stopping_rationale": "The relevant retrieved material does not resolve this premise.",
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
    revision = _close_trials(workspace, revision)
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
    initial["answers"][0]["answer"] = _answer_value(
        initial["answers"][0]["question_id"], "probably_yes"
    )
    initial["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "unresolved_premise": (
                "The report suggests an adequate process but omits enough detail for certainty."
            ),
            "stopping_rationale": "The relevant retrieved material does not resolve this premise.",
            "search_receipt": receipt,
        }
    ]
    saved = _call(workspace, "save_domain_judgment", initial)
    assert saved["outcome"] == "success", saved
    revision = int(saved["head"]["state_revision"])
    current = _state(workspace)["domain_records"]["trial:domain:randomization"]
    refreshed = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization"},
    )
    assert refreshed["outcome"] == "success", refreshed
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
        {"expected_revision": _close_trials(workspace, revision)},
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


def test_finalize_requires_an_explicit_trial_closure(tmp_path: Path) -> None:
    workspace, _evidence, revision = _complete_assessment(tmp_path)

    with pytest.raises(ValueError, match="current review and closure"):
        finalization.finalize_batch(workspace, revision)


def test_finalize_response_projects_frozen_assessment_summary_and_retry(
    tmp_path: Path,
) -> None:
    _workspace, _evidence, revision = _complete_assessment(tmp_path)
    revision = _close_trials(tmp_path, revision)
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
    artifact = _assessed_artifact(_workspace(tmp_path))
    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))

    assert set(canonical["trial_reviews"]) == {"trial"}
    assert set(canonical["trial_closures"]) == {"trial"}
    assert (
        canonical["trial_closures"]["trial"]["review_identity"]
        == canonical["trial_reviews"]["trial"]["identity"]
    )
    assert canonical["trial_closures"]["trial"]["disposition"] == "assessed"

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
        "result_semantics_version": "rob2-kit.result-semantics.v0.8",
    }
    assert _standalone_verify(artifact).returncode == 0


def test_prior_v08_scientific_pack_remains_verifiable(tmp_path: Path) -> None:
    source = _artifact(tmp_path / "source")

    def use_prior_guidance(canonical: dict[str, Any]) -> None:
        canonical["scientific_pack"]["content_hash"] = (
            "sha256:5c49411aedccf4cae2e3e97a955760ed83bd00283ff5a0ae5041272d13439b60"
        )

    prior = tmp_path / "prior-v08-guidance.rob2.zip"
    _rewrite_rehashed(source, prior, use_prior_guidance)
    assert verify_bundle(prior)
    assert _standalone_verify(prior).returncode == 0


@pytest.mark.parametrize(
    "content_hash",
    (
        "sha256:6d15307ced2cede1044b19507871c3b334c783868093f2015d372fb7b89f5a31",
        "sha256:9c293fbfaf1b10b82682a90d2e90986c3283fa1412f2c8b62a4d82a14a795dc8",
        "sha256:3ef492b34a81c19e3f75d72fea2b92c40aebde80c06e24e44c36cd76dc4cf3d4",
    ),
)
def test_previous_v07_scientific_packs_remain_verifiable(tmp_path: Path, content_hash: str) -> None:
    source = _artifact(tmp_path / "source")

    def use_previous_pack(canonical: dict[str, Any]) -> None:
        canonical["scientific_pack"]["result_semantics_version"] = "rob2-kit.result-semantics.v0.7"
        canonical["scientific_pack"]["content_hash"] = content_hash
        _convert_group_bound_result_to_legacy(canonical)

    previous = tmp_path / "previous-v07.rob2.zip"
    _rewrite_rehashed(source, previous, use_previous_pack)
    assert verify_bundle(previous)
    assert _standalone_verify(previous).returncode == 0


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


def test_rehashed_v06_empty_derived_inputs_fail_both_verifiers(tmp_path: Path) -> None:
    source = _artifact(tmp_path / "source")

    def convert_to_v06(canonical: dict[str, Any]) -> None:
        canonical["scientific_pack"]["result_semantics_version"] = "rob2-kit.result-semantics.v0.6"
        canonical["scientific_pack"]["content_hash"] = (
            "sha256:3ef492b34a81c19e3f75d72fea2b92c40aebde80c06e24e44c36cd76dc4cf3d4"
        )
        proposal = canonical["proposal"]
        payload = proposal["payload"]
        trial = canonical["batch"]["trials"][0]
        source = trial["sources"][0]
        payload["main_report_scopes"] = [
            {
                "trial_id": trial["id"],
                "source_id": source["id"],
                "source_sha256": source["sha256"],
                "projection_hash": source["projection_hash"],
                "end_page": source["page_count"],
                "boundary_evidence": [],
                "excluded_ranges": [],
            }
        ]
        payload["results"][0]["applicability"]["status"] = "supported"
        _convert_group_bound_result_to_legacy(canonical)
        proposal["identity"] = _identity(payload)
        review = canonical["proposal_review"]
        review["candidate"]["proposal"] = payload
        review["candidate"]["identity"] = proposal["identity"]
        review["identity"] = _identity(
            {key: value for key, value in review.items() if key != "identity"}
        )
        acknowledgment = canonical["proposal_acknowledgment"]
        acknowledgment["review_identity"] = review["identity"]
        acknowledgment["identity"] = _identity(
            {key: value for key, value in acknowledgment.items() if key != "identity"}
        )

    legacy = tmp_path / "v06-base.rob2.zip"
    _rewrite_rehashed(source, legacy, convert_to_v06)
    assert verify_bundle(legacy)
    assert _standalone_verify(legacy).returncode == 0

    def tamper(canonical: dict[str, Any]) -> None:
        proposal = canonical["proposal"]
        payload = proposal["payload"]
        payload["results"][0]["evidence"].append(
            {"kind": "derived", "operation": "sum", "inputs": [], "value": "0"}
        )
        proposal["identity"] = _identity(payload)
        review = canonical["proposal_review"]
        review["candidate"]["proposal"] = payload
        review["candidate"]["identity"] = proposal["identity"]
        review["identity"] = _identity(
            {key: value for key, value in review.items() if key != "identity"}
        )
        acknowledgment = canonical["proposal_acknowledgment"]
        acknowledgment["review_identity"] = review["identity"]
        acknowledgment["identity"] = _identity(
            {key: value for key, value in acknowledgment.items() if key != "identity"}
        )

    tampered = tmp_path / "v06-empty-derived-inputs.rob2.zip"
    _rewrite_rehashed(legacy, tampered, tamper)
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
    revision = _close_trials(tmp_path, revision)
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
    revision = _close_trials(workspace, revision)
    state = _state(workspace)
    state.pop(field)
    state = _commit_records(workspace, state, revision, {})

    with pytest.raises(ValueError, match="Proposal Review|Proposal acknowledgment"):
        finalization.finalize_batch(workspace, state["revision"])
