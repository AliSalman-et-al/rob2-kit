"""An upstream factual account is reusable without deriving signalling answers."""

import copy
import sqlite3
from pathlib import Path

import pymupdf
import pytest
from support import rob2 as support

from rob2_kit.application._state import _state
from rob2_kit.workflow_models import WorkingCheckpointDraft


@pytest.fixture
def account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict, dict, int]:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((48, 48), "Alpha: 20 randomized; 19 analyzed; 18 completed.")
        document.save(trial / "counts.pdf")
    original = support._workspace

    def create(path: Path, requested_outcome: str = "requested outcome") -> Path:
        result = original(path, requested_outcome)
        with (result / "input/trial/main.txt").open("a") as stream:
            stream.write(
                "Alpha: 20 randomized, 19 analyzed, 18 completed; urine availability unknown.\n"
            )
            stream.write(
                "Beta: 30 randomized, 29 analyzed; earlier phase used rescue medication.\n"
            )
        return result

    monkeypatch.setattr(support, "_workspace", create)
    workspace, evidence, revision = support._assessment_workspace(tmp_path)
    count_evidence = support._call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": evidence["source_id"],
            "page": 1,
            "start_line": 2,
            "end_line": 3,
        },
    )["data"]["evidence"]
    source = next(
        item
        for item in support._call(workspace, "list_sources", {"trial_id": "trial"})["data"][
            "sources"
        ]
        if item["label"] == "counts.pdf"
    )
    rendered = support._call(
        workspace, "render_page", {"trial_id": "trial", "source_id": source["id"], "page": 1}
    )["data"]
    visual = support._call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "delivery_receipt": rendered["delivery_receipt"],
            "region": [0.0, 0.0, 1.0, 1.0],
            "transcription": "Alpha: 20 randomized; 19 analyzed; 18 completed.",
            "uncertainty": "Endpoint availability is unspecified.",
        },
    )["data"]["evidence"]
    note = {
        "text": "Alpha has analysis and completion counts but unknown urine availability.",
        "sources": [
            {"source_id": evidence["source_id"], "page": 1, "start_line": 2, "end_line": 3}
        ],
    }
    steps = [
        {
            "id": "collection",
            "aspect": "outcome_ascertainment",
            "observation": note,
            "unknowns": ["Observed urine count remains unknown."],
            "counterevidence": [
                {**note, "text": "Analysis membership includes more than completers."}
            ],
            "counts": [
                {
                    "arm": "Alpha",
                    "population": "randomized",
                    "unit": "participants",
                    "time_point": "selected window",
                    "randomized": 20,
                    "analyzed": 19,
                    "completed": 18,
                    "basis": [visual["handle"]],
                }
            ],
        },
        {
            "id": "earlier-course",
            "aspect": "assignment_course",
            "observation": {
                **note,
                "text": "Beta used rescue medication in an earlier phase.",
                "scope": {"relation": "mismatch", "groups": ["Beta"], "window": "earlier phase"},
            },
            "inference": "Relevance to the selected window remains unresolved.",
        },
        {
            "id": "model",
            "aspect": "analysis",
            "observation": note,
            "unknowns": ["Analysis assumptions need targeted reading."],
        },
        {
            "id": "intentions",
            "aspect": "plan_report",
            "observation": note,
            "unknowns": ["Plan chronology remains unknown."],
        },
    ]
    draft = {"trial_id": "trial", "result_account": steps}
    saved = support._call(workspace, "save_working_checkpoint", {"checkpoint": draft})
    assert saved["outcome"] == "success", saved
    return workspace, evidence, count_evidence, revision


def _context(workspace: Path, domain: str) -> dict:
    result = support._call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain}
    )
    assert result["outcome"] == "success", result
    return result["data"]


def test_account_counts_exist_before_judgment_and_scope_and_unknowns_survive_domains(
    account: tuple,
) -> None:
    workspace, _, count_evidence, _ = account
    assert _state(workspace).get("domain_records", {}) == {}
    for domain in ("domain:deviations", "domain:missing", "domain:selection"):
        context = _context(workspace, domain)
        steps = context["working_checkpoint"]["checkpoint"]["result_account"]
        assert steps[0]["counts"][0]["completed"] == 18
        assert steps[0]["counts"][0].get("observed") is None
        assert steps[0]["unknowns"] == ["Observed urine count remains unknown."]
        assert steps[0]["counterevidence"][0]["sources"] == steps[0]["observation"]["sources"]
        assert steps[1]["observation"]["scope"]["groups"] == ["Beta"]
        assert any(
            item["handle"] == steps[0]["counts"][0]["basis"][0] for item in context["evidence"]
        )
        if domain != "domain:selection":
            projections = [
                card["participant_flow"]
                for card in context["comparison_cards"]
                if card["participant_flow"]
            ]
            assert projections
            assert "18" in str(projections) and "Alpha" in str(projections)
    assert _state(workspace).get("domain_records", {}) == {}


@pytest.mark.parametrize("scope_role", ["context", "contradiction", "inference"])
def test_step_snapshot_transfer_and_changed_dependency_do_not_rewrite_answers(
    account: tuple,
    scope_role: str,
) -> None:
    workspace, main, count_evidence, revision = account
    context = _context(workspace, "domain:deviations")
    steps = context["working_checkpoint"]["checkpoint"]["result_account"]
    draft = support._domain_draft("trial", "domain:deviations", revision, main)
    first = draft["answers"][0]
    first["bases"].append(
        {
            "kind": "context",
            "evidence": count_evidence["handle"],
            "working_observation": {"step_identity": steps[1]["identity"]},
        }
    )
    response = support._call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair", response
    assert any(item["code"] == "result_step_transfer" for item in response["repairs"])
    first["bases"][-1]["kind"] = scope_role
    first["bases"][-1]["working_observation"]["transfer"] = (
        "Earlier-phase rescue is contextual, not evidence of selected-window deviations."
    )
    if scope_role == "contradiction":
        first["counterevidence"] = [
            {
                "basis_index": 1,
                "implication": "Earlier rescue does not establish selected-window deviations.",
            }
        ]
    response = support._call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "success", response
    record = copy.deepcopy(_state(workspace)["domain_records"]["trial:domain:deviations"])
    snapshot = record["answers"][0]["bases"][-1]["working_observation"]
    assert snapshot["result_step"]["identity"] == steps[1]["identity"]
    assert snapshot["observation"]["scope"]["relation"] == "mismatch"
    assert snapshot["transfer"].startswith("Earlier-phase")
    revised = copy.deepcopy(steps)
    revised[2]["unknowns"] = ["An unrelated analysis clarification."]
    revised[2].pop("identity")
    saved = support._call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": {"trial_id": "trial", "result_account": revised}},
    )
    assert saved["outcome"] == "success", saved
    assert (
        support._call(workspace, "get_status", {})["data"]["working_checkpoint"]["reconsideration"]
        == []
    )
    revised[1]["unknowns"] = ["Additional uncertainty about the relied-on phase."]
    revised[1].pop("identity")
    saved = support._call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": {"trial_id": "trial", "result_account": revised}},
    )
    assert saved["outcome"] == "success", saved
    affected = support._call(workspace, "get_status", {})["data"]["working_checkpoint"][
        "reconsideration"
    ]
    assert [(item["domain_id"], item["question_id"], item["step_id"]) for item in affected] == [
        ("domain:deviations", first["question_id"], "earlier-course")
    ]
    assert _state(workspace)["domain_records"]["trial:domain:deviations"] == record
    stale = support._domain_draft(
        "trial", "domain:missing", int(response["head"]["state_revision"]), main
    )
    stale["answers"][0]["bases"].append(
        {
            "kind": "inference",
            "evidence": count_evidence["handle"],
            "working_observation": {
                "step_identity": steps[1]["identity"],
                "transfer": "Same qualified inference.",
            },
        }
    )
    rejected = support._call(workspace, "save_domain_judgment", stale)
    assert any(item["code"] == "result_step_stale" for item in rejected["repairs"])
    # The new warrant snapshot must remain independently exportable.
    from rob2_kit.application.finalization import verify_bundle
    from rob2_kit.packs import SCIENTIFIC_PACK

    revision = int(response["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        if domain.id == "domain:deviations":
            continue
        support._call(
            workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain.id}
        )
        next_draft = support._domain_draft("trial", domain.id, revision, main)
        if domain.id in {"domain:missing", "domain:selection"}:
            current = _context(workspace, domain.id)["working_checkpoint"]["checkpoint"][
                "result_account"
            ]
            next_draft["answers"][0]["bases"].append(
                {
                    "kind": "context",
                    "evidence": count_evidence["handle"],
                    "working_observation": {"step_identity": current[0]["identity"]},
                }
            )
        saved = support._call(workspace, "save_domain_judgment", next_draft)
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    for domain in ("domain:missing", "domain:selection"):
        row = _state(workspace)["domain_records"][f"trial:{domain}"]["answers"][0]
        shared = row["bases"][-1]["working_observation"]["result_step"]
        assert shared["id"] == "collection"
        assert shared["counts"][0]["completed"] == 18
        assert shared["counts"][0].get("observed") is None
        assert shared["counterevidence"][0]["sources"] == shared["observation"]["sources"]
    nested = _state(workspace)["domain_records"]["trial:domain:missing"]["answers"][0]["bases"][-1][
        "working_observation"
    ]
    handle = nested["result_step"]["counts"][0]["basis"][0]
    identity = nested["count_evidence"][handle]
    assert identity != count_evidence["identity"]
    with sqlite3.connect(workspace / ".rob2-kit/canonical.sqlite3") as db:
        assert db.execute(
            "SELECT 1 FROM canonical_records WHERE identity=? AND kind='evidence'", (identity,)
        ).fetchone()
    # Disposable visual render/evidence caches may be lost after canonical commit.
    with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as db:
        db.execute("DELETE FROM renders")
        db.execute("DELETE FROM evidence_handles")
        db.execute("DELETE FROM visual_deliveries")
    recovered = _context(workspace, "domain:missing")
    assert any(item["handle"] == handle for item in recovered["evidence"])
    finalized = support._finalize_assessment(workspace, revision)
    artifact = workspace / finalized["data"]["artifact"]["path"]
    assert verify_bundle(artifact)
    standalone = support._standalone_verify(artifact)
    assert standalone.returncode == 0, standalone.stdout + standalone.stderr


def test_account_replaces_parallel_notes_and_count_sources_must_be_explicit(
    account: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, main, count_evidence, revision = account
    steps = _context(workspace, "domain:missing")["working_checkpoint"]["checkpoint"][
        "result_account"
    ]
    with pytest.raises(ValueError, match="replaces"):
        WorkingCheckpointDraft.model_validate(
            {
                "trial_id": "trial",
                "result_account": steps,
                "observations": [steps[0]["observation"]],
            }
        )
    context = _context(workspace, "domain:selection")
    fake = copy.deepcopy(steps[1])
    fake["unknowns"] = ["Invented snapshot not in the saved account."]
    fake.pop("identity")
    draft = support._domain_draft("trial", "domain:selection", revision, main)
    draft["answers"][0]["bases"].append(
        {
            "kind": "inference",
            "evidence": count_evidence["handle"],
            "working_observation": {
                "checkpoint_identity": context["working_checkpoint"]["checkpoint_identity"],
                "observation": fake["observation"],
                "result_step": fake,
                "transfer": "Qualified contextual inference.",
            },
        }
    )
    rejected = support._call(workspace, "save_domain_judgment", draft)
    assert any(item["code"] == "result_step_snapshot_invalid" for item in rejected["repairs"])
    steps[0]["counts"][0]["basis"] = []
    steps[0].pop("identity")
    rejected = support._call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": {"trial_id": "trial", "result_account": steps}},
    )
    assert rejected["outcome"] != "success"
    import rob2_kit.application.working as working

    monkeypatch.setattr(working, "_result_identity", lambda state, trial: "sha256:" + "0" * 64)
    status = support._call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["reason"] == "result_changed" and status["checkpoint"] is None


@pytest.mark.parametrize("module", ["rob2_kit.application.finalization", "verify_bundle"])
def test_nested_count_closure_rejects_missing_tampered_and_other_trial(module: str) -> None:
    import importlib

    validate = importlib.import_module(module)._valid_count_evidence_closure
    link = {
        "result_step": {"counts": [{"basis": ["eh_abc"]}]},
        "count_evidence": {"eh_abc": "sha256:original"},
    }
    evidence = {"sha256:original": {"handle": "eh_abc", "trial_id": "trial"}}
    assert validate(link, evidence, "trial")
    assert not validate(link, {}, "trial")
    assert not validate(link, evidence, "other")
    assert not validate({**link, "count_evidence": {"eh_abc": "sha256:changed"}}, evidence, "trial")
    assert not validate({"result_step": link["result_step"]}, evidence, "trial")
    assert not validate(
        link, {"sha256:original": {"handle": "eh_different", "trial_id": "trial"}}, "trial"
    )
