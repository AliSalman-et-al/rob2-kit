"""An open-label trial assessed through the gates and repairs a real host meets."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

from e2e import trial
from e2e.agent import REPO, Agent, answer, rob2

MAIN = "main_article"


def repair_codes(value: dict) -> set[str]:
    return {item["code"] for item in value.get("repairs", [])}


def test_open_label_trial_through_repairs_restart_and_adjudication(tmp_path: Path) -> None:
    trial.build_open_label(tmp_path)
    agent = Agent(tmp_path)
    try:
        agent.prepare("knee pain at 12 months")

        # Quoting needs the quoted lines delivered first.
        quote = "Mean difference -1.2 (95% CI -2.0 to -0.4)"
        unread = agent.call(
            "select_text_evidence",
            {
                "trial_id": agent.trial_id,
                "source_id": agent.sources[MAIN],
                "page": 1,
                "selected_text": quote,
            },
        )
        assert unread["outcome"] == "condition"
        # A host that reads only the results lines can cite them, but validating before the
        # main-report pass is refused and the head names the windows still to read.
        agent.ok(
            "read_pages",
            {
                "trial_id": agent.trial_id,
                "windows": [
                    {"source_id": agent.sources[MAIN], "page": 1, "start_line": 14, "end_line": 16}
                ],
            },
        )
        early_passage = agent.cite(MAIN, 1, quote)
        early = agent.call(
            "validate_proposal",
            {
                "selections": [
                    {
                        "trial_id": agent.trial_id,
                        "relation": "related",
                        "candidate": {
                            "design": "individual_parallel",
                            "design_rationale": "Randomised 1:1.",
                            "design_evidence": [early_passage],
                            "target_measurement": "Knee pain",
                            "target_window": "12 months",
                            "comparison_groups": [
                                {"id": "surgery", "assignment": "Surgery"},
                                {"id": "physiotherapy", "assignment": "Physiotherapy"},
                            ],
                            "baseline_subgroup": None,
                            "intended_effect_measure": "mean difference",
                            "reported_outcome": "Knee pain",
                            "analysis_population": "completers",
                            "effect_measure": "Mean difference",
                            "estimate": "-1.2",
                        },
                        "scope_rationale": "Pain at 12 months.",
                        "source_passages": [early_passage],
                        "unknowns": [],
                        "counterevidence": [],
                    }
                ],
                "expected_revision": agent.revision(),
            },
        )
        assert "main_report_reading_required" in repair_codes(early), early
        assert agent.next_action()["operation"] == "read_pages"
        agent.read_required()

        cite = agent.cite_lines
        table = cite(MAIN, 1, "Table 2. Knee pain at 12 months", "-2.0 to -0.4)")
        design = cite(MAIN, 1, "randomised (1:1)")
        selection = {
            "relation": "narrower",
            "candidate": {
                "design": "individual_parallel",
                "design_rationale": "Adults were individually randomised to two parallel groups.",
                "design_evidence": [design],
                "target_measurement": "Knee pain (0 to 10)",
                "target_window": "12 months",
                "comparison_groups": [
                    {"id": "surgery", "assignment": "Arthroscopic surgery"},
                    {"id": "physiotherapy", "assignment": "12-week physiotherapy programme"},
                ],
                "baseline_subgroup": None,
                "intended_effect_measure": "mean difference",
                "reported_outcome": "Knee pain at 12 months (0 to 10)",
                "reported_definition": None,
                "analysis_population": "participants who completed their allocated treatment",
                "effect_measure": "Mean difference",
                "estimate": "-1.2",
                "precision": "95% CI -2.0 to -0.4 (Table 2)",
                "group_values": None,
                "reported_statistics": None,
            },
            "scope_rationale": "Table 2 reports pain at 12 months for a per-protocol population.",
            "population_rationale": "Only participants who completed treatment were analysed.",
            "source_passages": [table],
            "unknowns": [],
            "counterevidence": [],
        }

        # An annotated source value is not a literal quote.
        assert "result_value_not_supported" in repair_codes(agent.propose(selection))
        selection["candidate"]["precision"] = "95% CI -2.0 to -0.4"
        agent.propose(selection)
        agent.approve()
        agent.read_required()

        sequence = cite(MAIN, 1, "computer random number generator")
        envelopes = cite(MAIN, 1, "Allocation used envelopes held by the recruiting")
        baseline = cite(MAIN, 1, "Baseline characteristics were similar")
        unblinded = cite(MAIN, 1, "Neither participants nor clinicians were blinded")
        crossover = cite(
            MAIN, 1, "Eight participants allocated to physiotherapy", "during the trial."
        )
        per_protocol = cite(MAIN, 1, "The analysis included only participants", "(per-protocol)")
        follow_up = cite(MAIN, 1, "Pain at 12 months was available", "physiotherapy participants.")
        reasons = cite(MAIN, 1, "Withdrawals in the surgery group", "lack of")
        reported = cite(MAIN, 1, "The primary outcome was knee pain", "participants at 12 months.")

        randomization = [
            answer("sq:randomization:sequence", "yes", [sequence], "Computer random numbers."),
            answer(
                "sq:randomization:concealment",
                "probably_no",
                [envelopes],
                "Envelopes held by the recruiter.",
            ),
            answer("sq:randomization:baseline-imbalance", "no", [baseline], "Groups were similar."),
        ]
        incomplete = agent.save_domain("domain:randomization", randomization[:2])
        assert "answers_must_match_active_questions" in repair_codes(incomplete)
        stale = agent.call(
            "save_domain_judgment",
            {
                "trial_id": agent.trial_id,
                "domain_id": "domain:randomization",
                "expected_revision": agent.revision() - 1,
                "answers": randomization,
            },
        )
        assert stale.get("outcome") != "success"
        assert agent.save_domain("domain:randomization", randomization)["outcome"] == "success"

        deviations = [
            answer("sq:deviations:participants-aware", "yes", [unblinded], "Open label."),
            answer("sq:deviations:personnel-aware", "yes", [unblinded], "Open label."),
            answer(
                "sq:deviations:context-deviations",
                "yes",
                [crossover],
                "Disappointed controls sought surgery.",
            ),
            answer(
                "sq:deviations:affected-outcome",
                "probably_yes",
                [crossover],
                "Surgery changes pain.",
            ),
            answer(
                "sq:deviations:balanced",
                "no",
                [crossover],
                "Only the physiotherapy group crossed over.",
            ),
            answer(
                "sq:deviations:appropriate-analysis",
                "no",
                [per_protocol],
                "Naive per-protocol analysis.",
            ),
            answer(
                "sq:deviations:substantial-impact",
                "probably_yes",
                [per_protocol, follow_up],
                "34 excluded.",
            ),
        ]
        assert agent.save_domain("domain:deviations", deviations)["outcome"] == "success"
    finally:
        agent.close()

    # A new session resumes from status: the next Domain, after rereading the report.
    agent = Agent(tmp_path)
    try:
        agent.trial_id = "knee-arthroscopy"
        listed = agent.ok("list_sources", {"trial_id": agent.trial_id})
        agent.sources = {source["role"]: source["id"] for source in listed["data"]["sources"]}
        agent.read_required()
        assert agent.next_action()["domain_id"] == "domain:missing"

        missing = [
            answer("sq:missing:data-available", "no", [follow_up], "22% and 12% missing."),
            answer("sq:missing:evidence-unbiased", "no", [follow_up], "No sensitivity analysis."),
            answer(
                "sq:missing:true-value-dependent",
                "yes",
                [reasons],
                "Withdrawal for lack of improvement.",
            ),
            answer(
                "sq:missing:likely-dependent",
                "yes",
                [reasons, follow_up],
                "Outcome-related, differing.",
            ),
        ]
        missing[3]["counterevidence"] = [
            {"evidence": follow_up, "implication": "Both arms lost participants."}
        ]
        assert agent.save_domain("domain:missing", missing)["outcome"] == "success"

        measurement = [
            answer(
                "sq:measurement:method-inappropriate", "no", [reported], "A validated pain scale."
            ),
            answer(
                "sq:measurement:differential",
                "no",
                [reported],
                "Same scale and time in both groups.",
            ),
            answer(
                "sq:measurement:assessor-aware",
                "yes",
                [unblinded],
                "Participants report pain and knew.",
            ),
            answer("sq:measurement:influence-possible", "yes", [reported], "Self-reported pain."),
            answer(
                "sq:measurement:influence-likely",
                "probably_no",
                [reported],
                "No strong prior beliefs reported.",
            ),
        ]
        saved = agent.save_domain("domain:measurement", measurement)
        checkpoint = saved["data"]["checkpoint"]
        assert checkpoint["judgment"] == "some_concerns"

        # Depart from the proposed judgment on the unchanged checkpoint.
        adjudicated = agent.save_domain(
            "domain:measurement",
            measurement,
            supersedes=checkpoint["identity"],
            adjudication={
                "judgment": "high",
                "rationale": "Surgery versus physiotherapy invites strong expectations about pain.",
                "evidence": [unblinded],
            },
        )
        assert adjudicated["outcome"] == "success", adjudicated
        assert adjudicated["data"]["checkpoint"]["judgment"] == "high"

        selection_answers = [
            answer(
                "sq:selection:prespecified-analysis",
                "no_information",
                [reported],
                "No protocol or plan.",
            ),
            answer(
                "sq:selection:multiple-measurements",
                "no_information",
                [reported],
                "Intentions unavailable.",
            ),
            answer(
                "sq:selection:multiple-analyses",
                "no_information",
                [per_protocol],
                "Intentions unavailable.",
            ),
        ]
        assert agent.save_domain("domain:selection", selection_answers)["outcome"] == "success"

        agent.close_trials()
        finalized = agent.finalize()
    finally:
        agent.close()

    summary = finalized["data"]["assessment_summary"]["knee-arthroscopy"]
    assert summary["domains"] == {
        "domain:randomization": "high",
        "domain:deviations": "high",
        "domain:missing": "high",
        "domain:measurement": "high",
        "domain:selection": "some_concerns",
    }
    assert summary["overall"] == "high"

    bundle = tmp_path / finalized["data"]["artifact"]["path"]
    tampered = tmp_path / "tampered.rob2.zip"
    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(tampered, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "canonical.json":
                data = data.replace(b'"high"', b'"low"', 1)
            target.writestr(item, data)
    assert rob2(tmp_path, "verify", str(bundle)).returncode == 0
    assert rob2(tmp_path, "verify", str(tampered)).returncode != 0
    standalone = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(tampered)],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert standalone.returncode != 0
