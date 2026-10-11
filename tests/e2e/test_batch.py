"""A two-Trial batch exercising navigation, working notes and the unassessed path."""

from __future__ import annotations

import zipfile
from pathlib import Path

from e2e import trial
from e2e.agent import Agent, rob2
from e2e.test_assessment import OUTCOME, low_risk_answers, selection

MAIN = "main_article"
SPARSE = "dapa-glycaemia"
PREVENT = "prevent-tia"


def test_batch_with_unavailable_result_navigation_notes_and_archive(tmp_path: Path) -> None:
    trial.build(tmp_path)
    trial.build_sparse(tmp_path)
    agent = Agent(tmp_path)
    try:
        prepared = agent.prepare(OUTCOME)
        assert {item["id"] for item in prepared["data"]["trials"]} == {PREVENT, SPARSE}
        agent.read_required()
        # The batch resource reports the same workflow head as get_status.
        assert agent.resource("rob2://current-batch")["head"] == agent.ok("get_status")["head"]

        # Navigation: lexical search, a batch of searches, and a zero-hit absence receipt.
        agent.use(PREVENT)
        hits = agent.ok(
            "search_sources",
            {"trial_id": PREVENT, "query": "interactive web response", "mode": "phrase"},
        )["data"]["hits"]
        assert hits and hits[0]["page"] == 1
        batch = agent.ok(
            "search_sources_batch",
            {
                "requests": [
                    {"trial_id": PREVENT, "query": "masked", "mode": "all"},
                    {"trial_id": PREVENT, "query": "sealed opaque envelopes", "mode": "phrase"},
                ]
            },
        )
        masked, envelopes = (item["result"]["data"] for item in batch["data"]["results"])
        assert masked["hits"]
        assert envelopes["hits"] == []
        absence = envelopes["search_receipt"]
        assert agent.ok("read_guidance", {"document": "references/result.md"})["data"]
        arithmetic = agent.ok(
            "calculate_arithmetic", {"expression": "a / b", "inputs": {"a": "31", "b": "602"}}
        )
        assert arithmetic["result"].startswith("0.0514950")

        # Visual evidence from a rendered PDF page.
        rendered = agent.ok(
            "render_page", {"trial_id": PREVENT, "source_id": agent.sources[MAIN], "page": 2}
        )
        figure = agent.ok(
            "select_visual_evidence",
            {
                "trial_id": PREVENT,
                "source_id": agent.sources[MAIN],
                "delivery_receipt": rendered["data"]["delivery_receipt"],
                "transcription": "Table 2: recurrent stroke 31/602 apixaban, 52/602 aspirin.",
            },
        )["data"]["evidence"]["handle"]

        prevent_selection = {"trial_id": PREVENT, **selection(agent)}
        agent.use(SPARSE)
        missing = agent.cite_lines(MAIN, 1, "Stroke was not assessed")
        unavailable = {
            "trial_id": SPARSE,
            "relation": "unavailable",
            "candidate": None,
            "scope_rationale": "The report states that stroke was not assessed.",
            "population_rationale": None,
            "source_passages": [missing],
            "unknowns": [],
            "counterevidence": [],
            "missing_facts": [
                {
                    "fact": "Recurrent stroke within 12 months",
                    "basis": {"kind": "missing_reporting", "evidence": missing},
                }
            ],
        }
        agent.propose(prevent_selection, unavailable)
        agent.approve()
        agent.read_required()

        # Trials proceed in batch order: the unavailable Result is reviewed and closed first.
        assert agent.next_action() == {
            "operation": "review_trial",
            "authority": "host",
            "trial_id": SPARSE,
            "expected_revision": agent.revision(),
        }
        agent.close_trials()
        agent.read_required()
        agent.use(PREVENT)
        answers = low_risk_answers(agent)
        # Working notes carry reading across sessions.
        agent.ok(
            "save_working_checkpoint",
            {
                "checkpoint": {
                    "trial_id": PREVENT,
                    "observations": [
                        {
                            "text": "Central web allocation; outcome committee masked.",
                            "sources": [
                                {
                                    "source_id": agent.sources[MAIN],
                                    "page": 1,
                                    "start_line": 1,
                                    "end_line": 5,
                                }
                            ],
                        }
                    ],
                }
            },
        )
        # Answers may cite a figure and record a zero-hit search; D3 may carry counts.
        answers["domain:randomization"][0]["absence_searches"] = [absence]
        answers["domain:missing"][0]["bases"].append({"evidence": figure, "role": "context"})
        answers["domain:missing"][0]["missing_data"] = [
            {
                "arm": arm,
                "population": "randomised",
                "unit": "participants",
                "time_point": "12 months",
                "randomized": 602,
                "observed": observed,
            }
            for arm, observed in (("apixaban", 596), ("aspirin", 597))
        ]
        for domain_id, domain_answers in answers.items():
            assert agent.context()["domain_id"] == domain_id
            assert agent.save_domain(domain_id, domain_answers)["outcome"] == "success"
        review = agent.ok(
            "review_trial", {"trial_id": PREVENT, "expected_revision": agent.revision()}
        )
        detail = agent.ok(
            "review_trial",
            {
                "trial_id": PREVENT,
                "expected_revision": agent.revision(),
                "domain_id": "domain:missing",
                "question_id": "sq:missing:data-available",
            },
        )
        assert review["data"]["review"]["aggregation"]["adopted"] == "low"
        assert "sq:missing:data-available" in str(detail["data"])
        agent.close_trials()
        finalized = agent.finalize()
    finally:
        agent.close()
    # An unavailable Result needs a person to choose another outcome or supply sources.
    assert finalized["data"]["trial_dispositions"] == {SPARSE: "needs_input", PREVENT: "assessed"}
    assert finalized["data"]["assessment_summary"][PREVENT]["overall"] == "low"

    archive = tmp_path / "sources.zip"
    assert rob2(tmp_path, "archive-sources", "--output", str(archive)).returncode == 0
    assert rob2(tmp_path, "verify-sources", str(archive)).returncode == 0
    tampered = tmp_path / "tampered-sources.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w") as target:
        changed = 0
        for item in source.infolist():
            data = source.read(item)
            altered = data.replace(b"Stroke was not assessed", b"Stroke was not reported")
            changed += altered != data
            target.writestr(item, altered)
    assert changed == 1
    assert rob2(tmp_path, "verify-sources", str(tampered)).returncode != 0
    assert rob2(tmp_path, "export-skill", "--output", str(tmp_path / "skill")).returncode == 0
    assert (tmp_path / "skill" / "SKILL.md").is_file()
