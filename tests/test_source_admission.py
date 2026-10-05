"""Native admission preserves a live assessment and authenticates inventory history."""

from __future__ import annotations

import json
import socket
from copy import deepcopy

import httpx
import pytest
from support import rob2 as support
from support.rob2 import _call, _finalize_assessment, _standalone_verify
from test_assessment_review_gate import _complete_assessment
from test_companion_sources import URL, pdf
from test_finalization_bundle_integrity import _rewrite_rehashed

from rob2_kit.application import companion_sources as companion
from rob2_kit.application._state import _state
from rob2_kit.application.evidence import _search_receipt, search_sources, source_reading_status
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.application.trials import _review_record_is_current


@pytest.fixture
def assessed(tmp_path, monkeypatch):
    original = support._workspace

    def with_reference(path, requested_outcome="requested outcome"):
        workspace = original(path, requested_outcome)
        report = workspace / "input" / "trial" / "main.txt"
        report.write_text(report.read_text() + "Companion protocol " + URL + "\n")
        return workspace

    monkeypatch.setattr(support, "_workspace", with_reference)
    return _complete_assessment(tmp_path)[0]


@pytest.fixture
def public_pdf(monkeypatch):
    original = httpx.Client
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=pdf("Plan content NCT00000001"))

    monkeypatch.setattr(
        companion.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    return calls


def acquire(workspace):
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    receipt = _call(
        workspace,
        "acquire_companion_source",
        {
            "reference": {
                "trial_id": "trial",
                "source_id": source["id"],
                "page": 1,
                "citation": "Companion protocol " + URL,
                "linkage_rationale": "Explicit cited companion; applicability unknown",
                "requested_role": "protocol",
                "locator_kind": "url",
                "locator": URL,
            },
            "expected_revision": _state(workspace)["revision"],
        },
    )
    assert receipt["outcome"] == "success", receipt
    assert receipt["data"]["document_staged"] is True
    assert receipt["data"]["admitted_to_active_batch"] is False
    assert receipt["data"]["document_read"] is False
    return receipt["data"]["candidate_identity"]


def admit(workspace, identity):
    receipt = _call(
        workspace,
        "admit_companion_source",
        {
            "trial_id": "trial",
            "candidate_identity": identity,
            "expected_revision": _state(workspace)["revision"],
        },
    )
    assert receipt["outcome"] == "success", receipt
    assert receipt["data"]["document_read"] is False
    return receipt


def test_native_admission_preserves_sources_science_and_reopens_review_currency(
    assessed, public_pdf
):
    workspace = assessed
    reviewed = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": _state(workspace)["revision"]},
    )
    assert reviewed["outcome"] == "success", reviewed
    from test_bounded_domain_context import _wire_context
    from test_working_checkpoint import _checkpoint

    from rob2_kit.application.working import working_checkpoint_status

    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    _call(workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(source["id"])})
    context, _ = _wire_context(
        workspace,
        {"trial_id": "trial", "domain_id": "domain:deviations", "max_response_bytes": 32_768},
        drain=False,
    )
    assert context["outcome"] == "success", context
    cursor = context["data"]["context_page"]["next_cursor"]
    assert cursor is not None
    before = deepcopy(_state(workspace))
    old_bytes = {p: p.read_bytes() for p in (workspace / ".rob2-kit" / "sources").rglob("*.bin")}
    search = search_sources(workspace, "trial", "outcome")
    identity = acquire(workspace)
    assert _state(workspace)["batch"] == before["batch"]
    receipt = admit(workspace, identity)
    state = _state(workspace)
    for key in (
        "proposal",
        "review",
        "domain_records",
        "domain_history_records",
        "snapshots",
        "snapshot_history_records",
        "trial_reviews",
    ):
        assert state.get(key) == before.get(key), key
    assert all(p.read_bytes() == content for p, content in old_bytes.items())
    assert state["batch_history"] == [before["batch"]]
    assert state["batch"]["trials"][0]["sources"][:-2] == before["batch"]["trials"][0]["sources"]
    assert not _review_record_is_current(state, state["trial_reviews"]["trial"])
    status = _call(workspace, "get_status", {})
    assert status["head"]["next_action"]["operation"] == "review_trial"
    assert working_checkpoint_status(workspace, state, "trial")["status"] in {"stale", "absent"}
    stale_context, _ = _wire_context(workspace, {"cursor": cursor}, drain=False)
    assert stale_context["outcome"] == "condition", stale_context
    assert "stale" in stale_context["condition"]["code"]
    _call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:randomization"}
    )
    with pytest.raises(ValueError, match="corrupt|stale"):
        _search_receipt(workspace, search["search_receipt"]["handle"])
    new_sources = receipt["data"]["source_ids"]
    assert all(source_id.startswith("sh_") for source_id in new_sources)
    assert len(public_pdf) == 1
    assert len(source_reading_status(workspace, "trial")) == 1  # original report delivery survives
    read = _call(
        workspace, "read_pages", {"trial_id": "trial", "source_id": new_sources[0], "pages": [1]}
    )
    assert read["outcome"] == "success", read
    assert "Plan content" in json.dumps(read["data"])
    rereview = _call(
        workspace, "review_trial", {"trial_id": "trial", "expected_revision": state["revision"]}
    )
    assert rereview["outcome"] == "success", rereview
    assert _review_record_is_current(_state(workspace), _state(workspace)["trial_reviews"]["trial"])


def test_admitted_history_exports_verify_and_rehashed_tampering_is_rejected(
    assessed, public_pdf, tmp_path
):
    workspace = assessed
    identity = acquire(workspace)
    admit(workspace, identity)
    artifact = _finalize_assessment(workspace, _state(workspace)["revision"])["data"]["artifact"]
    path = workspace / artifact["path"]
    assert verify_bundle(path)
    assert _standalone_verify(path).returncode == 0
    from rob2_kit.application.source_archive import archive_sources, verify_source_archive

    archive = archive_sources(workspace)
    assert verify_source_archive(workspace / archive["path"])
    for index, mutate in enumerate(
        [
            lambda c: c["batch_history"][0]["trials"][0]["sources"].clear(),
            lambda c: c["source_admissions"][0]["candidate"]["capture"].update(
                sha256="sha256:" + "0" * 64
            ),
            lambda c: c["trial_reviews"]["trial"].pop("trial_inventory_identity"),
            lambda c: c["source_admissions"].clear(),
            lambda c: (c.pop("source_admissions"), c.pop("batch_history")),
        ]
    ):
        target = tmp_path / f"tampered-{index}.zip"
        _rewrite_rehashed(path, target, mutate)
        assert not verify_bundle(target)
        assert _standalone_verify(target).returncode != 0


def test_stale_closed_wrong_trial_and_corrupt_candidate_do_not_admit(assessed, public_pdf):
    workspace = assessed
    identity = acquire(workspace)
    state = _state(workspace)
    candidate = workspace / ".rob2-kit" / "companion_candidates" / identity[7:] / "candidate.pdf"
    candidate.write_bytes(candidate.read_bytes() + b"tampered")
    failed = _call(
        workspace,
        "admit_companion_source",
        {
            "trial_id": "trial",
            "candidate_identity": identity,
            "expected_revision": state["revision"],
        },
    )
    assert failed["outcome"] == "condition", failed
    assert _state(workspace) == state
    wrong = _call(
        workspace,
        "admit_companion_source",
        {
            "trial_id": "other",
            "candidate_identity": identity,
            "expected_revision": state["revision"],
        },
    )
    assert wrong["outcome"] == "condition"
    stale = _call(
        workspace,
        "admit_companion_source",
        {
            "trial_id": "trial",
            "candidate_identity": identity,
            "expected_revision": state["revision"] - 1,
        },
    )
    assert stale["outcome"] == "conflict"
    _finalize_assessment(workspace, state["revision"])
    closed = _call(
        workspace,
        "admit_companion_source",
        {
            "trial_id": "trial",
            "candidate_identity": identity,
            "expected_revision": _state(workspace)["revision"],
        },
    )
    assert closed["outcome"] == "condition"
    assert len(public_pdf) == 1


def test_two_trial_admission_preserves_unaffected_review_search_context_and_working(
    tmp_path, public_pdf
):
    import shutil

    from support.rob2 import (
        _domain_draft,
        _prepared_evidence,
        _proposal_args,
        _read_required_main_reports,
        _result,
        _review,
        _workspace,
    )
    from test_working_checkpoint import _checkpoint

    from rob2_kit.application.domains import _domain_context_basis_identity
    from rob2_kit.application.working import working_checkpoint_status
    from rob2_kit.packs import SCIENTIFIC_PACK

    workspace = _workspace(tmp_path)
    report = workspace / "input" / "trial" / "main.txt"
    report.write_text(report.read_text() + "Companion protocol " + URL + "\n")
    shutil.copytree(workspace / "input" / "trial", workspace / "input" / "zother")
    first = _prepared_evidence(workspace)
    second_source = _call(workspace, "list_sources", {"trial_id": "zother"})["data"]["sources"][0]
    second = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "zother",
            "source_id": second_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    result2 = _result(second)
    result2["trial_id"] = "zother"
    proposed = _call(
        workspace, "save_proposal", _proposal_args(workspace, [_result(first), result2])
    )
    assert proposed["outcome"] == "review_required", proposed
    _review(workspace)
    _read_required_main_reports(workspace)
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, _state(workspace)["revision"], first),
        )
        assert saved["outcome"] == "success", saved
    reviewed = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": _state(workspace)["revision"]},
    )
    assert reviewed["outcome"] == "success", reviewed
    first_source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    saved = _call(
        workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(first_source["id"])}
    )
    assert saved["outcome"] == "success", saved
    before = deepcopy(_state(workspace))
    context_basis = _domain_context_basis_identity(
        before, "trial", "domain:randomization", None, workspace
    )
    context = _call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:randomization"}
    )
    assert context["outcome"] == "success", context
    search = search_sources(workspace, "trial", "outcome")["search_receipt"]
    acquired = _call(
        workspace,
        "acquire_companion_source",
        {
            "reference": {
                "trial_id": "zother",
                "source_id": second_source["id"],
                "page": 1,
                "citation": "Companion protocol " + URL,
                "linkage_rationale": "Cited companion; applicability unknown",
                "requested_role": "sap",
                "locator_kind": "url",
                "locator": URL,
            },
            "expected_revision": before["revision"],
        },
    )
    assert acquired["outcome"] == "success", acquired
    admitted = _call(
        workspace,
        "admit_companion_source",
        {
            "trial_id": "zother",
            "candidate_identity": acquired["data"]["candidate_identity"],
            "expected_revision": _state(workspace)["revision"],
        },
    )
    assert admitted["outcome"] == "success", admitted
    state = _state(workspace)
    assert state["batch"]["trials"][0] == before["batch"]["trials"][0]
    assert _review_record_is_current(state, state["trial_reviews"]["trial"])
    assert _search_receipt(workspace, search["handle"]) == search
    assert (
        _domain_context_basis_identity(state, "trial", "domain:randomization", None, workspace)
        == context_basis
    )
    assert working_checkpoint_status(workspace, state, "trial")["status"] == "current"
    # Closing the unaffected review still works against its preserved exact review identity.
    closed = _call(
        workspace,
        "close_trial",
        {
            "trial_id": "trial",
            "review_reference": state["trial_reviews"]["trial"]["identity"],
            "expected_revision": state["revision"],
        },
    )
    assert closed["outcome"] == "success", closed


def test_historical_search_accounts_keep_exact_old_inventory_basis(assessed, public_pdf):
    from support.rob2 import _domain_draft

    workspace = assessed
    domain_id = "domain:randomization"
    old_search = search_sources(
        workspace, "trial", "unmentionedliteral", purpose_domain_id=domain_id
    )["search_receipt"]
    original = _state(workspace)["domain_records"]["trial:" + domain_id]
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    evidence_handle = _call(
        workspace,
        "select_text_evidence",
        {"trial_id": "trial", "source_id": source["id"], "page": 1, "start_line": 1, "end_line": 1},
    )["data"]["evidence"]["handle"]

    def draft(receipt):
        value = _domain_draft(
            "trial", domain_id, _state(workspace)["revision"], {"handle": evidence_handle}
        )
        value["answers"][0]["absence_searches"] = [receipt["handle"]]
        value["supersedes"] = _state(workspace)["domain_records"]["trial:" + domain_id]["identity"]
        value["revision_basis"] = {
            "kind": "self_correction",
            "rationale": "Record exact lexical investigation basis; fixture only",
        }
        return value

    _call(workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain_id})
    revised = _call(workspace, "save_domain_judgment", draft(old_search))
    assert revised["outcome"] == "success", revised
    assert (
        _state(workspace)["domain_records"]["trial:" + domain_id]["identity"]
        != original["identity"]
    )
    identity = acquire(workspace)
    admit(workspace, identity)
    stale = _call(workspace, "save_domain_judgment", draft(old_search))
    assert stale["outcome"] in {"condition", "repair"}, stale
    current_search = search_sources(
        workspace, "trial", "unmentionedliteral", purpose_domain_id=domain_id
    )["search_receipt"]
    assert current_search["batch_identity"] != old_search["batch_identity"]
    _call(workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain_id})
    current = _call(workspace, "save_domain_judgment", draft(current_search))
    assert current["outcome"] == "success", current
    artifact = _finalize_assessment(workspace, _state(workspace)["revision"])["data"]["artifact"]
    path = workspace / artifact["path"]
    assert verify_bundle(path)
    assert _standalone_verify(path).returncode == 0


def test_acquisition_checks_revision_and_open_trial_before_public_access(assessed, public_pdf):
    workspace = assessed
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    request = {
        "reference": {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "citation": "Companion protocol " + URL,
            "linkage_rationale": "Cited companion",
            "requested_role": "sap",
            "locator_kind": "url",
            "locator": URL,
        },
        "expected_revision": _state(workspace)["revision"] - 1,
    }
    stale = _call(workspace, "acquire_companion_source", request)
    assert stale["outcome"] == "conflict", stale
    request["expected_revision"] = _state(workspace)["revision"]
    request["reference"]["trial_id"] = "other"
    wrong = _call(workspace, "acquire_companion_source", request)
    assert wrong["outcome"] == "condition", wrong
    _finalize_assessment(workspace, _state(workspace)["revision"])
    request["reference"]["trial_id"] = "trial"
    request["expected_revision"] = _state(workspace)["revision"]
    closed = _call(workspace, "acquire_companion_source", request)
    assert closed["outcome"] == "condition", closed
    assert public_pdf == []
