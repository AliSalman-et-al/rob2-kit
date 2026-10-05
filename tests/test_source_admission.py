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

    def remove_source_history(canonical: dict[str, object]) -> None:
        canonical.pop("source_admissions")
        canonical.pop("batch_history")

    for index, mutate in enumerate(
        [
            lambda c: c["batch_history"][0]["trials"][0]["sources"].clear(),
            lambda c: c["source_admissions"][0]["candidate"]["capture"].update(
                sha256="sha256:" + "0" * 64
            ),
            lambda c: c["trial_reviews"]["trial"].pop("trial_inventory_identity"),
            lambda c: c["source_admissions"].clear(),
            remove_source_history,
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


def test_restart_recovers_admission_derivatives_after_postcommit_failure(
    assessed, public_pdf, monkeypatch
):
    from rob2_kit.application.evidence import read_pages, render_page
    from rob2_kit.application.source_handles import source_handle

    workspace = assessed
    identity = acquire(workspace)
    before = deepcopy(_state(workspace))
    original_db = companion._db

    def fail_derivative(root, name):
        if name == "derivative.sqlite3":
            raise OSError("injected postcommit derivative failure")
        return original_db(root, name)

    with monkeypatch.context() as patch:
        patch.setattr(companion, "_db", fail_derivative)
        with pytest.raises(OSError, match="injected postcommit"):
            companion.admit_companion_source(workspace, "trial", identity, before["revision"])
    committed = deepcopy(_state(workspace))
    assert committed["revision"] == before["revision"] + 1
    assert len(committed["source_admissions"]) == 1
    old = committed["batch"]["trials"][0]["sources"][0]
    new = committed["batch"]["trials"][0]["sources"][-2]
    for source in (old, new):
        assert read_pages(workspace, "trial", source["id"], [1])["pages"]
        assert search_sources(
            workspace, "trial", "outcome" if source is old else "Plan", source_id=source["id"]
        )["hits"]
    assert render_page(workspace, "trial", new["id"], 1)["outcome"] == "success"
    # Restart public route also sees exact readable handles without replaying admission.
    assert (
        _call(
            workspace,
            "read_pages",
            {"trial_id": "trial", "source_id": source_handle(new["id"]), "pages": [1]},
        )["outcome"]
        == "success"
    )
    assert _state(workspace) == committed
    with pytest.raises(ValueError, match="already admitted"):
        companion.admit_companion_source(workspace, "trial", identity, committed["revision"])
    assert _state(workspace) == committed


def test_precommit_failure_preserves_canonical_assessment(assessed, public_pdf, monkeypatch):
    workspace = assessed
    identity = acquire(workspace)
    before = deepcopy(_state(workspace))

    def fail_commit(*args, **kwargs):
        raise OSError("injected precommit failure")

    with monkeypatch.context() as patch:
        patch.setattr(companion, "_commit_records", fail_commit)
        with pytest.raises(OSError, match="injected precommit"):
            companion.admit_companion_source(workspace, "trial", identity, before["revision"])
    assert _state(workspace) == before
    old = before["batch"]["trials"][0]["sources"][0]
    from rob2_kit.application.evidence import read_pages

    assert read_pages(workspace, "trial", old["id"], [1])["pages"]


def test_rehashed_semantic_lineage_tamper_and_malformed_legacy_are_invalid(
    assessed, public_pdf, tmp_path
):
    from rob2_kit.application._state import _identity
    from rob2_kit.application.finalization import _valid_batch

    workspace = assessed
    identity = acquire(workspace)
    admit(workspace, identity)
    artifact = _finalize_assessment(workspace, _state(workspace)["revision"])["data"]["artifact"]
    path = workspace / artifact["path"]

    def forge_predecessor(canonical):
        previous = canonical["batch_history"][0]
        trial = previous["trials"][0]
        trial["requested_outcome"] = "A different historical assessment target"
        trial["identity"] = _identity({k: v for k, v in trial.items() if k != "identity"})
        previous["identity"] = _identity({k: v for k, v in previous.items() if k != "identity"})
        admission = canonical["source_admissions"][0]
        admission["previous_batch_identity"] = previous["identity"]
        admission["identity"] = _identity({k: v for k, v in admission.items() if k != "identity"})
        assert _valid_batch(previous)  # All ordinary nested identities are now consistent.

    target = tmp_path / "semantic-lineage-tamper.zip"
    _rewrite_rehashed(path, target, forge_predecessor)
    assert not verify_bundle(target)
    assert _standalone_verify(target).returncode != 0
    for index, malformed in enumerate(
        [
            lambda c: c["batch"].update(trials=[None]),
            lambda c: c["batch"]["trials"][0].update(sources=[None]),
        ]
    ):

        def mutate(canonical):
            canonical.pop("batch_history")
            canonical.pop("source_admissions")
            malformed(canonical)

        target = tmp_path / f"malformed-legacy-{index}.zip"
        _rewrite_rehashed(path, target, mutate)
        assert not verify_bundle(target)
        assert _standalone_verify(target).returncode != 0


def test_lost_receipt_status_recovers_without_refetch_or_read_claim(assessed, public_pdf):
    workspace = assessed
    identity = acquire(workspace)
    staged = _call(workspace, "get_status", {})["data"]["companion_sources"][0]
    assert staged["candidate_identity"] == identity and not staged["admitted_to_active_batch"]
    revision = _state(workspace)["revision"]
    assert acquire(workspace) == identity  # Same exact reference at fresh revision, no new network.
    assert len(public_pdf) == 1 and _state(workspace)["revision"] == revision
    action = staged["next_action"]
    assert action["operation"] == "admit_companion_source"
    _call(workspace, action["operation"], {k: v for k, v in action.items() if k != "operation"})
    admitted = _call(workspace, "get_status", {})["data"]["companion_sources"][0]
    assert admitted["admitted_to_active_batch"] and admitted["reading_status"] == "unread"
    action = admitted["next_action"]
    assert action["operation"] == "read_pages"
    _call(workspace, action["operation"], {k: v for k, v in action.items() if k != "operation"})
    assert (
        _call(workspace, "get_status", {})["data"]["companion_sources"][0]["reading_status"]
        == "read_complete"
    )


def test_concurrent_acquisition_does_not_duplicate_public_fetch(assessed, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from rob2_kit.application.contracts import WorkflowConflict

    workspace = assessed
    source = _state(workspace)["batch"]["trials"][0]["sources"][0]
    reference = companion.CompanionReference(
        trial_id="trial",
        source_id=source["id"],
        page=1,
        citation="Companion protocol " + URL,
        linkage_rationale="Fixture reference",
        requested_role="sap",
        locator_kind="url",
        locator=URL,
    )
    started, release = threading.Event(), threading.Event()
    calls = []

    def fetch(ref):
        calls.append(ref)
        started.set()
        assert release.wait(5)
        data = pdf("Plan content")
        return data, {
            "reference": ref.model_dump(),
            "status": "captured",
            "source_role": "other",
            "sha256": "sha256:" + __import__("hashlib").sha256(data).hexdigest(),
            "page_count": 1,
        }

    monkeypatch.setattr(companion, "_acquire", fetch)
    revision = _state(workspace)["revision"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(companion.acquire_companion_source, workspace, reference, revision)
        assert started.wait(5)
        try:
            with pytest.raises(ValueError, match="in progress"):
                companion.acquire_companion_source(workspace, reference, revision)
        finally:
            release.set()
        receipt = future.result(timeout=5)
    assert len(calls) == 1
    with pytest.raises(WorkflowConflict):
        companion.acquire_companion_source(workspace, reference, revision)
    recovered = companion.acquire_companion_source(
        workspace, reference, _state(workspace)["revision"]
    )
    assert recovered["candidate_identity"] == receipt["candidate_identity"] and len(calls) == 1
