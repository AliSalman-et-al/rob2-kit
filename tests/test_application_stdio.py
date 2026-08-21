from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from rob2_kit.interfaces.mcp.server import mcp


def test_mcp_current_batch_resource_is_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def read() -> dict[str, object]:
        async with Client(mcp) as client:
            names = [tool.name for tool in await client.list_tools()]
            resource = await client.read_resource("rob2://current-batch")
        assert names == [
            "preflight_sources",
            "inspect_candidate_sources",
            "save_intake_plan",
            "capture_batch",
            "list_sources",
            "retrieve_evidence",
            "render_page",
            "save_proposal",
            "approve_batch",
            "validate_domain_judgment",
            "commit_domain_judgment",
            "prepare_trial_finish",
            "finish_trial",
            "finalize_batch",
            "read_record",
        ]
        return json.loads(resource[0].text)

    payload = asyncio.run(read())
    assert payload["phase"] == "empty"


def test_stdio_clean_intake_auto_ack_and_conditional_review_survive_restart(tmp_path: Path) -> None:
    (tmp_path / "main.txt").write_text("main", encoding="utf-8")
    environment = os.environ.copy()
    environment["ROB2_WORKSPACE"] = str(tmp_path)

    def transport() -> StdioTransport:
        return StdioTransport(
            command=sys.executable,
            args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
            env=environment,
        )

    async def clean() -> dict[str, object]:
        async with Client(transport()) as client:
            preflight = await client.call_tool(
                "preflight_sources",
                {"roots": [{"alias": "trial", "path": ".", "trial_id": "trial"}]},
            )
            preflight_value = dict(preflight.structured_content or {})
            candidate = preflight_value["candidates"][0]
            assert "pages" not in candidate
            inspected = await client.call_tool(
                "inspect_candidate_sources",
                {"candidate_identity": candidate["identity"], "page": 1},
            )
            inspection = dict(inspected.structured_content or {})
            assert inspection["text"] == "main"
            assert "pages" not in inspection["candidate"]
            plan = await client.call_tool(
                "save_intake_plan",
                {
                    "preflight": preflight_value["reference"],
                    "entries": [
                        {
                            "candidate_identity": candidate["identity"],
                            "role": "main_article",
                            "disposition": "include",
                            "criticality": "required",
                        }
                    ],
                },
            )
            saved = dict(plan.structured_content or {})
            assert saved["acknowledgment"]["kind"] == "review_ack"
            captured = await client.call_tool(
                "capture_batch",
                {
                    "plan": saved["plan"],
                    "acknowledgment": saved["acknowledgment"],
                },
            )
            return dict(captured.structured_content or {})

    assert asyncio.run(clean())["outcome"] == "success"

    conditional = tmp_path / "conditional"
    conditional.mkdir()
    (conditional / "main.txt").write_text("main", encoding="utf-8")
    (conditional / "appendix.txt").write_text("appendix", encoding="utf-8")
    environment["ROB2_WORKSPACE"] = str(conditional)

    async def needs_researcher() -> dict[str, object]:
        async with Client(transport()) as client:
            preflight = dict(
                (
                    await client.call_tool(
                        "preflight_sources",
                        {"roots": [{"alias": "trial", "path": ".", "trial_id": "trial"}]},
                    )
                ).structured_content
                or {}
            )
            entries = [
                {
                    "candidate_identity": item["identity"],
                    "role": (
                        "main_article" if item["relative_path"] == "main.txt" else "supplement"
                    ),
                    "disposition": ("include" if item["relative_path"] == "main.txt" else "omit"),
                    "criticality": (
                        "required" if item["relative_path"] == "main.txt" else "optional"
                    ),
                    **(
                        {}
                        if item["relative_path"] == "main.txt"
                        else {"omission_reason": "reviewed"}
                    ),
                }
                for item in preflight["candidates"]
            ]
            return dict(
                (
                    await client.call_tool(
                        "save_intake_plan",
                        {"preflight": preflight["reference"], "entries": entries},
                    )
                ).structured_content
                or {}
            )

    saved = asyncio.run(needs_researcher())
    assert "acknowledgment" not in saved
    assert saved["conditions"]

    # A fresh stdio process sees the same unresolved researcher requirement.
    async def restarted() -> dict[str, object]:
        async with Client(transport()) as client:
            return json.loads((await client.read_resource("rob2://current-batch"))[0].text)

    restarted_status = asyncio.run(restarted())
    assert isinstance(restarted_status.get("presentation"), dict)
    presentation = cast(dict[str, object], restarted_status["presentation"])
    assert presentation.get("code") == "intake_acknowledgment_required"


def test_stdio_public_assessed_workflow_commits_all_five_domains(tmp_path: Path) -> None:
    """Run a complete assessed Batch through the published MCP boundary."""

    source = (
        "PFS evidence: time to biochemical, symptomatic, or radiographic progression; "
        "median time to progression; follow-up analysis; randomized patients; "
        "ADT plus docetaxel 20.2 months; ADT alone 11.7 months; "
        "hazard ratio 0.61 (95% CI 0.51 to 0.72; P<0.001). "
        "comparative time-to-event efficacy result."
    )
    (tmp_path / "article.txt").write_text(source, encoding="utf-8")
    environment = os.environ.copy()
    environment["ROB2_WORKSPACE"] = str(tmp_path)

    def transport() -> StdioTransport:
        return StdioTransport(
            command=sys.executable,
            args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
            env=environment,
        )

    def acknowledge_review() -> None:
        review = subprocess.run(
            [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "review"],
            input="yes\n",
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        assert review.returncode == 0, review.stderr or review.stdout

    async def exercise() -> dict[str, object]:
        async with Client(transport()) as client:
            preflight = dict(
                (
                    await client.call_tool(
                        "preflight_sources",
                        {"roots": [{"alias": "trial", "path": ".", "trial_id": "chaarted"}]},
                    )
                ).structured_content
                or {}
            )
            candidate = dict(preflight["candidates"][0])
            plan = dict(
                (
                    await client.call_tool(
                        "save_intake_plan",
                        {
                            "preflight": preflight["reference"],
                            "entries": [
                                {
                                    "candidate_identity": candidate["identity"],
                                    "role": "main_article",
                                    "disposition": "include",
                                    "criticality": "required",
                                }
                            ],
                        },
                    )
                ).structured_content
                or {}
            )
            captured = dict(
                (
                    await client.call_tool(
                        "capture_batch",
                        {
                            "plan": plan["plan"],
                            "acknowledgment": plan["acknowledgment"],
                        },
                    )
                ).structured_content
                or {}
            )
            assert captured["outcome"] == "success"

            listed = dict(
                (
                    await client.call_tool("list_sources", {"trial_id": "chaarted"})
                ).structured_content
                or {}
            )
            alias = dict(listed["sources"][0])["alias"]
            retrieved = dict(
                (
                    await client.call_tool(
                        "retrieve_evidence",
                        {
                            "trial_id": "chaarted",
                            "manual_selections": [
                                {
                                    "kind": "manual_selection",
                                    "source_alias": alias,
                                    "page": 1,
                                    "start": 0,
                                    "end": len(source),
                                    "quote": source,
                                }
                            ],
                        },
                    )
                ).structured_content
                or {}
            )
            evidence = dict(retrieved["evidence"][0])
            evidence_ref = {"kind": "evidence", "identity": evidence["identity"]}
            clarity = {"state": "specified"}
            card = {
                "trial_id": "chaarted",
                "target": {
                    "outcome_definition": (
                        "time to biochemical, symptomatic, or radiographic progression"
                    ),
                    "measurement": "median time to progression",
                    "time_point_or_window": "follow-up analysis",
                    "effect_of_interest": (
                        "effect on time to biochemical, symptomatic, or radiographic progression"
                    ),
                    "comparison_groups": [
                        {"id": "docetaxel", "label": "ADT plus docetaxel"},
                        {"id": "adt", "label": "ADT alone"},
                    ],
                    "intended_analysis_population": "randomized patients",
                    "intended_effect_measure": "hazard ratio",
                },
                "reported": {
                    "form": "comparative_effect",
                    "effect_measure": "hazard ratio",
                    "reported_text": source,
                    "effect": {
                        "statistic": "hazard ratio",
                        "unit": "ratio",
                        "group_or_category": "docetaxel versus adt",
                        "value": "0.61 (95% CI 0.51 to 0.72; P<0.001)",
                        "denominator_basis": "time-to-event analysis",
                    },
                    "quantities": [
                        {
                            "statistic": "median",
                            "unit": "months",
                            "group_or_category": "docetaxel",
                            "value": "20.2",
                            "denominator_basis": "randomized arm",
                        },
                        {
                            "statistic": "median",
                            "unit": "months",
                            "group_or_category": "adt",
                            "value": "11.7",
                            "denominator_basis": "randomized arm",
                        },
                    ],
                    "comparison_groups": ["docetaxel", "adt"],
                },
                "population": {
                    "analyzed_population": "randomized patients",
                    "outcome_measurement_coverage": [
                        {"group_id": "docetaxel", "status": "measured"},
                        {"group_id": "adt", "status": "measured"},
                    ],
                },
                "source_table_meaning": (
                    "Secondary endpoint: time to biochemical, symptomatic, or radiographic "
                    "progression"
                ),
                "evidence": {
                    "target_basis": [evidence_ref],
                    "reported_values": [evidence_ref],
                    "reported_context": [evidence_ref],
                    "population_basis": [evidence_ref],
                },
                "clarity": {
                    "outcome_definition": clarity,
                    "measurement": clarity,
                    "time_point": clarity,
                    "analysis_population": clarity,
                    "comparison_groups": clarity,
                    "effect_measure": clarity,
                    "source_table_meaning": clarity,
                    "choice_among_eligible_results": clarity,
                },
            }
            proposal = dict(
                (
                    await client.call_tool(
                        "save_proposal",
                        {
                            "proposal": {
                                "outcome_statement": (
                                    "effect on time to biochemical, symptomatic, or radiographic "
                                    "progression"
                                ),
                                "results": [card],
                            }
                        },
                    )
                ).structured_content
                or {}
            )
            assert proposal["outcome"] == "success"

            acknowledge_review()
            status = json.loads((await client.read_resource("rob2://current-batch"))[0].text)
            continuation = dict(status["continuation"])
            approved = dict(
                (
                    await client.call_tool(
                        "approve_batch",
                        {
                            "transition": proposal["transition"],
                            "acknowledgment": continuation["acknowledgment"],
                        },
                    )
                ).structured_content
                or {}
            )
            assert approved["outcome"] == "success"

            answer_paths = {
                "domain:randomization": {
                    "sq:randomization:sequence": "yes",
                    "sq:randomization:concealment": "yes",
                    "sq:randomization:baseline-imbalance": "no",
                },
                "domain:deviations": {
                    "sq:deviations:participants-aware": "no",
                    "sq:deviations:personnel-aware": "no",
                    "sq:deviations:appropriate-analysis": "yes",
                },
                "domain:missing": {"sq:missing:data-available": "yes"},
                "domain:measurement": {
                    "sq:measurement:method-inappropriate": "no",
                    "sq:measurement:differential": "no",
                    "sq:measurement:assessor-aware": "yes",
                    "sq:measurement:influence-possible": "no",
                },
                "domain:selection": {
                    "sq:selection:prespecified-analysis": "yes",
                    "sq:selection:multiple-measurements": "no",
                    "sq:selection:multiple-analyses": "no",
                },
            }
            packet = approved["approved_batch"]
            domain_ids = tuple(answer_paths)
            for index, domain_id in enumerate(domain_ids, 1):
                draft = {
                    "active_answers": [
                        {
                            "question_id": question_id,
                            "answer": answer,
                            "rationale": (
                                "The captured trial report supports this deterministic answer."
                            ),
                            "evidence_uses": [
                                {
                                    "relationship": "supporting",
                                    "claim": (
                                        "The captured trial report is the basis for this answer."
                                    ),
                                    "rationale": "The exact evidence record is in the trial scope.",
                                    "evidence": [evidence_ref],
                                }
                            ],
                        }
                        for question_id, answer in answer_paths[domain_id].items()
                    ]
                }
                validated = dict(
                    (
                        await client.call_tool(
                            "validate_domain_judgment", {"packet": packet, "draft": draft}
                        )
                    ).structured_content
                    or {}
                )
                assert validated["outcome"] == "success", validated
                committed = dict(
                    (
                        await client.call_tool(
                            "commit_domain_judgment", {"transition": validated["transition"]}
                        )
                    ).structured_content
                    or {}
                )
                assert committed["outcome"] == "success"
                status = json.loads((await client.read_resource("rob2://current-batch"))[0].text)
                committed_domains = dict(status["committed_domains"])
                assert len(committed_domains) == index
                assert f"chaarted:result:{domain_id}" in committed_domains
                if index < len(domain_ids):
                    packet = dict(committed["next_action"])["packet"]

            prepared = dict(
                (
                    await client.call_tool(
                        "prepare_trial_finish",
                        {
                            "packet": packet,
                            "candidate": {"disposition": "assessed"},
                        },
                    )
                ).structured_content
                or {}
            )
            assert prepared["outcome"] == "success"
            acknowledge_review()
            status = json.loads((await client.read_resource("rob2://current-batch"))[0].text)
            finish_continuation = dict(status["continuation"])
            finished = dict(
                (
                    await client.call_tool(
                        "finish_trial",
                        {
                            "transition": prepared["transition"],
                            "acknowledgment": finish_continuation["acknowledgment"],
                        },
                    )
                ).structured_content
                or {}
            )
            assert finished["outcome"] == "success"
            final = dict((await client.call_tool("finalize_batch", {})).structured_content or {})
            assert final["outcome"] == "success"
            assert dict(final["counts"])["assessed"] == 1
            assert dict(final["presentation"])["code"] == "finalized_all_assessed"
            return final

    result = asyncio.run(exercise())
    artifact = result.get("artifact")
    assert isinstance(artifact, dict)
    bundle_path = artifact.get("bundle_path")
    assert isinstance(bundle_path, str) and bundle_path
    from rob2_kit.evaluation.manifest import CHAARTED_MANIFEST
    from rob2_kit.evaluation.verifier import verify_artifact

    verified = verify_artifact(tmp_path / bundle_path, CHAARTED_MANIFEST, "pfs")
    assert verified.ok, verified.failures
