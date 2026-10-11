from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastmcp import Client
from pydantic import ValidationError
from support.rob2 import (
    _call,
    _domain_draft,
    _domain_submission,
    _prepared_evidence,
    _proposal_args,
    _public_proposal_records,
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _db, _ensure, _root
from rob2_kit.application.working import _delivery_projection
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.models import canonical_json_bytes
from rob2_kit.packs.scientific import SCIENTIFIC_PACK
from rob2_kit.workflow_models import WorkingCheckpoint, WorkingPremiseRecord, WorkingSourceBinding


def test_delivery_coverage_unions_overlaps_without_erasing_gaps_or_scope(tmp_path: Path) -> None:
    _ensure(_root(tmp_path))
    source, empty, older = ("source_" + c * 64 for c in "abc")
    bindings = tuple(
        WorkingSourceBinding(source_id=s, projection_hash="sha256:" + "d" * 64)
        for s in (source, empty)
    )
    state = {"batch": {"identity": "batch"}}
    rows = [("batch", "assessment", "trial", source, 1, n, n + 1) for n in range(1, 130)] + [
        ("batch", "assessment", "trial", source, 1, 141, 200),
        ("batch", "proposal", "trial", source, 1, 1, 5),
        ("batch", "assessment", "trial", source, 2, 1, 3),
        ("batch", "assessment", "trial", empty, 1, 0, 0),
        ("batch", "assessment", "trial", older, 1, 1, 260),
        ("other-batch", "assessment", "trial", source, 1, 1, 260),
    ]
    with _db(tmp_path, "derivative.sqlite3") as connection:
        connection.executemany("INSERT INTO page_reads VALUES (?,?,?,?,?,?,?)", rows)
        connection.executemany(
            "INSERT INTO pages VALUES (?,?,?)",
            [(source, 1, "line\n" * 260), (source, 2, "line\n" * 3), (empty, 1, "")],
        )
    coverage = _delivery_projection(tmp_path, state, "trial", bindings)
    assert coverage["state"] == "partial"
    assert not coverage["ranges_truncated"]
    assert coverage["range_count"] == 5
    assert [
        (r["page"], r["phase"], r["start_line"], r["end_line"]) for r in coverage["ranges"]
    ] == [
        (1, "assessment", 1, 130),
        (1, "assessment", 141, 200),
        (1, "proposal", 1, 5),
        (2, "assessment", 1, 3),
        (1, "assessment", 0, 0),
    ]
    with _db(tmp_path, "derivative.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM page_reads").fetchone()[0] == len(rows)
        connection.executemany(
            "INSERT INTO page_reads VALUES (?,?,?,?,?,?,?)",
            [
                ("batch", "assessment", "trial", source, 1, 131, 140),
                ("batch", "assessment", "trial", source, 1, 201, 260),
            ],
        )
    completed = _delivery_projection(tmp_path, state, "trial", bindings)
    assert completed["state"] == "delivered"
    assert completed["range_count"] == 4
    assert completed["ranges"][0]["end_line"] == 260


def _checkpoint(source_id: str, text: str = "Allocation concealment is not yet clear.") -> dict:
    return {
        "trial_id": "trial",
        "observations": [
            {
                "text": text,
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:concealment",
            }
        ],
        "interpretations": [
            {
                "text": "The report does not describe who generated the sequence.",
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
                "domain_id": "domain:randomization",
            }
        ],
        "terminology": [
            {
                "term": "central allocation",
                "meaning": "Assignment is issued after enrollment by a central service.",
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
            }
        ],
        "unread_ranges": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
        "open_questions": [
            {
                "text": "Was the allocation sequence concealed until assignment?",
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:concealment",
            }
        ],
        "drafts": [
            {
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:concealment",
                "answer": "no_information",
                "text": ("Do not treat the silence as evidence of inadequate concealment."),
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
            }
        ],
        "next_action": "Read the protocol section on sequence generation and concealment.",
    }


def _proposal_waiting_for_review(workspace: Path) -> dict:
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required", proposed
    return evidence


def _public_call(
    workspace: Path,
    calls: list[str],
    tool: str,
    arguments: dict,
    *,
    approve: bool = False,
) -> dict:
    """Make and record exactly one public MCP call, including approval elicitation."""

    async def invoke() -> dict:
        previous_workspace = os.environ.get("ROB2_WORKSPACE")
        os.environ["ROB2_WORKSPACE"] = str(workspace)

        async def elicit(
            _message: str, _response_type: type | None, _params: object, _context: object
        ) -> dict[str, bool]:
            return {"approved": True}

        try:
            options = {"elicitation_handler": elicit} if approve else {}
            async with Client(mcp, **options) as client:
                result = await client.call_tool(
                    tool,
                    _domain_submission(arguments) if tool == "save_domain_judgment" else arguments,
                )
                return dict(result.structured_content or {})
        finally:
            if previous_workspace is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous_workspace

    calls.append(tool)
    return asyncio.run(invoke())


def _handoff_checkpoint(source_id: str, *, result_bound: bool) -> dict:
    facts = [
        {
            "text": (
                "The report defines Overall Survival as death from any cause and states "
                "that assessment continued through 30 June 2024."
                if result_bound
                else "Participants were individually randomly assigned to intervention and control."
            ),
            "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
            "domain_id": "domain:randomization",
        }
    ]
    return {
        "trial_id": "trial",
        "main_report_source_id": source_id,
        "observations": facts,
        "premise_records": [
            {
                "proposition": "The allocation sequence was generated unpredictably.",
                "status": "unresolved",
                "observations": facts,
                "inference": (
                    "The report describes individual random assignment but does not state "
                    "how its sequence was generated."
                ),
                "unresolved_component": "The sequence-generation method is not reported.",
                "next_action": "Check the methods section for the sequence-generation method.",
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:sequence",
            }
        ],
        "next_action": "Inspect the allocation-method passage before answering D1.",
    }


def test_result_bound_checkpoint_handoff_avoids_postapproval_main_report_read(
    tmp_path: Path,
) -> None:
    def run_handoff_case(case_dir: Path, *, rebind_notes: bool) -> dict:
        workspace = _workspace(case_dir, "Overall Survival")
        (workspace / "input" / "trial" / "main.txt").write_text(
            "Participants were individually randomly assigned to intervention and control groups. "
            "The Overall Survival was measured in the analyzed population. It was defined as "
            "death from any cause through 30 June 2024; death ascertainment; end of follow-up; "
            "assigned to intervention; assigned to control; randomized population; risk ratio; "
            "risk; 1; events; 2.\n",
            encoding="utf-8",
        )
        calls: list[str] = []
        reads: list[dict[str, int | bool]] = []
        repairs = 0
        after_approval = False
        inline_report_bytes = 0

        def call(tool: str, arguments: dict, *, approve: bool = False) -> dict:
            nonlocal repairs, inline_report_bytes
            receipt = _public_call(workspace, calls, tool, arguments, approve=approve)
            if receipt.get("outcome") == "repair":
                repairs += 1
            if tool == "read_pages":
                pages = receipt.get("data", {}).get("pages", [])
                reads.append(
                    {
                        "postapproval": after_approval,
                        "bytes": sum(
                            len(line.partition("|")[2].encode("utf-8"))
                            for page in pages
                            for line in str(page.get("numbered_text", "")).splitlines()
                        ),
                    }
                )
            if tool == "get_domain_context" and after_approval:
                inline_report_bytes += sum(
                    len(line.partition("|")[2].encode("utf-8"))
                    for page in receipt.get("data", {}).get("primary_report", [])
                    for line in str(page.get("numbered_text", "")).splitlines()
                )
            return receipt

        prepared = call(
            "prepare_batch",
            {"requested_outcome": "Overall Survival", "expected_revision": 0},
        )
        assert prepared["outcome"] == "success", prepared
        initial_status = call("get_status", {})
        reading = initial_status["data"]["main_report_reading"]["trial"]
        assert reading["status"] == "required", reading
        initial_read = call(
            "read_pages",
            {"trial_id": "trial", "windows": reading["required_ranges"]},
        )
        assert initial_read["outcome"] == "success", initial_read

        sources = call("list_sources", {"trial_id": "trial"})["data"]["sources"]
        source = next(item for item in sources if item["label"] == "main.txt")
        evidence = call(
            "select_text_evidence",
            {
                "trial_id": "trial",
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": 1,
            },
        )["data"]["evidence"]

        preproposal = call(
            "save_working_checkpoint",
            {"checkpoint": _handoff_checkpoint(source["id"], result_bound=False)},
        )
        assert preproposal["outcome"] == "success", preproposal

        result = _result(evidence, "Overall Survival")
        revision = int(call("get_status", {})["head"]["state_revision"])
        validation = call(
            "validate_proposal",
            {
                **_public_proposal_records(
                    [result],
                    [
                        {
                            "trial_id": "trial",
                            "evidence_basis": [evidence["handle"]],
                            "scope_justification": "The reported endpoint matches the target.",
                            "population_justification": "Analysis retains randomized participants.",
                            "unknowns": [],
                            "counterevidence": [],
                        }
                    ],
                ),
                "expected_revision": revision,
            },
        )
        assert validation["outcome"] == "success", validation
        proposal = call("save_proposal", validation["data"]["next_action"])
        assert proposal["outcome"] == "review_required", proposal

        status = call("get_status", {})
        assert status["data"]["working_checkpoint"]["status"] == "stale"
        assert status["data"]["working_checkpoint"]["reason"] == "result_changed"
        if rebind_notes:
            rebound = call(
                "save_working_checkpoint",
                {"checkpoint": _handoff_checkpoint(source["id"], result_bound=True)},
            )
            assert rebound["outcome"] == "success", rebound
            current = call("get_status", {})["data"]["working_checkpoint"]
            assert current["status"] == "current"
            assert current["checkpoint"]["result_identity"] == rebound["data"]["result_identity"]

        approved = call("request_proposal_approval", {}, approve=True)
        assert approved["outcome"] == "success", approved
        after_approval = True
        status = call("get_status", {})
        assert status["head"]["phase"] == "assessment"
        draft = _domain_draft(
            "trial",
            "domain:randomization",
            int(status["head"]["state_revision"]),
            evidence,
        )

        context = call(
            "get_domain_context",
            {
                "trial_id": "trial",
                "domain_id": "domain:randomization",
                "max_response_bytes": 24_000,
            },
        )
        assert context["outcome"] == "success", context
        recovery = context["data"]["reading_recovery"]
        investigation = context["data"]["investigation"]
        context_page = context["data"]["context_page"]
        while context_page["next_cursor"] is not None:
            context = call(
                "get_domain_context",
                {
                    "trial_id": "trial",
                    "domain_id": "domain:randomization",
                    "cursor": context_page["next_cursor"],
                },
            )
            assert context["outcome"] == "success", context
            context_page = context["data"]["context_page"]
        if rebind_notes:
            assert investigation["status"] == "unresolved"
            assert investigation["proposition"] == (
                "The allocation sequence was generated unpredictably."
            )
            assert investigation["stale"] == []
            # Reading recovery reports phase-local delivery gaps even when a
            # result-bound checkpoint supplies the authorized handoff.
            assert recovery["status"] == "required"
            saved = call("save_domain_judgment", draft)
            assert saved["outcome"] == "success", saved
        else:
            assert recovery["status"] == "required"
            rejected = call("save_domain_judgment", draft)
            assert rejected["outcome"] == "repair", rejected
            assert any(
                r["code"] == "post_approval_main_report_reading_required"
                for r in rejected["repairs"]
            )
            call("read_pages", {"trial_id": "trial", "source_id": source["id"], "pages": [1]})
            saved = call("save_domain_judgment", draft)
            assert saved["outcome"] == "success", saved

        assert calls.count("request_proposal_approval") == 1
        assert calls.count("read_pages") == (1 if rebind_notes else 2)
        assert calls.count("save_domain_judgment") == (1 if rebind_notes else 2)
        return {
            "repairs": repairs,
            "inline_report_bytes": inline_report_bytes,
            "reads": reads,
            "repeated_source_bytes": sum(
                int(item["bytes"]) for item in reads if item["postapproval"]
            ),
            "postapproval_read_calls": sum(bool(item["postapproval"]) for item in reads),
        }

    without_rebind = run_handoff_case(tmp_path / "without-rebind", rebind_notes=False)
    with_rebind = run_handoff_case(tmp_path / "with-rebind", rebind_notes=True)

    assert without_rebind["inline_report_bytes"] == 0
    assert with_rebind["inline_report_bytes"] == 0
    assert without_rebind["postapproval_read_calls"] == 1
    assert with_rebind["postapproval_read_calls"] == 0
    assert without_rebind["repeated_source_bytes"] > 0
    assert with_rebind["repeated_source_bytes"] == 0
    assert without_rebind["repairs"] == 1
    assert with_rebind["repairs"] == 0


@pytest.mark.parametrize(
    "scenario",
    [
        "cohort",
        "fixed_time_probability",
        "follow_up_hazard_ratio",
        "adverse_event_threshold",
    ],
)
def test_working_checkpoint_is_hidden_after_result_scope_replacement(
    tmp_path: Path, scenario: str
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    source_id = evidence["source_id"]
    _call(workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(source_id)})
    _review(workspace)

    revised = _result(evidence)
    if scenario == "cohort":
        revised["reported"]["analysis_population"] = "per-protocol population"
    elif scenario == "fixed_time_probability":
        revised["target"]["time_point_or_window"]["description"] = "12 weeks after randomization"
        revised["target"]["intended_effect_measure"] = "probability"
    elif scenario == "follow_up_hazard_ratio":
        revised["target"]["time_point_or_window"]["description"] = "end of follow-up"
        revised["target"]["intended_effect_measure"] = "hazard ratio"
    else:
        revised["target"]["measurement"]["method"] = (
            "grade 3 or higher treatment-emergent adverse events"
        )
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [revised]))

    assert proposed["outcome"] == "review_required", proposed
    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "stale"
    assert status["reason"] == "result_changed"
    assert status["checkpoint"] is None
    assert status["recovery"] == "reorient_from_sources"


def test_unresolved_premise_requires_a_component() -> None:
    with pytest.raises(ValidationError, match="unresolved_component"):
        WorkingPremiseRecord.model_validate(
            {
                "proposition": "The missingness mechanism is outcome-dependent.",
                "status": "unresolved",
            }
        )


@pytest.mark.parametrize(
    ("premise_status", "source_scope_matches"),
    [("bounded", True), ("support", True), ("support", False)],
)
def test_trial_review_retains_source_observations_after_domain_commits(
    tmp_path: Path, premise_status: str, source_scope_matches: bool
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    checkpoint = _checkpoint(evidence["source_id"])
    checkpoint["premise_records"] = [
        {
            "proposition": "Allocation remained concealed until assignment.",
            "status": premise_status,
            "observations": checkpoint["observations"],
            "inference": "The host tentatively regarded concealment as adequate.",
            "counterevidence": checkpoint["observations"],
            "unresolved_component": "The concealment procedure is not reported.",
            "stopping_rationale": "The captured report leaves the procedure unresolved.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:concealment",
            "next_action": "Read the remaining accessible protocol section.",
        }
    ]
    saved = _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})
    assert saved["outcome"] == "success", saved

    database = workspace / ".rob2-kit" / "working.sqlite3"
    with sqlite3.connect(database) as connection:
        original_payload = connection.execute("SELECT payload FROM working_checkpoints").fetchone()[
            0
        ]

    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(
        _call(
            workspace,
            "get_domain_context",
            {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
        )["head"]["state_revision"]
    )
    for domain in SCIENTIFIC_PACK.domains:
        saved_domain = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved_domain["outcome"] == "success", saved_domain
        revision = int(saved_domain["head"]["state_revision"])

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT payload FROM working_checkpoints").fetchone()[0] == (
            original_payload
        )
        if not source_scope_matches:
            payload = json.loads(original_payload)
            payload["source_scope"][0]["projection_hash"] = "sha256:" + "f" * 64
            payload["identity"] = None
            stale = WorkingCheckpoint.model_validate(payload)
            connection.execute(
                "UPDATE working_checkpoints SET identity=?,payload=?",
                (
                    stale.identity,
                    canonical_json_bytes(stale.model_dump(mode="json", exclude_none=True)),
                ),
            )

    review = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": revision},
    )
    assert review["outcome"] == "success", review
    review_page = review["data"].get("review_page")
    if review_page is not None:
        premise_count = review_page["counts"]["premise_records"]
    else:
        premise_count = sum(
            len(finding["premise_records"]) for finding in review["data"]["domain_findings"]
        )
    assert premise_count == (1 if source_scope_matches else 0)
    if not source_scope_matches:
        if review_page is not None:
            assert "premise_records" not in review_page["deferred_fields"]
        return
    if review_page is not None:
        assert "premise_records" in review_page["deferred_fields"]
    recovered = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": review["head"]["state_revision"],
            "domain_id": "domain:randomization",
        },
    )
    assert recovered["outcome"] == "success", recovered
    if "review_page" in recovered["data"]:
        assert recovered["data"]["review_page"]["complete"] is True
    randomization = recovered["data"]["domain_findings"][0]
    assert randomization["premise_records"][0]["observations"]
    assert randomization["premise_records"][0]["observations"] == checkpoint["observations"]
    retained = randomization["premise_records"][0]
    assert retained["counterevidence"] == checkpoint["observations"]
    assert retained["status"] == "unresolved"
    assert retained.get("inference") is None
    assert retained.get("stopping_rationale") is None
    assert randomization["premise_checkpoint_identity"] is not None
    concealment = next(
        item
        for item in randomization["answers"]
        if item["question_id"] == "sq:randomization:concealment"
    )
    assert concealment["uninvestigated_routes"]
