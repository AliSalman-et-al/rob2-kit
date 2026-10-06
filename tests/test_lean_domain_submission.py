"""Compact source references use the same scientific and canonical boundaries."""

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError
from support import rob2 as support

from rob2_kit.application._state import _canonical_evidence_records, _state
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.packs.scientific import SCIENTIFIC_PACK

FACTS = [
    "Participants and providers knew assignments. Changes were ordinary clinical care, "
    "not caused by trial participation. Available outcomes were analysed by random assignment.",
    "Requested outcomes were missing for many participants. No reassuring recovery or "
    "sensitivity analysis was reported. Missingness was strongly associated with worse "
    "requested outcomes; most withdrawals followed deterioration, with some reasons unknown.",
    "The original plan predates unblinded access and specifies the requested outcome at "
    "end of follow-up and assigned-group analysis. The reported primary analysis matches it.",
    "The intended requested-outcome measurements and assigned-group analyses are reported, "
    "including the planned primary and sensitivity results. Later SAP finalization is undated.",
]


def workspace_with_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, additional_source: str | None = None
):
    original = support._workspace

    def create(path: Path, requested_outcome: str = "requested outcome") -> Path:
        workspace = original(path, requested_outcome)
        main = workspace / "input/trial/main.txt"
        main.write_text(main.read_text() + "\n".join(FACTS) + "\n")
        if additional_source is not None:
            (workspace / "input/trial/quotes.txt").write_text(additional_source)
        return workspace

    monkeypatch.setattr(support, "_workspace", create)
    return support._assessment_workspace(tmp_path)


def reference(evidence: dict, line: int) -> dict:
    return {"source_id": evidence["source_id"], "page": 1, "start_line": line, "end_line": line}


def answer(question: str, value: str, bases: list, *, unknowns: list | None = None) -> dict:
    return {
        "question_id": question,
        "answer": value,
        "bases": bases,
        "justification": "The cited source facts support this response for the approved Result.",
        "unknowns": unknowns or [],
        "counterevidence": [],
    }


@pytest.mark.parametrize(
    "timing,expected", [("probably_yes", "low"), ("no_information", "some_concerns")]
)
def test_complete_lean_d2_d3_d5_preserves_sources_uncertainty_and_native_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timing: str, expected: str
) -> None:
    workspace, evidence, revision = workspace_with_facts(tmp_path, monkeypatch)
    selected = support._call(
        workspace, "select_text_evidence", {"trial_id": "trial", **reference(evidence, 2)}
    )["data"]["evidence"]
    d2 = [
        answer("sq:deviations:participants-aware", "yes", [selected["handle"]]),
        answer("sq:deviations:personnel-aware", "yes", [selected["handle"]]),
        answer("sq:deviations:context-deviations", "no", [reference(evidence, 2)]),
        answer(
            "sq:deviations:appropriate-analysis",
            "probably_yes",
            [selected["handle"]],
            unknowns=["Unmeasured outcomes are not established."],
        ),
    ]
    missing_evidence = support._call(
        workspace, "select_text_evidence", {"trial_id": "trial", **reference(evidence, 3)}
    )["data"]["evidence"]
    d3 = [
        answer("sq:missing:data-available", "no", [reference(evidence, 3)]),
        answer("sq:missing:evidence-unbiased", "no", [reference(evidence, 3)]),
        answer(
            "sq:missing:true-value-dependent",
            "yes",
            [{"kind": "inference", "evidence": missing_evidence["handle"]}],
        ),
        answer(
            "sq:missing:likely-dependent",
            "probably_yes",
            [reference(evidence, 3)],
            unknowns=["Exact unobserved outcomes and some withdrawal reasons remain unknown."],
        ),
    ]
    d5 = [
        answer(
            "sq:selection:prespecified-analysis",
            timing,
            [reference(evidence, 4)],
            unknowns=["The later SAP finalization date is not reported."],
        ),
        answer("sq:selection:multiple-measurements", "probably_no", [reference(evidence, 5)]),
        answer("sq:selection:multiple-analyses", "probably_no", [reference(evidence, 5)]),
    ]
    d5[0]["counterevidence"] = [
        {
            "evidence": [reference(evidence, 5)],
            "implication": "The later version's date is unknown despite matching earlier intent.",
        }
    ]
    for domain, draft, label in [
        ("domain:deviations", d2, "low"),
        ("domain:missing", d3, "high"),
        ("domain:selection", d5, expected),
    ]:
        context = support._call(
            workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain}
        )
        assert context["outcome"] == "success", context
        cards = context["data"]["questions"]
        assert {card["id"] for card in cards} == {
            q.id for q in SCIENTIFIC_PACK.questions if q.domain_id == domain
        }
        official = {
            section["excerpt"] for section in context["data"]["official_guidance"]["sections"]
        }
        assert all(
            q.guidance.official.source_excerpt in official
            for q in SCIENTIFIC_PACK.questions
            if q.domain_id == domain
        )
        saved = support._call(
            workspace,
            "save_domain_judgment",
            {
                "trial_id": "trial",
                "domain_id": domain,
                "expected_revision": revision,
                "answers": draft,
            },
        )
        assert saved["outcome"] == "success", saved
        assert saved["data"]["checkpoint"]["judgment"] == label
        record = _state(workspace)["domain_records"][f"trial:{domain}"]
        assert record["active_questions"] == [x["question_id"] for x in draft]
        assert [x["answer"] for x in record["answers"]] == [x["answer"] for x in draft]
        ids = {b["evidence"] for a in record["answers"] for b in a["bases"]}
        catalog = _canonical_evidence_records(workspace, ids)
        for a in record["answers"]:
            for basis in a["bases"]:
                captured = catalog[basis["evidence"]]
                assert basis["source"] == captured["quote"]
                assert basis["source"] == FACTS[captured["start_line"] - 2]
                assert "working_observation" not in basis
        if domain == "domain:deviations":
            assert ids == {selected["identity"]}  # exact range reuses selected content
        if domain == "domain:missing":
            assert len(ids) == 1  # repeated references resolve to one canonical Evidence
        if domain == "domain:selection":
            assert record["answers"][0]["unknowns"] == draft[0]["unknowns"]
            assert (
                record["answers"][0]["counterevidence"][0]["implication"]
                == d5[0]["counterevidence"][0]["implication"]
            )
            assert record["answers"][0]["bases"][-1]["kind"] == "context"
        revision = saved["head"]["state_revision"]
    assert (
        support._call(workspace, "get_status", {})["data"]["working_checkpoint"]["status"]
        == "absent"
    )
    for domain in ["domain:randomization", "domain:measurement"]:
        saved = support._call(
            workspace,
            "save_domain_judgment",
            support._domain_draft("trial", domain, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = saved["head"]["state_revision"]
    artifact = support._finalize_assessment(workspace, revision)["data"]["artifact"]["path"]
    assert verify_bundle(workspace / artifact)
    assert support._standalone_verify(workspace / artifact).returncode == 0

    # Rehashing does not let the new uniform basis contract invent cited material.
    tampered = tmp_path / "inference-source-tamper.rob2.zip"

    def falsify_source(canonical: dict) -> None:
        missing = canonical["domain_records"]["trial:domain:missing"]
        dependent = next(
            item
            for item in missing["answers"]
            if item["question_id"] == "sq:missing:true-value-dependent"
        )
        dependent["bases"][0]["source"] = "Fabricated withdrawal reason not in the Source."

    support._rehashed_full_tamper(workspace / artifact, tampered, falsify_source)
    assert not verify_bundle(tampered)
    assert support._standalone_verify(tampered).returncode == 1


def test_valid_basis_structure_does_not_certify_entailment_or_rewrite_modality(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = support._assessment_workspace(tmp_path)
    draft = support._domain_draft("trial", "domain:randomization", revision, evidence)
    first = draft["answers"][0]
    first["answer"] = "yes"
    before = _state(workspace)
    for invalid in ([], [{"kind": "inference", "evidence": "eh_0000000000000000"}]):
        first["bases"] = invalid
        try:
            rejected = support._call(workspace, "save_domain_judgment", draft)
        except ToolError:
            pass
        else:
            assert rejected["outcome"] != "success", rejected
        assert _state(workspace) == before
    first.update(
        bases=[
            {
                "kind": "limitation",
                "unresolved_premise": "The sequence-generation method is not established.",
                "stopping_rationale": "This unsupported response tests structure only.",
            }
        ],
        justification="Unsupported Yes tests structural parity, not clinical validity.",
        unknowns=["The sequence-generation method is not established."],
        counterevidence=[],
    )
    saved = support._call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    stored = _state(workspace)["domain_records"]["trial:domain:randomization"]["answers"][0]
    assert stored["answer"] == "yes"
    assert [basis["kind"] for basis in stored["bases"]] == ["limitation"]
    revision = saved["head"]["state_revision"]
    for domain in SCIENTIFIC_PACK.domains:
        if domain.id == "domain:randomization":
            continue
        saved = support._call(
            workspace,
            "save_domain_judgment",
            support._domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = saved["head"]["state_revision"]
    path = support._finalize_assessment(workspace, revision)["data"]["artifact"]["path"]
    artifact = workspace / path
    assert verify_bundle(artifact)
    assert support._standalone_verify(artifact).returncode == 0

    # The declared predecessor retains its original modality predicate.
    predecessor = tmp_path / "predecessor-limitation-only.rob2.zip"

    def declare_predecessor(canonical: dict) -> None:
        canonical["scientific_pack"]["content_hash"] = (
            "sha256:0096ab3948d391e476d6d56b4e69f14f416253aa6c210ab0edc4d1b868566f08"
        )

    support._rehashed_full_tamper(artifact, predecessor, declare_predecessor)
    assert not verify_bundle(predecessor)
    independent = support._standalone_verify(predecessor)
    assert independent.returncode == 1
    assert "definitive Domain answer lacks a direct basis" in (
        str(independent.stdout) + str(independent.stderr)
    )


@pytest.mark.parametrize("invalid", ["handle", "source", "page", "lines", "quote"])
def test_lean_rejects_fabricated_sources_without_saving_a_domain(
    tmp_path: Path, invalid: str
) -> None:
    workspace, evidence, revision = support._assessment_workspace(tmp_path)
    ref = reference(evidence, 1)
    if invalid == "handle":
        ref = "eh_0123456789abcdef"
    elif invalid == "source":
        ref["source_id"] = "sh_0123456789abcdef"
    elif invalid == "page":
        ref["page"] = 999
    elif invalid == "lines":
        ref["end_line"] = 999
    else:
        ref["quote"] = "Invented source text"
    draft = support._domain_draft("trial", "domain:selection", revision, evidence)
    draft["answers"][0]["bases"] = [ref]
    try:
        result = support._call(workspace, "save_domain_judgment", draft)
        assert result["outcome"] in {"repair", "condition"}, result
    except ToolError:
        pass
    assert not _state(workspace).get("domain_records")
    assert _state(workspace)["revision"] == revision


@pytest.mark.parametrize("defect", ["missing_active_answer", "unresolved_definitive_claim"])
def test_lean_keeps_canonical_active_path_and_uncertainty_checks(
    tmp_path: Path, defect: str
) -> None:
    workspace, evidence, revision = support._assessment_workspace(tmp_path)
    draft = support._domain_draft("trial", "domain:selection", revision, evidence)
    for item in draft["answers"]:
        item["bases"] = [evidence["handle"]]
    if defect == "missing_active_answer":
        draft["answers"].pop()
    else:
        draft["answers"][0]["answer"] = "yes"
        draft["answers"][0]["limitations"] = [
            {
                "premise": "Finalization relative to unblinded access is unresolved.",
                "stopping_rationale": "The inspected source does not establish this event.",
            }
        ]
    saved = support._call(workspace, "save_domain_judgment", draft)
    if defect == "missing_active_answer":
        assert saved["outcome"] == "repair", saved
        assert not _state(workspace).get("domain_records")
        assert _state(workspace)["revision"] == revision
    else:
        assert saved["outcome"] == "success", saved
        record = _state(workspace)["domain_records"]["trial:domain:selection"]
        stored = record["answers"][0]
        assert stored["answer"] == "yes"
        assert any(
            b["kind"] == "limitation"
            and b["unresolved_premise"] == draft["answers"][0]["limitations"][0]["premise"]
            for b in stored["bases"]
        )


def test_inline_copied_quotes_reuse_reviewed_selector_and_preserve_canonical_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, evidence, revision = workspace_with_facts(
        tmp_path,
        monkeypatch,
        "Unread unique fact.\nRepeated.\nRepeated.\nRisk 1 3 years.\nDose 50 69 mg.\n",
    )
    source = evidence["source_id"]
    context = support._call(
        workspace,
        "get_domain_context",
        {
            "trial_id": "trial",
            "domain_id": "domain:deviations",
        },
    )
    assert context["outcome"] == "success"
    drafted = support._domain_draft("trial", "domain:deviations", revision, evidence)
    before = _state(workspace)
    for quote, page in [(FACTS[0], 2), (FACTS[0].replace("ordinary", "extraordinary"), 1)]:
        bad = {**drafted, "answers": [dict(item) for item in drafted["answers"]]}
        bad["answers"][0]["bases"] = [{"source_id": source, "page": page, "selected_text": quote}]
        rejected = support._call(workspace, "save_domain_judgment", bad)
        assert rejected["outcome"] != "success"
        assert _state(workspace) == before
    extra = next(
        item
        for item in support._call(workspace, "list_sources", {"trial_id": "trial"})["data"][
            "sources"
        ]
        if item["label"] == "quotes.txt"
    )

    def reject_extra(quote: str, expected: str) -> None:
        bad = {**drafted, "answers": [dict(item) for item in drafted["answers"]]}
        bad["answers"][0]["bases"] = [
            {
                "source_id": extra["id"],
                "page": 1,
                "selected_text": quote,
            }
        ]
        rejected = support._call(workspace, "save_domain_judgment", bad)
        assert rejected["outcome"] != "success"
        assert expected in str(rejected)
        assert _state(workspace) == before

    reject_extra("Unread unique fact.", "not fully delivered")
    support._call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "source_id": extra["id"],
            "pages": [1],
        },
    )
    reject_extra("Repeated.", "ambiguous")
    reject_extra("Risk 1-3 years.", "not an exact")
    reject_extra("Dose 50-69 mg.", "not an exact")
    ranged = support._call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            **reference(evidence, 2),
        },
    )["data"]["evidence"]
    quote_ref = {"source_id": source, "page": 1, "selected_text": FACTS[0]}
    drafted["answers"][0]["bases"] = [
        {
            "evidence": quote_ref,
            "role": "context",
            "working_observation": {
                "text": "Assignments were known; the quoted passage reports usual care."
            },
        }
    ]
    drafted["answers"][0]["counterevidence"] = [
        {
            "evidence": [quote_ref],
            "implication": "Usual care limits an inference of trial-context deviations.",
        }
    ]
    drafted["answers"][1]["bases"] = [quote_ref]
    saved = support._call(workspace, "save_domain_judgment", drafted)
    assert saved["outcome"] == "success", saved
    record = _state(workspace)["domain_records"]["trial:domain:deviations"]
    first = record["answers"][0]
    assert first["bases"][0]["evidence"] == ranged["identity"]
    assert first["bases"][0]["source"] == FACTS[0]
    assert first["bases"][0]["kind"] == "context"
    assert first["counterevidence"][0]["basis_index"] == 0
    assert record["answers"][1]["bases"][0]["evidence"] == ranged["identity"]
