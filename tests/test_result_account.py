"""An upstream factual account is reusable without deriving signalling answers."""

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from support import rob2 as support

from rob2_kit.application._state import _state
from rob2_kit.application.source_handles import source_handle
from rob2_kit.workflow_models import WorkingCheckpointDraft, WorkingObservationLink


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


@pytest.mark.parametrize(
    ("passage", "observed", "inference", "unknowns"),
    [
        (
            "Alpha: 20 randomized; 18 analyzed. Two incomplete records were excluded; "
            "which outcome measurements were unavailable is not stated.",
            None,
            None,
            ["Selected-outcome availability for the two excluded records is unknown."],
        ),
        (
            "Alpha: 20 randomized; all 20 endpoint values were recorded; 18 analyzed. "
            "Two measured endpoints were omitted because a separate covariate was missing.",
            20,
            None,
            [],
        ),
        (
            "Alpha: 20 randomized; 18 endpoint values were recorded; 18 analyzed. "
            "The two unavailable measurements followed a documented equipment failure.",
            18,
            None,
            [],
        ),
        (
            "Alpha: 20 randomized; 18 analyzed. Monitoring stopped before the endpoint "
            "window in two participants; endpoint recovery is not described.",
            None,
            "The interruption probably prevented endpoint recording for those participants.",
            ["Recovery of endpoint values after the interruption is unknown."],
        ),
    ],
    ids=["unknown", "observed-but-omitted", "unavailable", "qualified-inference"],
)
def test_review_preserves_shared_warrant_snapshot_without_adjudicating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    passage: str,
    observed: int | None,
    inference: str | None,
    unknowns: list[str],
) -> None:
    original = support._workspace

    def create(path: Path, requested_outcome: str = "requested outcome") -> Path:
        workspace = original(path, requested_outcome)
        with (workspace / "input/trial/main.txt").open("a") as stream:
            stream.write(passage + "\n")
        return workspace

    monkeypatch.setattr(support, "_workspace", create)
    workspace, main, revision = support._assessment_workspace(tmp_path)
    evidence = support._call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": main["source_id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]
    note = {
        "text": passage,
        "sources": [{"source_id": main["source_id"], "page": 1, "start_line": 2, "end_line": 2}],
        "scope": {"meaning": "reported", "relation": "unknown"},
    }
    saved = support._call(
        workspace,
        "save_working_checkpoint",
        {
            "checkpoint": {
                "trial_id": "trial",
                "result_account": [
                    {
                        "id": "ascertainment",
                        "aspect": "outcome_ascertainment",
                        "observation": note,
                        "inference": inference,
                        "unknowns": unknowns,
                        "counterevidence": [note],
                        "counts": [
                            {
                                "arm": "Alpha",
                                "population": "randomized",
                                "unit": "participants",
                                "time_point": "selected window",
                                "randomized": 20,
                                "analyzed": 18,
                                "observed": observed,
                                "basis": [evidence["handle"]],
                            }
                        ],
                    }
                ],
            }
        },
    )
    assert saved["outcome"] == "success", saved
    questions = {}
    for domain in support.SCIENTIFIC_PACK.domains:
        context = _context(workspace, domain.id)
        draft = support._domain_draft("trial", domain.id, revision, main)
        question_id = {
            "domain:deviations": "sq:deviations:appropriate-analysis",
            "domain:missing": "sq:missing:data-available",
        }.get(domain.id, draft["answers"][0]["question_id"])
        selected_answer = next(
            answer for answer in draft["answers"] if answer["question_id"] == question_id
        )
        if domain.id in {"domain:deviations", "domain:missing"}:
            step = context["working_checkpoint"]["checkpoint"]["result_account"][0]
            selected_answer["bases"].append(
                {
                    "kind": "inference" if inference else "context",
                    "evidence": evidence["handle"],
                    "working_observation": {"step_identity": step["identity"]},
                }
            )
        questions[domain.id] = question_id
        committed = support._call(workspace, "save_domain_judgment", draft)
        assert committed["outcome"] == "success", committed
        revision = int(committed["head"]["state_revision"])
    records = copy.deepcopy(_state(workspace)["domain_records"])
    if inference is not None:
        relied_on_answer = next(
            answer
            for answer in records["trial:domain:deviations"]["answers"]
            if answer["question_id"] == questions["domain:deviations"]
        )
        revised = copy.deepcopy(relied_on_answer["bases"][-1]["working_observation"]["result_step"])
        revised.pop("identity")
        revised["inference"] = (
            "Later account revision: the original inference needs reconsideration."
        )
        updated = support._call(
            workspace,
            "save_working_checkpoint",
            {"checkpoint": {"trial_id": "trial", "result_account": [revised]}},
        )
        assert updated["outcome"] == "success", updated
    for domain in ("domain:deviations", "domain:missing", "domain:measurement"):
        reviewed = support._call(
            workspace,
            "review_trial",
            {
                "trial_id": "trial",
                "expected_revision": revision,
                "domain_id": domain,
                "question_id": questions[domain],
            },
        )
        assert reviewed["outcome"] == "success", reviewed
        revision = int(reviewed["head"]["state_revision"])
        finding = reviewed["data"]["domain_findings"][0]["answers"][0]
        assert (
            reviewed["data"]["domain_findings"][0]["decision"]
            == records[f"trial:{domain}"]["decision"]
        )
        original_answer = next(
            answer
            for answer in records[f"trial:{domain}"]["answers"]
            if answer["question_id"] == questions[domain]
        )
        assert finding["answer"] == original_answer["answer"]
        if domain == "domain:measurement":
            assert all("working_observation" not in basis for basis in finding["bases"])
        else:
            link = original_answer["bases"][-1]["working_observation"]
            # The typed receipt may emit nullable defaults; retained content and
            # snapshot identities must still match the unchanged canonical basis.
            assert (
                WorkingObservationLink.model_validate(
                    finding["bases"][-1]["working_observation"]
                ).model_dump(mode="json", exclude_none=True)
                == link
            )
            assert finding["bases"][-1]["assertion"] == "host_asserted"
            assert link["result_step"]["unknowns"] == unknowns
            assert link["result_step"].get("inference") == inference
            assert link["result_step"]["counts"][0].get("observed") == observed
            assert link["result_step"]["observation"]["scope"]["meaning"] == "reported"
        assert _state(workspace)["domain_records"] == records


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


@pytest.mark.parametrize(
    ("scope_role", "shortcut"),
    [("context", False), ("contradiction", False), ("inference", False), ("context", True)],
)
def test_step_snapshot_transfer_and_changed_dependency_do_not_rewrite_answers(
    account: tuple,
    scope_role: str,
    shortcut: bool,
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
                {"role": "context", "step_identity": current[0]["identity"]}
                if shortcut
                else {
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
    draft = support._domain_draft("trial", "domain:deviations", revision, main)
    draft["answers"][0]["bases"] = [
        {"step_identity": steps[1]["identity"], "role": "inference", "transfer": "Context."}
    ]
    before = copy.deepcopy(_state(workspace))
    rejected = support._call(workspace, "save_domain_judgment", draft)
    assert rejected["outcome"] == "condition", rejected
    assert _state(workspace) == before


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


@pytest.mark.parametrize("change", ["missing", "tampered"])
def test_nested_visual_count_source_must_validate_before_promotion(
    account: tuple, change: str
) -> None:
    workspace, main, evidence_a, revision = account
    steps = _context(workspace, "domain:missing")["working_checkpoint"]["checkpoint"][
        "result_account"
    ]
    source = next(
        s
        for s in _state(workspace)["batch"]["trials"][0]["sources"]
        if s["logical_path"] == "counts.pdf"
    )
    captured = workspace / ".rob2-kit/sources/trial" / (source["id"] + ".bin")
    if change == "missing":
        captured.unlink()
    else:
        captured.write_bytes(b"tampered source")
    draft = support._domain_draft("trial", "domain:missing", revision, main)
    draft["answers"][0]["bases"].append(
        {
            "kind": "context",
            "evidence": evidence_a["handle"],
            "working_observation": {"step_identity": steps[0]["identity"]},
        }
    )
    saved = support._call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] != "success", saved
    assert _state(workspace)["revision"] == revision
    assert not _state(workspace).get("domain_records")


def test_account_selected_handle_preserves_exact_unknowns_without_copying_locators(account: tuple):
    workspace, _, selected, _ = account
    prior = _state(workspace)
    draft: dict[str, Any] = {
        "trial_id": "trial",
        "result_account": [
            {
                "id": "observation",
                "aspect": "outcome_ascertainment",
                "observation": {
                    "text": "Availability is unresolved.",
                    "sources": [selected["handle"]],
                },
                "unknowns": ["Blinding is unreported.", "Observed outcome count is unknown."],
                "inference": "Completion alone does not establish observation.",
                "counterevidence": [
                    {"text": "Analysis is reported.", "sources": [selected["handle"]]}
                ],
            }
        ],
    }
    saved = support._call(workspace, "save_working_checkpoint", {"checkpoint": draft})
    assert saved["outcome"] == "success", saved
    step = _context(workspace, "domain:missing")["working_checkpoint"]["checkpoint"][
        "result_account"
    ][0]
    assert step["unknowns"] == draft["result_account"][0]["unknowns"]
    assert step["inference"] == draft["result_account"][0]["inference"]
    assert step["observation"]["sources"] == [
        {
            "source_id": selected["source_id"],
            "page": 1,
            "start_line": 2,
            "end_line": 3,
        }
    ]
    assert step["counterevidence"][0]["sources"] == step["observation"]["sources"]
    assert _state(workspace) == prior
    bad = copy.deepcopy(draft)
    bad["result_account"][0]["observation"]["sources"] = ["eh_" + "f" * 16]
    rejected = support._call(workspace, "save_working_checkpoint", {"checkpoint": bad})
    assert rejected["outcome"] == "condition"
    unchanged = _context(workspace, "domain:missing")["working_checkpoint"]["checkpoint"][
        "result_account"
    ][0]
    assert unchanged == step


def test_account_visual_reference_reuses_delivered_image_selector(account: tuple):
    workspace, _, _, _ = account
    with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as connection:
        delivery = connection.execute("SELECT identity FROM visual_deliveries LIMIT 1").fetchone()[
            0
        ]
        candidates = [
            json.loads(bytes(row[0]))
            for row in connection.execute("SELECT payload FROM evidence_handles")
        ]
    visual = next(e for e in candidates if e["kind"] == "figure")
    reference = {
        "delivery_receipt": delivery,
        "region": [0, 0, 1, 1],
        "transcription": visual["transcription"],
        "uncertainty": "Count meaning unresolved.",
    }
    draft: dict[str, Any] = {
        "trial_id": "trial",
        "result_account": [
            {
                "id": "flow",
                "aspect": "analysis",
                "observation": {"text": "Flow has analysis counts.", "sources": [reference]},
                "unknowns": ["Actual outcome observation is unresolved."],
            }
        ],
    }
    saved = support._call(workspace, "save_working_checkpoint", {"checkpoint": draft})
    assert saved["outcome"] == "success", saved
    step = _context(workspace, "domain:missing")["working_checkpoint"]["checkpoint"][
        "result_account"
    ][0]
    assert step["observation"]["sources"] == [
        {
            "source_id": source_handle(visual["source_id"]),
            "page": 1,
            "start_line": 0,
            "end_line": 0,
        }
    ]
    assert step["unknowns"] == ["Actual outcome observation is unresolved."]
    with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as connection:
        items = [
            json.loads(bytes(row[0]))
            for row in connection.execute("SELECT payload FROM evidence_handles")
        ]
    resolved = next(e for e in items if e.get("uncertainty") == reference["uncertainty"])
    assert resolved["render"]["page"] == 1
    assert resolved["render"]["source_id"] == visual["source_id"]
    assert resolved["region"] == [0.0, 0.0, 1.0, 1.0]

    # Resaving the returned whole-page note preserves its canonical content identity.
    resaved = support._call(
        workspace,
        "save_working_checkpoint",
        {
            "checkpoint": {"trial_id": "trial", "result_account": [step]},
        },
    )
    assert resaved["outcome"] == "success", resaved
    again = _context(workspace, "domain:missing")["working_checkpoint"]["checkpoint"][
        "result_account"
    ][0]
    assert again == step
    bad = copy.deepcopy(draft)
    bad["result_account"][0]["observation"]["sources"][0]["delivery_receipt"] = "sha256:" + "f" * 64
    rejected = support._call(workspace, "save_working_checkpoint", {"checkpoint": bad})
    assert rejected["outcome"] == "condition"
    assert (
        _context(workspace, "domain:missing")["working_checkpoint"]["checkpoint"]["result_account"][
            0
        ]
        == step
    )


def test_compact_step_citation_preserves_source_qualifiers_without_reciting_evidence(account):
    from rob2_kit.application.domains import resolve_domain_sources
    from rob2_kit.workflow_models import (
        DomainEvidenceCitation,
        DomainSaveAnswer,
        WorkingSourceRange,
    )

    workspace, main, _, revision = account
    step = _context(workspace, "domain:deviations")["working_checkpoint"]["checkpoint"][
        "result_account"
    ][0]
    draft = support._domain_draft("trial", "domain:deviations", revision, main)
    answer = next(
        a for a in draft["answers"] if a["question_id"] == "sq:deviations:appropriate-analysis"
    )
    answer["bases"] = [{"step_identity": step["identity"], "role": "context"}]
    # The shorthand expands to the same existing citation+snapshot representation.
    public = support._domain_submission(draft)
    parsed = DomainSaveAnswer.model_validate(
        next(a for a in public["answers"] if a["question_id"] == answer["question_id"])
    )
    resolved = resolve_domain_sources(workspace, "trial", [parsed])[0]
    explicit = parsed.model_copy(
        update={
            "bases": tuple(
                DomainEvidenceCitation(
                    evidence=WorkingSourceRange.model_validate(location),
                    role="context",
                    working_observation={"step_identity": step["identity"]},
                )
                for location in step["observation"]["sources"]
            )
        }
    )
    assert (
        resolved.canonical_payload()
        == resolve_domain_sources(workspace, "trial", [explicit])[0].canonical_payload()
    )
    result = support._call(workspace, "save_domain_judgment", draft)
    assert result["outcome"] == "success", result
    stored = next(
        a
        for a in _state(workspace)["domain_records"]["trial:domain:deviations"]["answers"]
        if a["question_id"] == answer["question_id"]
    )
    snapshot = stored["bases"][0]["working_observation"]["result_step"]
    assert snapshot == step
    assert snapshot["unknowns"] == ["Observed urine count remains unknown."]
    assert (
        snapshot["counterevidence"][0]["text"]
        == "Analysis membership includes more than completers."
    )
    assert stored["answer"] == answer["answer"]


@pytest.mark.parametrize(
    "role,transfer,success",
    [
        ("direct_support", None, False),
        ("context", None, False),
        ("inference", "Earlier phase is relevant only through this explicit transfer.", True),
    ],
)
def test_compact_step_retains_existing_scope_transfer_rules(account, role, transfer, success):
    workspace, main, _, revision = account
    step = _context(workspace, "domain:deviations")["working_checkpoint"]["checkpoint"][
        "result_account"
    ][1]
    draft = support._domain_draft("trial", "domain:deviations", revision, main)
    draft["answers"][0]["bases"] = [
        {"step_identity": step["identity"], "role": role, "transfer": transfer}
    ]
    result = support._call(workspace, "save_domain_judgment", draft)
    assert (result["outcome"] == "success") is success, result
    if not success:
        assert any(r["code"] == "result_step_transfer" for r in result["repairs"])


def test_compact_step_unknown_identity_cannot_supply_an_evidence_basis(account):
    workspace, main, _, revision = account
    draft = support._domain_draft("trial", "domain:deviations", revision, main)
    draft["answers"][0]["bases"] = [{"step_identity": "sha256:" + "0" * 64, "role": "inference"}]
    before = copy.deepcopy(_state(workspace))
    result = support._call(workspace, "save_domain_judgment", draft)
    assert result["outcome"] == "condition", result
    assert _state(workspace) == before


def test_compact_step_visual_locator_requires_original_region_citation(account):
    workspace, main, _, revision = account
    steps = copy.deepcopy(
        _context(workspace, "domain:deviations")["working_checkpoint"]["checkpoint"][
            "result_account"
        ]
    )
    for step in steps:
        step.pop("identity", None)
    visual_handle = steps[0]["counts"][0]["basis"][0]
    steps[0]["observation"]["sources"] = [visual_handle]
    saved = support._call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": {"trial_id": "trial", "result_account": steps}},
    )
    assert saved["outcome"] == "success", saved
    current = _context(workspace, "domain:deviations")["working_checkpoint"]["checkpoint"][
        "result_account"
    ][0]
    draft = support._domain_draft("trial", "domain:deviations", revision, main)
    draft["answers"][0]["bases"] = [{"step_identity": current["identity"], "role": "context"}]
    before = copy.deepcopy(_state(workspace))
    rejected = support._call(workspace, "save_domain_judgment", draft)
    assert rejected["outcome"] == "condition", rejected
    assert _state(workspace) == before
    draft["answers"][0]["bases"] = [
        {
            "kind": "context",
            "evidence": visual_handle,
            "working_observation": {"step_identity": current["identity"]},
        }
    ]
    accepted = support._call(workspace, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success", accepted
