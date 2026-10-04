"""Fail-closed verification of the public wheel contract."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "release" / "public-contract.json"


def _load_contract() -> dict[str, Any]:
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if set(value) != {
        "contract_version",
        "tools",
        "resources",
        "resource_descriptions",
        "resource_templates",
        "skill_pointers",
        "examples",
    }:
        raise ValueError("public contract shape differs")
    if value["contract_version"] != "0.11.0":
        raise ValueError("public contract version differs")
    expected_order = [
        "read_guidance",
        "prepare_batch",
        "get_status",
        "save_working_checkpoint",
        "list_sources",
        "search_sources",
        "search_sources_batch",
        "read_pages",
        "select_text_evidence",
        "render_page",
        "select_visual_evidence",
        "validate_proposal",
        "save_proposal",
        "request_proposal_approval",
        "get_domain_context",
        "save_domain_judgment",
        "review_trial",
        "close_trial",
        "finalize_batch",
    ]
    if [item["name"] for item in value["tools"]] != expected_order:
        raise ValueError("public tool order differs")
    if any(
        set(item)
        != {
            "name",
            "title",
            "description",
            "read_only",
            "destructive",
            "idempotent",
            "open_world",
            "schema_sha256",
            "output_schema_sha256",
        }
        for item in value["tools"]
    ):
        raise ValueError("public tool schema hash fields differ")
    if any(not item["title"].strip() for item in value["tools"]):
        raise ValueError("public tool title is missing")
    if any(not item["description"].strip() for item in value["tools"]):
        raise ValueError("public tool description is missing")
    if any(item["destructive"] or not item["idempotent"] for item in value["tools"]):
        raise ValueError("public tool safety annotations differ")
    if value["resources"] != ["rob2://current-batch"] or value["resource_templates"] != ["rob2://guidance/{name}"]:
        raise ValueError("public resource catalog differs")
    if set(value["resource_descriptions"]) != {"rob2://current-batch"} or not all(
        isinstance(description, str) and description.strip()
        for description in value["resource_descriptions"].values()
    ):
        raise ValueError("public resource description is missing")
    return value


def _assert_generated(contract: dict[str, Any]) -> None:
    from rob2_kit.contract_manifest import _manifest

    generated = asyncio.run(_manifest())
    if generated != contract:
        raise ValueError("checked public contract differs from generated runtime contract")


def _schema_hash(schema: dict[str, Any]) -> str:
    text = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _verify_d3_projection(context: dict[str, Any]) -> None:
    """Check D3 identity and source coverage without enforcing maintainer science."""
    questions = context.get("questions")
    if not isinstance(questions, list):
        raise ValueError("D3 question cards are missing")
    expected = {
        "sq:missing:data-available",
        "sq:missing:evidence-unbiased",
        "sq:missing:true-value-dependent",
        "sq:missing:likely-dependent",
    }
    if {q.get("id") for q in questions if isinstance(q, dict)} != expected:
        raise ValueError("D3 question identity differs")
    for question in questions:
        options = {"yes", "probably_yes", "probably_no", "no"}
        if question["id"] != "sq:missing:evidence-unbiased":
            options.add("no_information")
        if set(question.get("options", [])) != options:
            raise ValueError("D3 official answer options differ")
        if not question.get("activation") or not question.get("query_suggestions"):
            raise ValueError("D3 dependencies or source navigation are missing")
    core = context.get("official_guidance")
    if not isinstance(core, dict) or not core.get("complete"):
        raise ValueError("D3 official guidance is incomplete")
    covered = {
        q
        for section in core.get("sections", [])
        if section.get("source_version") == "22 August 2019"
        and section.get("source_sha256")
        == "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670"
        and section.get("excerpt")
        for q in section.get("question_ids", [])
    }
    if covered != expected:
        raise ValueError("D3 official source coverage differs")


def _verify_packaged_skill(skill: str, reference: str) -> None:
    """Check scientific-source routing and co-located interface instructions."""
    for asset in (skill, reference):
        if not all(
            marker in asset
            for marker in (
                "official_guidance.sections",
                "official_d3_prototype",
                "counterevidence",
                "missing_data",
            )
        ):
            raise ValueError("packaged D3 source routing or submission instructions are missing")
    if not all(
        marker in reference
        for marker in (
            "read_pages",
            "basis",
            "randomized - observed",
            "scoped",
        )
    ):
        raise ValueError("packaged D3 source recovery or typed arithmetic is missing")


async def _verify_client(client: Client, contract: dict[str, Any]) -> None:
    tools = await client.list_tools()
    if [tool.name for tool in tools] != [item["name"] for item in contract["tools"]]:
        raise ValueError("MCP tool catalog differs")
    for tool, expected in zip(tools, contract["tools"], strict=True):
        annotations = tool.annotations
        if annotations is None or annotations.read_only_hint != expected["read_only"]:
            raise ValueError(f"MCP annotations differ: {tool.name}")
        if bool(annotations.open_world_hint) != expected["open_world"]:
            raise ValueError(f"MCP open-world annotation differs: {tool.name}")
        if bool(annotations.destructive_hint) != expected["destructive"]:
            raise ValueError(f"MCP destructive annotation differs: {tool.name}")
        if bool(annotations.idempotent_hint) != expected["idempotent"]:
            raise ValueError(f"MCP idempotent annotation differs: {tool.name}")
        if _schema_hash(tool.input_schema) != expected["schema_sha256"]:
            raise ValueError(f"MCP schema hash differs: {tool.name}")
        if (tool.description or "").strip() != expected["description"]:
            raise ValueError(f"MCP description differs: {tool.name}")
        if (tool.title or "").strip() != expected["title"]:
            raise ValueError(f"MCP title differs: {tool.name}")
        if tool.output_schema is None:
            raise ValueError(f"MCP output schema is missing: {tool.name}")
        if _schema_hash(tool.output_schema) != expected["output_schema_sha256"]:
            raise ValueError(f"MCP output schema hash differs: {tool.name}")
    resources = [str(item.uri) for item in await client.list_resources()]
    templates = [str(item.uri_template) for item in await client.list_resource_templates()]
    if resources != contract["resources"] or templates != contract["resource_templates"]:
        raise ValueError("MCP resource catalog differs")
    resource_items = await client.list_resources()
    descriptions = {str(item.uri): (item.description or "").strip() for item in resource_items}
    if descriptions != contract["resource_descriptions"]:
        raise ValueError("MCP resource descriptions differ")
    current = await client.read_resource("rob2://current-batch")
    if len(current) != 1 or not getattr(current[0], "text", None):
        raise ValueError("current-batch resource is unreadable")


async def _call(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def one(request: dict[str, Any]) -> dict[str, Any]:
        result = await client.call_tool(name, request)
        value = result.structured_content
        if not isinstance(value, dict):
            raise ValueError(f"{name} did not return structured content")
        if name != "render_page" and result.content != []:
            raise ValueError(f"{name} returned unexpected content")
        return value

    value = await one(arguments)
    if name == "get_domain_context" and "cursor" not in arguments:
        pages = [value]
        while (
            isinstance(value.get("data"), dict)
            and isinstance(value["data"].get("context_page"), dict)
            and value["data"]["context_page"].get("next_cursor") is not None
        ):
            value = await one({"cursor": value["data"]["context_page"]["next_cursor"]})
            pages.append(value)
        if len(pages) > 1 and all(isinstance(page.get("data"), dict) for page in pages):
            merged = dict(pages[0])
            data = dict(pages[0]["data"])
            for section in ("questions", "comparison_cards", "evidence"):
                data[section] = [item for page in pages for item in page["data"].get(section, [])]
            data.pop("context_page", None)
            merged["data"] = data
            merged["head"] = pages[-1].get("head", merged.get("head"))
            value = merged
    flat = dict(value)
    head = flat.get("head")
    if isinstance(head, dict):
        flat["phase"] = head["phase"]
        flat["state_revision"] = head["state_revision"]
    data = flat.get("data")
    if isinstance(data, dict):
        flat.update(data)
    return flat


def _acceptance_result(evidence: dict[str, Any]) -> dict[str, Any]:
    phrase = "requested outcome"
    return {
        "trial_id": "trial",
        "relation": "exact",
        "scope_rationale": "The selected Evidence supports endpoint and time correspondence.",
        "population_rationale": (
            "The reported population is distinguished from baseline eligibility."
        ),
        "source_passages": [evidence["handle"]],
        "unknowns": [],
        "counterevidence": [],
        "candidate": {
            "clarity": {
                name: "specified"
                for name in (
                    "outcome_definition",
                    "measurement",
                    "time_point",
                    "analysis_population",
                    "comparison_groups",
                    "effect_measure",
                    "source_table_meaning",
                    "eligible_result_choice",
                )
            },
            "design": "individual_parallel",
            "design_rationale": "The fixture is an individually randomized parallel trial.",
            "design_evidence": [evidence["handle"]],
            "target_measurement": phrase,
            "target_window": phrase,
            "comparison_groups": [
                {"id": "a", "assignment": phrase},
                {"id": "b", "assignment": phrase},
            ],
            "baseline_subgroup": None,
            "intended_effect_measure": phrase,
            "reported_outcome": phrase,
            "reported_definition": phrase,
            "analysis_population": phrase,
            "group_values": [
                {"group_id": group, "statistic": phrase, "value": phrase, "unit": phrase}
                for group in ("a", "b")
            ],
        },
    }


async def _verify_proposal(client: Client) -> None:
    """Exercise intake, Evidence selection, and the sole Proposal gate."""

    prepared = await _call(
        client,
        "prepare_batch",
        {
            "expected_revision": 0,
            "requested_outcome": "requested outcome",
        },
    )
    if prepared.get("phase") != "proposal":
        raise ValueError("acceptance intake did not reach proposal")
    sources = await _call(client, "list_sources", {"trial_id": "trial"})
    rows = sources.get("sources")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("acceptance source catalog differs")
    if not isinstance(sources.get("conditions"), list) or not isinstance(
        sources.get("omissions"), list
    ):
        raise ValueError("acceptance source inventory omitted intake conditions or omissions")
    navigated = await _call(
        client,
        "list_sources",
        {"trial_id": "trial", "source_id": rows[0]["id"]},
    )
    navigation = navigated.get("navigation")
    if (
        not isinstance(navigation, dict)
        or navigation.get("source_id") != rows[0]["id"]
        or not isinstance(navigation.get("entries"), list)
        or not navigation["entries"]
        or not isinstance(navigation.get("pages_without_text_projection"), list)
    ):
        raise ValueError("acceptance direct Source navigation differs")
    batched = await _call(
        client,
        "search_sources_batch",
        {
            "requests": [
                {"trial_id": "trial", "query": "requested outcome", "mode": "all"},
                {"trial_id": "trial", "query": "absent phrase", "mode": "phrase"},
            ]
        },
    )
    batch_results = batched.get("results")
    if (
        not isinstance(batch_results, list)
        or len(batch_results) != 2
        or batch_results[0].get("result", {}).get("outcome") != "success"
        or not batch_results[0]["result"].get("data", {}).get("hits")
        or batch_results[1].get("result", {}).get("outcome") != "success"
        or batch_results[1]["result"].get("data", {}).get("condition") != "no_hits"
    ):
        raise ValueError(f"acceptance independent search batch differs: {batched}")
    await _call(
        client, "read_pages", {"trial_id": "trial", "source_id": rows[0]["id"], "pages": [1]}
    )
    selected = await _call(
        client,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": rows[0]["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )
    evidence = selected.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("acceptance evidence selection failed")
    result = _acceptance_result(evidence)
    reasoned = await _call(
        client,
        "validate_proposal",
        {
            "selections": [result],
            "expected_revision": prepared["state_revision"],
        },
    )
    if reasoned.get("outcome") != "success":
        raise ValueError("acceptance proposal reasoning did not succeed")
    proposed = await _call(
        client,
        "save_proposal",
        reasoned["next_action"],
    )
    if proposed.get("outcome") != "review_required":
        raise ValueError("acceptance proposal did not request researcher approval")


def _domain_answers(
    context: dict[str, Any],
    evidence: dict[str, Any],
    search_receipt: str,
    question_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Create a typed, evidence-backed no-information path for release acceptance."""

    answers: list[dict[str, Any]] = []
    for question in context.get("questions", []):
        if not isinstance(question, dict) or (
            question_ids is None
            and question.get("activation_status")
            not in {"always_active", "active_in_saved_checkpoint"}
        ):
            continue
        if question_ids is not None and question.get("id") not in question_ids:
            continue
        options = question.get("options", [])
        if not isinstance(options, list):
            raise ValueError("acceptance Domain question options are malformed")
        answer = (
            "no_information"
            if "no_information" in options
            else "probably_no"
            if "probably_no" in options
            else None
        )
        if not isinstance(answer, str):
            raise ValueError("acceptance Domain question has no usable uncertainty option")
        basis = (
            {
                "kind": "limitation",
                "unresolved_premise": "The release acceptance source does not report this fact.",
                "stopping_rationale": (
                    "The captured acceptance source was reviewed, but the premise remains "
                    "unresolved."
                ),
                "search_receipt": search_receipt,
            }
            if answer == "no_information"
            else {
                "kind": "direct_support",
                "evidence": evidence["handle"],
            }
        )
        answers.append(
            {
                "question_id": question["id"],
                "answer": answer,
                "bases": (
                    []
                    if answer == "no_information"
                    else [
                        {("role" if key == "kind" else key): value for key, value in basis.items()}
                    ]
                ),
                "limitations": (
                    [
                        {
                            ("premise" if key == "unresolved_premise" else key): value
                            for key, value in basis.items()
                            if key != "kind"
                        }
                    ]
                    if answer == "no_information"
                    else []
                ),
                "justification": "The cited basis supports the selected uncertainty option.",
                "unknowns": [],
                "counterevidence": [],
            }
        )
    return answers


async def _verify_domains(client: Client, evidence: dict[str, Any], domains: list[str]) -> int:
    """Save requested Domains through the public FastMCP client boundary."""

    revision = int((await _call(client, "get_status", {}))["state_revision"])
    sources = await _call(client, "list_sources", {"trial_id": "trial"})
    source_rows = sources.get("sources")
    if not isinstance(source_rows, list) or len(source_rows) != 1:
        raise ValueError("acceptance narrow-search source scope differs")
    source_id = source_rows[0].get("id")
    if not isinstance(source_id, str):
        raise ValueError("acceptance narrow-search Source ID is unavailable")
    await _call(client, "read_pages", {"trial_id": "trial", "source_id": source_id, "pages": [1]})
    narrow = await _call(
        client,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "release acceptance eligible lexical",
            "mode": "all",
            "source_id": source_id,
            "limit": 2,
        },
    )
    narrow_data = narrow.get("data")
    if not isinstance(narrow_data, dict) or narrow_data.get("condition") != "no_hits":
        raise ValueError("acceptance narrow-search no-hit behavior differs")
    diagnostic = narrow_data.get("diagnostic")
    navigation = diagnostic.get("navigation") if isinstance(diagnostic, dict) else None
    if (
        not isinstance(diagnostic, dict)
        or diagnostic.get("code") != "no_hits"
        or diagnostic.get("mode") != "all"
        or not isinstance(navigation, dict)
        or navigation.get("source_id") != source_id
        or not isinstance(navigation.get("entries"), list)
        or not navigation["entries"]
    ):
        raise ValueError(f"acceptance narrow-search diagnostic differs: {diagnostic}")
    navigation_action = diagnostic.get("next_action")
    if navigation.get("truncated"):
        if (
            not isinstance(navigation_action, dict)
            or navigation_action.get("operation") != "list_sources"
            or navigation_action.get("source_id") != source_id
            or navigation_action.get("cursor") != navigation.get("next_cursor")
        ):
            raise ValueError(f"acceptance navigation continuation differs: {diagnostic}")
        await _call(
            client,
            "list_sources",
            {
                key: value
                for key, value in navigation_action.items()
                if key not in {"kind", "operation"}
            },
        )
    elif navigation_action is not None:
        raise ValueError(f"acceptance complete navigation repeats an action: {diagnostic}")

    unscoped = await _call(
        client,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "release acceptance eligible lexical",
            "mode": "all",
            "limit": 2,
        },
    )
    unscoped_diagnostic = unscoped.get("diagnostic")
    if (
        not isinstance(unscoped_diagnostic, dict)
        or unscoped_diagnostic.get("code") != "no_hits"
        or unscoped_diagnostic.get("mode") != "all"
        or unscoped_diagnostic.get("next_action") is not None
        or "do not establish" not in unscoped_diagnostic.get("detail", "")
    ):
        raise ValueError(f"acceptance unscoped narrow-search differs: {unscoped_diagnostic}")
    for domain_id in domains:
        context = await _call(
            client,
            "get_domain_context",
            {
                "trial_id": "trial",
                "domain_id": domain_id,
                "max_response_bytes": 131_072,
            },
        )
        if context.get("domain_id") != domain_id:
            raise ValueError(f"acceptance Domain context differs: {domain_id}")
        if domain_id == "domain:missing":
            _verify_d3_projection(context)
        revision = int(context["state_revision"])
        searched = await _call(
            client,
            "search_sources",
            {
                "trial_id": "trial",
                "query": f"release acceptance absent {domain_id.replace(':', ' ')}",
                "mode": "all",
            },
        )
        search_data = searched.get("data")
        if (
            searched.get("outcome") != "success"
            or not isinstance(search_data, dict)
            or search_data.get("condition") != "no_hits"
            or not isinstance(search_data.get("search_receipt"), str)
        ):
            raise ValueError(f"acceptance Domain limitation search differs: {domain_id}")
        search_receipt = search_data["search_receipt"]
        answers = _domain_answers(context, evidence, search_receipt)
        for _attempt in range(5):
            saved = await _call(
                client,
                "save_domain_judgment",
                {
                    "trial_id": "trial",
                    "domain_id": domain_id,
                    "expected_revision": revision,
                    "answers": answers,
                },
            )
            if saved.get("outcome") == "success":
                break
            repair = next(
                (
                    item
                    for item in saved.get("repairs", [])
                    if isinstance(item, dict)
                    and item.get("code") == "answers_must_match_active_questions"
                ),
                None,
            )
            detail = repair.get("detail") if isinstance(repair, dict) else None
            match = re.search(r"active IDs: \[([^]]*)\]", str(detail))
            if match is None:
                raise ValueError(f"acceptance Domain save failed: {domain_id}: {saved}")
            active_ids = {item.strip() for item in match.group(1).split(",") if item.strip()}
            answers = _domain_answers(context, evidence, search_receipt, active_ids)
        else:
            raise ValueError(f"acceptance Domain save exceeded repair attempts: {domain_id}")
        revision = int(saved["state_revision"])
    return revision


def _verify_wheel_archive(wheel: Path) -> None:
    skill_members = {
        "rob2_kit/packs/d3_authoritative.py",
        "rob2_kit/skills/rob2-assess/SKILL.md",
        "rob2_kit/skills/rob2-assess/references/deviations.md",
        "rob2_kit/skills/rob2-assess/references/evidence.md",
        "rob2_kit/skills/rob2-assess/references/measurement.md",
        "rob2_kit/skills/rob2-assess/references/missing.md",
        "rob2_kit/skills/rob2-assess/references/randomization.md",
        "rob2_kit/skills/rob2-assess/references/result.md",
        "rob2_kit/skills/rob2-assess/references/selection.md",
    }
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            "\\" in name or ".." in name.split("/") for name in names
        ):
            raise ValueError("wheel archive has ambiguous members")
        entries = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(entries) != 1:
            raise ValueError("wheel entry point is unavailable")
        entry_points = archive.read(entries[0]).decode("utf-8").replace("\r\n", "\n")
        if entry_points != "[console_scripts]\nrob2 = rob2_kit.interfaces.cli.app:main\n":
            raise ValueError("wheel entry point differs")
        for host in ("codex.json", "claude-code.json"):
            member = f"rob2_kit/hosts/{host}"
            payload = json.loads(archive.read(member))
            expected_command = "rob2 mcp-codex" if host == "codex.json" else "rob2 mcp"
            if payload.get("mcp_command") != expected_command or payload.get("skills") != [
                "rob2-assess"
            ]:
                raise ValueError(f"wheel host contract differs: {host}")
        missing_skills = sorted(skill_members - set(names))
        if missing_skills:
            raise ValueError(f"wheel skill is incomplete: {', '.join(missing_skills)}")
        _verify_packaged_skill(
            archive.read("rob2_kit/skills/rob2-assess/SKILL.md").decode("utf-8"),
            archive.read("rob2_kit/skills/rob2-assess/references/missing.md").decode("utf-8"),
        )
        for member in sorted(skill_members):
            canonical = ROOT / "src" / Path(member)
            if not canonical.is_file():
                raise ValueError(f"canonical wheel skill member is missing: {member}")
            if archive.read(member) != canonical.read_bytes():
                raise ValueError(f"wheel skill member differs from canonical file: {member}")


def _installed_python(wheel: Path, directory: Path) -> Path:
    venv = directory / "venv"
    # Use the interpreter that runs this verifier.  On Windows, the machine
    # default can be an Anaconda build whose decorated ``sys.version`` breaks
    # stdlib/platform consumers during the real stdio acceptance check.
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return python


def verify(wheel: Path | None = None, bundle: Path | None = None) -> None:
    if bundle is not None:
        from rob2_kit.application.finalization import verify_bundle

        if not verify_bundle(bundle):
            raise ValueError("assessment bundle failed independent verification")
        return
    contract = _load_contract()
    _assert_generated(contract)
    if wheel is None:
        from rob2_kit.interfaces.mcp.server import mcp

        async def local_proposal() -> None:
            async with Client(mcp) as client:
                await _verify_client(client, contract)
                await _verify_proposal(client)

        async def local_domains() -> None:
            async with Client(mcp) as client:
                await _verify_client(client, contract)
                context = await _call(
                    client,
                    "get_domain_context",
                    {
                        "trial_id": "trial",
                        "domain_id": "domain:randomization",
                        "max_response_bytes": 131_072,
                    },
                )
                evidence_rows = context.get("evidence")
                if not isinstance(evidence_rows, list):
                    raise ValueError("source-tree acceptance returned no selected Evidence")
                evidence = next(
                    (
                        item
                        for item in evidence_rows
                        if isinstance(item, dict) and item.get("kind") == "narrative"
                    ),
                    None,
                )
                if not isinstance(evidence, dict):
                    raise ValueError("source-tree acceptance lost selected Evidence")
                await _verify_domains(
                    client,
                    evidence,
                    ["domain:randomization", "domain:deviations", "domain:missing"],
                )

        previous_workspace = os.environ.get("ROB2_WORKSPACE")
        with tempfile.TemporaryDirectory(prefix="rob2-release-local-") as temporary:
            try:
                os.environ["ROB2_WORKSPACE"] = temporary
                trial = Path(temporary) / "input" / "trial"
                trial.mkdir(parents=True)
                (trial / "main.txt").write_text("requested outcome", encoding="utf-8")
                (trial / "sources.toml").write_text(
                    'roles = { "main.txt" = "main_article" }\n', encoding="utf-8"
                )
                _verify_packaged_skill(
                    (ROOT / "src/rob2_kit/skills/rob2-assess/SKILL.md").read_text(encoding="utf-8"),
                    (ROOT / "src/rob2_kit/skills/rob2-assess/references/missing.md").read_text(
                        encoding="utf-8"
                    ),
                )
                asyncio.run(local_proposal())
                review = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rob2_kit.interfaces.cli.app",
                        "review",
                        "--workspace",
                        temporary,
                    ],
                    cwd=ROOT,
                    env=os.environ,
                    input="yes\n",
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if review.returncode != 0:
                    raise ValueError(f"source-tree Proposal review failed: {review.stderr.strip()}")
                asyncio.run(local_domains())
            finally:
                if previous_workspace is None:
                    os.environ.pop("ROB2_WORKSPACE", None)
                else:
                    os.environ["ROB2_WORKSPACE"] = previous_workspace
        return
    _verify_wheel_archive(wheel)
    with tempfile.TemporaryDirectory(prefix="rob2-release-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        trial = workspace / "input" / "trial"
        trial.mkdir(parents=True)
        (trial / "main.txt").write_text(
            "requested outcome",
            encoding="utf-8",
        )
        (trial / "sources.toml").write_text(
            'roles = { "main.txt" = "main_article" }\n', encoding="utf-8"
        )
        python = _installed_python(wheel, Path(temporary))
        environment = os.environ | {"ROB2_WORKSPACE": str(workspace)}
        domains = [
            "domain:randomization",
            "domain:deviations",
            "domain:missing",
            "domain:measurement",
            "domain:selection",
        ]

        async def proposal_process() -> None:
            transport = StdioTransport(
                command=str(python),
                args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
                env=environment,
            )
            async with Client(transport) as client:
                await _verify_client(client, contract)
                await _verify_proposal(client)

        # The researcher gate is deliberately exercised through the installed
        # CLI, not a private application helper or a second MCP operation.
        asyncio.run(proposal_process())
        review = subprocess.run(
            [
                str(python),
                "-m",
                "rob2_kit.interfaces.cli.app",
                "review",
                "--workspace",
                str(workspace),
            ],
            cwd=workspace,
            env=environment,
            input="yes\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if review.returncode != 0:
            raise ValueError(f"wheel-installed Proposal review failed: {review.stderr.strip()}")

        async def first_domain_process() -> None:
            transport = StdioTransport(
                command=str(python),
                args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
                env=environment,
            )
            async with Client(transport) as client:
                await _verify_client(client, contract)
                context = await _call(
                    client,
                    "get_domain_context",
                    {"trial_id": "trial", "domain_id": domains[0]},
                )
                evidence_rows = context.get("evidence")
                if not isinstance(evidence_rows, list):
                    raise ValueError("wheel restart acceptance returned no selected Evidence")
                evidence = next(
                    (
                        item
                        for item in evidence_rows
                        if isinstance(item, dict) and item.get("kind") == "narrative"
                    ),
                    None,
                )
                if not isinstance(evidence, dict):
                    raise ValueError("wheel restart acceptance lost selected Evidence")
                await _verify_domains(client, evidence, domains[:1])

        # Close the first MCP process after approval and one Domain.  The next
        # process must recover the durable ledger and continue from it.
        asyncio.run(first_domain_process())

        async def resumed_domains_process() -> None:
            transport = StdioTransport(
                command=str(python),
                args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
                env=environment,
            )
            async with Client(transport) as client:
                await _verify_client(client, contract)
                status = await _call(client, "get_status", {})
                if status.get("phase") != "assessment":
                    raise ValueError("wheel process restart did not resume assessment")
                context = await _call(
                    client,
                    "get_domain_context",
                    {"trial_id": "trial", "domain_id": domains[1]},
                )
                evidence_rows = context.get("evidence")
                if not isinstance(evidence_rows, list):
                    raise ValueError("wheel process restart returned no Domain Evidence")
                evidence = next(
                    (
                        item
                        for item in evidence_rows
                        if isinstance(item, dict) and item.get("kind") == "narrative"
                    ),
                    None,
                )
                if not isinstance(evidence, dict):
                    raise ValueError("wheel process restart lost Domain Evidence")
                await _verify_domains(client, evidence, domains[1:])

        asyncio.run(resumed_domains_process())

        artifact_path: Path | None = None

        async def finalization_process() -> None:
            nonlocal artifact_path
            transport = StdioTransport(
                command=str(python),
                args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
                env=environment,
            )
            async with Client(transport) as client:
                await _verify_client(client, contract)
                status = await _call(client, "get_status", {})
                action = status.get("head", {}).get("next_action")
                if not isinstance(action, dict) or action.get("operation") != "review_trial":
                    raise ValueError("wheel process restart did not reach Trial review")
                reviewed = await _call(
                    client,
                    "review_trial",
                    {
                        "trial_id": action["trial_id"],
                        "expected_revision": action["expected_revision"],
                    },
                )
                action = reviewed.get("head", {}).get("next_action")
                if not isinstance(action, dict) or action.get("operation") != "close_trial":
                    raise ValueError("wheel Trial review did not require explicit closure")
                closed = await _call(
                    client,
                    "close_trial",
                    {
                        "trial_id": action["trial_id"],
                        "expected_revision": action["expected_revision"],
                        "review_reference": action["review_reference"],
                    },
                )
                action = closed.get("head", {}).get("next_action")
                if not isinstance(action, dict) or action.get("operation") != "finalize_batch":
                    raise ValueError("closed Trial did not advance to Batch finalization")
                finalized = await _call(
                    client,
                    "finalize_batch",
                    {"expected_revision": action["expected_revision"]},
                )
                if finalized.get("outcome") != "success":
                    raise ValueError(f"wheel finalization failed: {finalized}")
                artifact = finalized.get("artifact")
                if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                    raise ValueError("wheel finalization did not return an artifact")
                artifact_path = workspace / artifact["path"]
                if not artifact_path.is_file():
                    raise ValueError("wheel finalization artifact is missing")

        # A third process proves that the final ledger and artifact survive a
        # host restart immediately before automatic finalization.
        asyncio.run(finalization_process())
        if artifact_path is None:
            raise ValueError("wheel finalization artifact path is unavailable")

        product_verify = subprocess.run(
            [str(python), "-m", "rob2_kit.interfaces.cli.app", "verify", str(artifact_path)],
            cwd=workspace,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if product_verify.returncode != 0:
            raise ValueError(f"wheel product bundle verification failed: {product_verify.stderr}")
        standalone_verify = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_bundle.py"), str(artifact_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if standalone_verify.returncode != 0:
            raise ValueError(
                f"standalone bundle verification failed: {standalone_verify.stdout}"
                f"{standalone_verify.stderr}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--bundle", type=Path)
    arguments = parser.parse_args()
    if arguments.wheel is not None and arguments.bundle is not None:
        parser.error("--wheel and --bundle are mutually exclusive")
    verify(arguments.wheel, arguments.bundle)
