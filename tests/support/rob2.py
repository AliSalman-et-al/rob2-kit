"""Shared black-box workflow helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from fastmcp import Client

from rob2_kit.application._state import _identity
from rob2_kit.application.evidence import _search_receipt
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.logic.evaluator import active_questions
from rob2_kit.packs import SCIENTIFIC_PACK

standalone_valid_selected_evidence = runpy.run_path("scripts/verify_bundle.py")[
    "_valid_selected_evidence"
]
standalone_valid_batch = runpy.run_path("scripts/verify_bundle.py")["_valid_batch"]
standalone_normalized_contains = runpy.run_path("scripts/verify_bundle.py")["_normalized_contains"]


def _call(workspace: Path, tool: str, arguments: dict[str, object]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments)
            value = dict(result.structured_content or {})
            value["_image_content"] = [
                item for item in result.content if getattr(item, "type", None) == "image"
            ]
            return value

    return asyncio.run(invoke())


def _review(workspace: Path) -> None:
    environment = os.environ | {"ROB2_WORKSPACE": str(workspace)}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "rob2_kit.interfaces.cli.app",
            "review",
            "--workspace",
            str(workspace),
        ],
        input="yes\n",
        text=True,
        env=environment,
        check=True,
        capture_output=True,
    )


def _workspace(tmp_path: Path) -> Path:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True, exist_ok=True)
    (trial / "main.txt").write_text(
        "The requested outcome was not reported; "
        "only an alternate endpoint was measured. "
        "death ascertainment; end of follow-up; "
        "assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was "
        "measured in the analyzed population.; risk; 1; events; 2.\n",
        encoding="utf-8",
    )
    return tmp_path


def _result(_evidence: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "assessable",
        "trial_id": "trial",
        "relation": "exact",
        "target": {
            "measurement": {"method": "death ascertainment"},
            "time_point_or_window": {
                "kind": "described",
                "description": "end of follow-up",
            },
            "comparison_groups": [
                {"id": "a", "assignment": "assigned to intervention"},
                {"id": "b", "assignment": "assigned to control"},
            ],
            "intended_analysis_population": "randomized population",
            "intended_effect_measure": "risk ratio",
        },
        "reported": {
            "form": "group_bound_values",
            "endpoint": {
                "name": "requested outcome",
                "definition": "The requested outcome was measured in the analyzed population.",
            },
            "values": [
                {"group_id": "a", "statistic": "risk", "value": "1", "unit": "events"},
                {"group_id": "b", "statistic": "risk", "value": "2", "unit": "events"},
            ],
        },
    }

    return result


def _result_for_trial(evidence: dict[str, Any], trial_id: str) -> dict[str, Any]:
    result = _result(evidence)
    result["trial_id"] = trial_id
    return result


def _answers(domain_id: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for question in (item for item in SCIENTIFIC_PACK.questions if item.domain_id == domain_id):
        if question.id in active_questions(values):
            values[question.id] = (
                "no_information"
                if any(answer.value == "no_information" for answer in question.allowed_answers)
                else "no"
            )
    return values


def _domain_draft(
    trial_id: str,
    domain_id: str,
    revision: int,
    evidence: dict[str, Any] | None = None,
    search_receipt: str | None = None,
) -> dict[str, Any]:
    bases = (
        [
            {
                "kind": "direct_support",
                "evidence": evidence["handle"],
            }
        ]
        if evidence is not None
        else [
            {
                "kind": "limitation",
                "text": "Not reported.",
                **({"search_receipt": search_receipt} if search_receipt is not None else {}),
            }
        ]
    )
    return {
        "trial_id": trial_id,
        "domain_id": domain_id,
        "expected_revision": revision,
        "answers": [
            {"question_id": question_id, "answer": answer, "bases": list(bases)}
            for question_id, answer in _answers(domain_id).items()
        ],
    }


def _prepared_evidence(workspace: Path) -> dict[str, Any]:
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "main.txt"
    )
    return _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]


def _assessment_workspace(tmp_path: Path) -> tuple[Path, dict[str, Any], int]:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    return workspace, evidence, revision


def _finalize_assessment(workspace: Path, expected_revision: int) -> dict[str, Any]:
    """Automatically freeze the completed assessment and create its artifact."""
    finalized = _call(workspace, "finalize_batch", {"expected_revision": expected_revision})
    assert finalized["outcome"] == "success"
    return finalized


def _proposal_args(workspace: Path, results: list[dict[str, Any]]) -> dict[str, object]:
    """Build the exact public save_proposal request from current status."""
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    return {"results": results, "expected_revision": revision}


def _unavailable_result(evidence: dict[str, Any], fact: str) -> dict[str, Any]:
    return {
        "kind": "unavailable",
        "trial_id": "trial",
        "relation": "ambiguous",
        "missing_facts": [
            {
                "fact": fact,
                "basis": {
                    "kind": "missing_reporting",
                    "evidence": evidence["handle"],
                },
            }
        ],
    }


def _assessed_artifact(workspace: Path) -> Path:
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required"
    _review(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    return workspace / str(finalized["data"]["artifact"]["path"])


def _assessed_artifact_with_domain_evidence(workspace: Path) -> Path:
    return _assessed_artifact(workspace)


def _absence_assessed_artifact(workspace: Path) -> Path:
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required"
    _review(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        receipt = _search_receipt(
            workspace,
            _call(
                workspace,
                "search_sources",
                {"trial_id": "trial", "query": f"no-hit-{domain.id}"},
            )["data"]["search_receipt"],
        )
        draft = _domain_draft("trial", domain.id, revision, evidence)
        for answer in draft["answers"]:
            if answer["answer"] == "no_information":
                answer["bases"] = [{"kind": "absence", "search_receipt": receipt["handle"]}]
            else:
                answer["bases"] = [
                    {
                        "kind": "direct_support",
                        "evidence": evidence["handle"],
                    }
                ]
        saved = _call(workspace, "save_domain_judgment", draft)
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0
    return artifact


def _rehashed_domain_tamper(source: Path, target: Path, mutate: Any) -> None:
    with zipfile.ZipFile(source) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    canonical = json.loads(files["canonical.json"])
    mutate(canonical)
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
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])


def _rewrite_zip(source: Path, target: Path, replacements: dict[str, bytes]) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as archive:
        for info in original.infolist():
            payload = replacements.get(info.filename, original.read(info))
            archive.writestr(info, payload)


def _standalone_verify(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )


def _update_manifest_hash(manifest_bytes: bytes, member: str, payload: bytes) -> bytes:
    manifest = json.loads(manifest_bytes)
    for row in manifest["files"]:
        if row["path"] == member:
            row["sha256"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _rehashed_result_tamper(source: Path, target: Path, mutate: Any) -> None:
    """Rewrite every relevant archive hash after a scientific-payload mutation."""
    with zipfile.ZipFile(source) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    canonical = json.loads(files["canonical.json"])
    mutate(canonical["proposal"]["payload"]["results"][0])
    canonical["proposal"]["identity"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                canonical["proposal"]["payload"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    files["canonical.json"] = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    manifest = json.loads(files["manifest.json"])
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


def _rehashed_full_tamper(source: Path, target: Path, mutate: Any) -> None:
    """Rewrite canonical, proposal, manifest, and verification identities together."""
    with zipfile.ZipFile(source) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    canonical = json.loads(files["canonical.json"])
    mutate(canonical)
    proposal = canonical.get("proposal")
    if isinstance(proposal, dict) and isinstance(proposal.get("payload"), dict):
        proposal["identity"] = _identity(proposal["payload"])
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
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])


__all__ = [
    name
    for name in globals()
    if (name.startswith("_") and not name.startswith("__")) or name.startswith("standalone_")
]
