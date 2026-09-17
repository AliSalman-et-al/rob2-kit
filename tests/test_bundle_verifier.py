"""Product and standalone finalized-bundle verification tests."""

# Shared private helpers keep caller setup out of the scenarios.
# ruff: noqa: F405

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from support.rob2 import *  # noqa: F401,F403

from rob2_kit.application._state import _identity
from rob2_kit.application.finalization import (
    _contains_forbidden_paths,
    _valid_batch,
    _valid_selected_evidence,
    verify_bundle,
)
from rob2_kit.workflow_models import CapturedTrial


def test_rehashed_bundle_boundary_tampering_fails_product_and_standalone(
    tmp_path: Path,
) -> None:
    artifact = _assessed_artifact(_workspace(tmp_path))

    def rehash_batch(canonical: dict[str, Any]) -> None:
        for trial in canonical["batch"]["trials"]:
            trial["identity"] = _identity(
                {key: value for key, value in trial.items() if key != "identity"}
            )
        canonical["batch"]["identity"] = _identity(
            {
                "trials": canonical["batch"]["trials"],
                "conditions": canonical["batch"]["conditions"],
            }
        )

    cases = (
        lambda canonical: (
            canonical["batch"].update({"trials": []}),
            canonical["batch"].update(
                {
                    "identity": _identity(
                        {
                            "trials": [],
                            "conditions": canonical["batch"]["conditions"],
                        }
                    )
                }
            ),
        ),
        lambda canonical: (
            canonical["batch"]["trials"][0]["sources"][0].update({"page_count": "1"}),
            rehash_batch(canonical),
        ),
        lambda canonical: canonical["domain_records"]["trial:domain:randomization"].update(
            {"hidden": True}
        ),
        lambda canonical: canonical["proposal"]["payload"]["results"][0]["target"].update(
            {"intended_effect_measure": ""}
        ),
        lambda canonical: canonical["proposal"]["payload"]["results"][0]["evidence"].__setitem__(
            0,
            {
                "kind": "derived",
                "operation": "sum",
                "inputs": [{"handle": "eh_invalid", "value": 1}],
                "value": "1",
            },
        ),
    )
    for index, mutate in enumerate(cases):
        tampered = tmp_path / f"shape-tamper-{index}.rob2.zip"
        _rehashed_full_tamper(artifact, tampered, mutate)
        assert not verify_bundle(tampered)
        assert _standalone_verify(tampered).returncode == 1

    with zipfile.ZipFile(artifact) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        manifest["unexpected"] = True
        changed = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_tamper = tmp_path / "manifest-shape-tamper.rob2.zip"
    _rewrite_zip(artifact, manifest_tamper, {"manifest.json": changed})
    assert not verify_bundle(manifest_tamper)
    assert _standalone_verify(manifest_tamper).returncode == 1


def test_standalone_verifier_rejects_targeted_claim_tampering(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    artifact = _assessed_artifact(workspace)
    with zipfile.ZipFile(artifact) as archive:
        original_manifest = archive.read("manifest.json")
        original_canonical = archive.read("canonical.json")
        original_report = archive.read("report.html")
        original_verification = archive.read("verification.json")

    # A stale manifest hash is rejected before any application import.
    stale = tmp_path / "stale-manifest.zip"
    with zipfile.ZipFile(artifact) as archive:
        manifest = json.loads(original_manifest)
        manifest["files"][0]["sha256"] = "sha256:" + "0" * 64
        _rewrite_zip(
            artifact,
            stale,
            {"manifest.json": json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()},
        )
    assert _standalone_verify(stale).returncode == 1

    canonical = json.loads(original_canonical)
    canonical["proposal"]["payload"]["results"][0]["bindings"][0]["value_digest"] = (
        "sha256:" + "0" * 64
    )
    changed_canonical = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    changed_manifest = _update_manifest_hash(original_manifest, "canonical.json", changed_canonical)
    evidence_tamper = tmp_path / "evidence-tamper.zip"
    _rewrite_zip(
        artifact,
        evidence_tamper,
        {"canonical.json": changed_canonical, "manifest.json": changed_manifest},
    )
    assert _standalone_verify(evidence_tamper).returncode == 1

    canonical = json.loads(original_canonical)
    canonical["proposal"]["payload"]["results"][0]["bindings"][0]["value_digest"] = (
        "sha256:" + "f" * 64
    )
    changed_canonical = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    changed_manifest = _update_manifest_hash(original_manifest, "canonical.json", changed_canonical)
    mapping_tamper = tmp_path / "mapping-value-tamper.zip"
    _rewrite_zip(
        artifact,
        mapping_tamper,
        {"canonical.json": changed_canonical, "manifest.json": changed_manifest},
    )
    assert _standalone_verify(mapping_tamper).returncode == 1

    canonical = json.loads(original_canonical)
    snapshot = canonical["snapshots"]["trial"]
    snapshot["overall"] = "low"
    changed_canonical = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    changed_manifest = _update_manifest_hash(original_manifest, "canonical.json", changed_canonical)
    snapshot_tamper = tmp_path / "snapshot-tamper.zip"
    _rewrite_zip(
        artifact,
        snapshot_tamper,
        {"canonical.json": changed_canonical, "manifest.json": changed_manifest},
    )
    assert _standalone_verify(snapshot_tamper).returncode == 1

    changed_report = original_report.replace(b'"trial": "assessed"', b'"trial": "failed"')
    changed_manifest = _update_manifest_hash(original_manifest, "report.html", changed_report)
    html_tamper = tmp_path / "html-tamper.zip"
    _rewrite_zip(
        artifact,
        html_tamper,
        {"report.html": changed_report, "manifest.json": changed_manifest},
    )
    assert _standalone_verify(html_tamper).returncode == 1

    verification = json.loads(original_verification)
    verification["manifest_identity"] = "sha256:" + "f" * 64
    changed_verification = json.dumps(verification, sort_keys=True, separators=(",", ":")).encode()
    changed_manifest = _update_manifest_hash(
        original_manifest, "verification.json", changed_verification
    )
    json_tamper = tmp_path / "json-tamper.zip"
    _rewrite_zip(
        artifact,
        json_tamper,
        {"verification.json": changed_verification, "manifest.json": changed_manifest},
    )
    assert _standalone_verify(json_tamper).returncode == 1


def test_standalone_verifier_rejects_incomplete_assessed_domain_coverage(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    artifact = _assessed_artifact(workspace)
    with zipfile.ZipFile(artifact) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    canonical = json.loads(files["canonical.json"])
    removed_domain = "domain:selection"
    domain_key = f"trial:{removed_domain}"
    del canonical["domain_records"][domain_key]
    del canonical["domain_history"][domain_key]
    del canonical["domain_history_records"][domain_key]
    snapshot = canonical["snapshots"]["trial"]
    snapshot["checkpoints"].pop()
    del snapshot["domain_judgments"][removed_domain]
    snapshot["identity"] = _identity(
        {key: value for key, value in snapshot.items() if key != "identity"}
    )
    canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]
    canonical["snapshot_history_records"]["trial"][-1] = snapshot
    files["canonical.json"] = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    manifest = json.loads(files["manifest.json"])
    manifest["identity"] = _identity({"schema": "rob2-kit.bundle.v0.3", "canonical": canonical})
    files["verification.json"] = json.dumps(
        {
            "schema": "rob2-kit.independent-verifier-input.v0.3",
            "manifest_identity": manifest["identity"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    for row in manifest["files"]:
        row["sha256"] = "sha256:" + hashlib.sha256(files[row["path"]]).hexdigest()
    files["manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    tampered = tmp_path / "incomplete-domains.rob2.zip"
    with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    rejected = _standalone_verify(tampered)
    assert rejected.returncode == 1
    assert "snapshot history semantics are invalid" in rejected.stdout


def test_domain_shape_and_question_tampering_fails_both_bundle_verifiers(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    artifact = _assessed_artifact_with_domain_evidence(workspace)

    def tamper(canonical: dict[str, Any]) -> None:
        key = "trial:domain:randomization"
        record = canonical["domain_records"][key]
        old_identity = record["identity"]
        record["answers"][0]["bases"][0]["source"] = "invented explanation"
        record["answers"][0]["question_id"] = "sq:randomization:not-active"
        fields = (
            "trial_id",
            "domain_id",
            "answers",
            "search_accounts",
            "active_questions",
            "inactive_questions",
            "judgment",
            "trace",
        )
        record["identity"] = _identity({field: record[field] for field in fields})
        canonical["domain_history"][key][-1] = record["identity"]
        snapshot = canonical["snapshots"]["trial"]
        snapshot["checkpoints"] = [
            record["identity"] if value == old_identity else value
            for value in snapshot["checkpoints"]
        ]
        snapshot["identity"] = _identity(
            {field: value for field, value in snapshot.items() if field != "identity"}
        )
        canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]

    tampered = tmp_path / "domain-source-tamper.rob2.zip"
    _rehashed_domain_tamper(artifact, tampered, tamper)
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1


def test_selected_evidence_catalog_is_closed_and_source_bound() -> None:
    source_sha = "sha256:" + "1" * 64
    source_id = "source_" + hashlib.sha256(f"trial\0main.txt\0{source_sha}".encode()).hexdigest()
    source: dict[str, object] = {
        "id": source_id,
        "trial_id": "trial",
        "role": "main_article",
        "label": "main.txt",
        "logical_path": "main.txt",
        "sha256": source_sha,
        "media_type": "text/plain",
        "page_count": 1,
        "projection_hash": "sha256:" + "2" * 64,
        "origin": "local_dossier",
    }
    evidence: dict[str, Any] = {
        "kind": "narrative",
        "trial_id": "trial",
        "source_id": source_id,
        "page": 1,
        "start": 0,
        "end": 8,
        "quote": "evidence",
    }
    evidence["identity"] = _identity(evidence)
    evidence["handle"] = "eh_" + evidence["identity"].removeprefix("sha256:")[:16]
    sources: dict[str, dict[str, object]] = {source_id: source}
    assert _valid_selected_evidence(evidence, sources, _identity)
    assert standalone_valid_selected_evidence(evidence, sources, _identity)

    fabricated = {**evidence, "hidden": "invented"}
    fabricated["identity"] = _identity(
        {key: value for key, value in fabricated.items() if key not in {"identity", "handle"}}
    )
    fabricated["handle"] = "eh_" + fabricated["identity"].removeprefix("sha256:")[:16]
    assert not _valid_selected_evidence(fabricated, sources, _identity)
    assert not standalone_valid_selected_evidence(fabricated, sources, _identity)

    unknown_source = {**evidence, "source_id": "source_" + "f" * 64}
    unknown_source["identity"] = _identity(
        {key: value for key, value in unknown_source.items() if key not in {"identity", "handle"}}
    )
    unknown_source["handle"] = "eh_" + unknown_source["identity"].removeprefix("sha256:")[:16]
    assert not _valid_selected_evidence(unknown_source, sources, _identity)
    assert not standalone_valid_selected_evidence(unknown_source, sources, _identity)

    for malformed in (
        {
            **evidence,
            "search_session": "not-a-sha",
            "candidate_rank": 1,
            "start_line": 1,
            "end_line": 1,
        },
        {
            **evidence,
            "start": 0,
            "end": 1,
            "quote": "x",
            "start_line": 500,
            "end_line": 999,
        },
    ):
        malformed["identity"] = _identity(
            {key: value for key, value in malformed.items() if key not in {"identity", "handle"}}
        )
        malformed["handle"] = "eh_" + malformed["identity"].removeprefix("sha256:")[:16]
        assert not _valid_selected_evidence(malformed, sources, _identity)
        assert not standalone_valid_selected_evidence(malformed, sources, _identity)

    render = {
        "source_id": source_id,
        "page": 1,
        "png_sha256": "sha256:" + "3" * 64,
        "recipe": "page-png-v1",
    }
    render["identity"] = _identity(
        {
            "source_id": source_id,
            "source_sha256": source_sha,
            "page": 1,
            "recipe": "page-png-v1",
        }
    )
    figure: dict[str, Any] = {
        "kind": "figure",
        "trial_id": "trial",
        "source_id": source_id,
        "render": render,
        "delivery_receipt": _identity(
            {
                "trial_id": "trial",
                "source_id": source_id,
                "render_identity": render["identity"],
                "png_sha256": render["png_sha256"],
                "channel": "mcp_image_content",
                "mime_type": "image/png",
            }
        ),
        "transcription": "Figure evidence",
        "region": [0.1, 0.1, 0.9, 0.9],
        "provenance": "host_visual",
    }
    figure["identity"] = _identity(figure)
    figure["handle"] = "eh_" + figure["identity"].removeprefix("sha256:")[:16]
    assert _valid_selected_evidence(figure, sources, _identity)
    assert standalone_valid_selected_evidence(figure, sources, _identity)
    figure["delivery_receipt"] = "sha256:" + "4" * 64
    figure["identity"] = _identity(
        {key: value for key, value in figure.items() if key not in {"identity", "handle"}}
    )
    figure["handle"] = "eh_" + figure["identity"].removeprefix("sha256:")[:16]
    assert not _valid_selected_evidence(figure, sources, _identity)
    assert not standalone_valid_selected_evidence(figure, sources, _identity)
    figure["delivery_receipt"] = _identity(
        {
            "trial_id": "trial",
            "source_id": source_id,
            "render_identity": render["identity"],
            "png_sha256": render["png_sha256"],
            "channel": "mcp_image_content",
            "mime_type": "image/png",
        }
    )
    figure["identity"] = _identity(
        {key: value for key, value in figure.items() if key not in {"identity", "handle"}}
    )
    figure["handle"] = "eh_" + figure["identity"].removeprefix("sha256:")[:16]
    figure["render"]["png_sha256"] = "invented"
    figure["identity"] = _identity(
        {key: value for key, value in figure.items() if key not in {"identity", "handle"}}
    )
    figure["handle"] = "eh_" + figure["identity"].removeprefix("sha256:")[:16]
    assert not _valid_selected_evidence(figure, sources, _identity)
    assert not standalone_valid_selected_evidence(figure, sources, _identity)


def test_batch_value_shapes_match_standalone_verifier() -> None:
    source_sha = "sha256:" + "1" * 64
    source_id = "source_" + hashlib.sha256(f"trial\0main.txt\0{source_sha}".encode()).hexdigest()
    trial: dict[str, Any] = {
        "id": "trial",
        "label": "Trial",
        "requested_outcome": "overall survival",
        "sources": [
            {
                "id": source_id,
                "trial_id": "trial",
                "role": "main_article",
                "label": "main.txt",
                "logical_path": "main.txt",
                "sha256": source_sha,
                "media_type": "text/plain",
                "page_count": 1,
                "projection_hash": "sha256:" + "2" * 64,
                "origin": "local_dossier",
            }
        ],
        "registry": {
            "kind": "not_found",
            "query": "trial",
            "retrieved_at": "2026-08-25T00:00:00+00:00",
        },
        "omissions": [],
    }
    trial = CapturedTrial.model_validate(trial).model_dump(mode="json")
    batch: dict[str, Any] = {"trials": [trial], "conditions": []}
    batch["identity"] = _identity(batch)
    assert _valid_batch(batch)
    assert standalone_valid_batch(batch)

    for mutate in (
        lambda value: value["trials"][0]["registry"].update({"retrieved_at": "invented"}),
        lambda value: value["trials"][0].update({"id": "invalid trial id"}),
        lambda value: value["trials"][0]["sources"][0].update({"role": "primary_publication"}),
    ):
        invalid = json.loads(json.dumps(batch))
        mutate(invalid)
        invalid["trials"][0]["identity"] = _identity(
            {key: value for key, value in invalid["trials"][0].items() if key != "identity"}
        )
        invalid["identity"] = _identity(
            {"trials": invalid["trials"], "conditions": invalid["conditions"]}
        )
        assert not _valid_batch(invalid)
        assert not standalone_valid_batch(invalid)


def test_rehashed_hidden_bundle_shapes_fail_both_verifiers(tmp_path: Path) -> None:
    artifact = _assessed_artifact(_workspace(tmp_path))

    def hidden_trial(canonical: dict[str, Any]) -> None:
        trial = canonical["batch"]["trials"][0]
        trial["hidden"] = "invented"
        trial["identity"] = _identity(
            {key: value for key, value in trial.items() if key != "identity"}
        )
        canonical["batch"]["identity"] = _identity(
            {
                "trials": canonical["batch"]["trials"],
                "conditions": canonical["batch"]["conditions"],
            }
        )

    def hidden_proposal_envelope(canonical: dict[str, Any]) -> None:
        canonical["proposal"]["hidden"] = "invented"

    def hidden_canonical_envelope(canonical: dict[str, Any]) -> None:
        canonical["hidden"] = "invented"

    for index, mutate in enumerate(
        (hidden_trial, hidden_proposal_envelope, hidden_canonical_envelope)
    ):
        tampered = tmp_path / f"hidden-shape-{index}.rob2.zip"
        _rehashed_domain_tamper(artifact, tampered, mutate)
        assert not verify_bundle(tampered)
        assert _standalone_verify(tampered).returncode == 1

    with zipfile.ZipFile(artifact) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    manifest = json.loads(files["manifest.json"])
    manifest["hidden"] = "invented"
    files["manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    tampered = tmp_path / "hidden-manifest-shape.rob2.zip"
    with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.writestr(name, files[name])
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1


def test_domain_answers_tampering_fails_both_bundle_verifiers(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    artifact = _assessed_artifact(workspace)

    def tamper(canonical: dict[str, Any]) -> None:
        key = "trial:domain:deviations"
        record = canonical["domain_records"][key]
        old_identity = record["identity"]
        next(
            item
            for item in record["answers"]
            if item["question_id"] == "sq:deviations:participants-aware"
        )["answer"] = "no"
        fields = (
            "trial_id",
            "domain_id",
            "answers",
            "search_accounts",
            "active_questions",
            "inactive_questions",
            "judgment",
            "trace",
        )
        record["identity"] = _identity({field: record[field] for field in fields})
        canonical["domain_history"][key][-1] = record["identity"]
        snapshot = canonical["snapshots"]["trial"]
        snapshot["checkpoints"] = [
            record["identity"] if value == old_identity else value
            for value in snapshot["checkpoints"]
        ]
        snapshot["identity"] = _identity(
            {field: value for field, value in snapshot.items() if field != "identity"}
        )
        canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]

    tampered = tmp_path / "domain-answer-tamper.rob2.zip"
    _rehashed_domain_tamper(artifact, tampered, tamper)
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1


def test_rehashed_trial_review_and_closure_tampering_fails_both_verifiers(
    tmp_path: Path,
) -> None:
    artifact = _assessed_artifact(_workspace(tmp_path))

    def reseal(record: dict[str, Any]) -> None:
        record["identity"] = _identity(
            {key: value for key, value in record.items() if key != "identity"}
        )

    def detach_review_result(canonical: dict[str, Any]) -> None:
        review = canonical["trial_reviews"]["trial"]
        review["result_identity"] = "sha256:" + "0" * 64
        reseal(review)

    def detach_closure(canonical: dict[str, Any]) -> None:
        closure = canonical["trial_closures"]["trial"]
        closure["review_identity"] = "sha256:" + "0" * 64
        reseal(closure)

    cases = (
        lambda canonical: canonical.pop("trial_reviews"),
        lambda canonical: canonical["trial_closures"].pop("trial"),
        detach_review_result,
        detach_closure,
    )
    for index, mutate in enumerate(cases):
        tampered = tmp_path / f"trial-review-closure-{index}.rob2.zip"
        _rehashed_full_tamper(artifact, tampered, mutate)
        assert not verify_bundle(tampered)
        assert _standalone_verify(tampered).returncode == 1


def test_historical_bundle_without_trial_closure_fields_stays_verifiable(
    tmp_path: Path,
) -> None:
    artifact = _assessed_artifact(_workspace(tmp_path))
    with zipfile.ZipFile(artifact) as archive:
        files = {item.filename: archive.read(item) for item in archive.infolist()}
    canonical = json.loads(files["canonical.json"])
    canonical.pop("trial_reviews")
    canonical.pop("trial_closures")
    files["canonical.json"] = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    dispositions = canonical["dispositions"]
    counts = {
        name: sum(value == name for value in dispositions.values())
        for name in ("assessed", "needs_input", "failed", "pending")
    }
    total = len(dispositions)
    wording = (
        "Batch finalized. No RoB 2 assessments were completed."
        if not counts["assessed"]
        else "Batch finalized. "
        f"RoB 2 assessments completed for {counts['assessed']}/{total} Trials. "
        f"{counts['needs_input']} Trials need input; {counts['failed']} Trials failed."
    )
    claims = json.loads(files["claims.json"])
    claims["counts"] = counts
    claims["authoritative_wording"] = wording
    files["claims.json"] = json.dumps(
        claims, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    files["report.html"] = (
        "<html><body><h1>Batch finalized</h1><pre>"
        + json.dumps(claims, sort_keys=True)
        + "</pre></body></html>"
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
    historical = tmp_path / "legacy-without-trial-closures.rob2.zip"
    with zipfile.ZipFile(historical, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])

    assert verify_bundle(historical)
    assert _standalone_verify(historical).returncode == 0


def test_bundle_path_policy_allows_escaped_text_and_rejects_platform_paths(
    tmp_path: Path,
) -> None:
    assert not _contains_forbidden_paths({"quote": "line\nbreak and a literal \\ mark"})
    workspace = _workspace(tmp_path)
    artifact = _assessed_artifact(workspace)
    with zipfile.ZipFile(artifact) as archive:
        original_manifest = archive.read("manifest.json")
        original_canonical = archive.read("canonical.json")

    for index, path_value in enumerate(
        ("C:\\private\\source.pdf", "\\\\server\\share\\source.pdf", "relative\\source.pdf")
    ):
        canonical = json.loads(original_canonical)
        canonical["batch"]["trials"][0]["sources"][0]["logical_path"] = path_value
        changed_canonical = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        changed_manifest = _update_manifest_hash(
            original_manifest, "canonical.json", changed_canonical
        )
        tampered = tmp_path / f"platform-path-{index}.zip"
        _rewrite_zip(
            artifact,
            tampered,
            {"canonical.json": changed_canonical, "manifest.json": changed_manifest},
        )
        assert not verify_bundle(tampered)
        assert _standalone_verify(tampered).returncode == 1

    canonical = json.loads(original_canonical)
    canonical["batch"]["trials"][0]["workspace_path"] = "workspace/report"
    changed_canonical = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    changed_manifest = _update_manifest_hash(original_manifest, "canonical.json", changed_canonical)
    tampered = tmp_path / "forbidden-path-field.zip"
    _rewrite_zip(
        artifact,
        tampered,
        {"canonical.json": changed_canonical, "manifest.json": changed_manifest},
    )
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1
