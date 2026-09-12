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
from mcp.types import TextContent

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
    if value["contract_version"] != "0.5.0":
        raise ValueError("public contract version differs")
    expected_order = [
        "prepare_batch",
        "get_status",
        "list_sources",
        "search_sources",
        "read_pages",
        "select_text_evidence",
        "render_page",
        "select_visual_evidence",
        "save_proposal",
        "request_proposal_approval",
        "get_domain_context",
        "save_domain_judgment",
        "request_trial_terminal",
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
    if value["resources"] != ["rob2://current-batch"] or value["resource_templates"] != []:
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
    """Check the live structured D3.1 premise boundary and provenance split."""

    if context.get("domain_id") != "domain:missing":
        raise ValueError("D3 acceptance context has the wrong Domain")
    questions = context.get("questions")
    if not isinstance(questions, list):
        raise ValueError("D3 acceptance context has no question cards")
    card = next(
        (
            item
            for item in questions
            if isinstance(item, dict) and item.get("id") == "sq:missing:data-available"
        ),
        None,
    )
    if not isinstance(card, dict):
        raise ValueError("D3.1 question card is missing")

    if card.get("official_guidance") != (
        "‘Nearly all’ should be interpreted as that the number of participants with missing "
        "outcome data is sufficiently small that their outcomes, whatever they were, could "
        "have made no important difference to the estimated effect of intervention. For "
        "continuous outcomes, availability of data from 95% of the participants will often be "
        "sufficient. Note that imputed data should be regarded as missing data."
    ):
        raise ValueError("D3.1 official guidance projection differs")
    if card.get("source_locator") != "Full guidance p. 45, Box 8, signalling question 3.1":
        raise ValueError("D3.1 official locator projection differs")

    evidence_needed = card.get("evidence_needed")
    invalid_shortcuts = card.get("invalid_shortcuts")
    considerations = card.get("considerations")
    if not all(
        isinstance(value, list) for value in (evidence_needed, invalid_shortcuts, considerations)
    ):
        raise ValueError("D3.1 structured guidance fields are not lists")
    evidence_text = " ".join(str(item) for item in evidence_needed).casefold()
    if not all(
        marker in evidence_text
        for marker in (
            "yes or probably yes",
            "actual outcome-availability evidence",
            "observed-outcome counts",
            "loss-to-follow-up or censoring accounting",
            "complete/nearly-complete ascertainment",
        )
    ):
        raise ValueError("D3.1 affirmative availability evidence boundary is incomplete")
    shortcuts = [str(item).casefold() for item in invalid_shortcuts]

    def has_shortcut(*markers: str) -> bool:
        return any(all(marker in item for marker in markers) for item in shortcuts)

    if not all(
        (
            has_shortcut("analysis denominator", "itt membership"),
            has_shortcut("planned or scheduled follow-up"),
            has_shortcut("treatment continuation", "discontinuation"),
            has_shortcut("generic censoring rule", "actual rates", "follow-up accounting"),
        )
    ):
        raise ValueError("D3.1 non-entailing shortcut boundary is incomplete")
    consideration_text = " ".join(str(item) for item in considerations).casefold()
    if not all(
        marker in consideration_text for marker in ("administrative censoring", "missing follow-up")
    ):
        raise ValueError("D3.1 censoring distinction is missing")


def _verify_packaged_skill(skill: str, reference: str) -> None:
    """Check the portable skill's compact audit and co-located detail."""

    def section(text: str, heading: str, prefix: str) -> list[str]:
        lines = text.splitlines()
        start = lines.index(heading) + 1
        end = next(
            (index for index in range(start, len(lines)) if lines[index].startswith(prefix)),
            len(lines),
        )
        return lines[start:end]

    audit_lines = section(skill, "### 6. Audit and commit the Domain once", "### ")
    audit = " ".join(line.strip() for line in audit_lines).casefold()
    if audit.count("availability audit") != 1 or not all(
        marker in audit
        for marker in (
            "yes/probably yes needs actual outcome-availability evidence",
            "analysis membership",
            "planned or scheduled follow-up",
            "treatment continuation or discontinuation",
            "generic censoring rule alone do not suffice",
        )
    ):
        raise ValueError("packaged skill D3.1 availability audit is incomplete")

    audit_lines = section(reference, "## Availability audit", "## ")
    bullets: list[str] = []
    continuation = False
    for line in audit_lines:
        if line.startswith("- "):
            bullets.append(line.removeprefix("- ").strip())
            continuation = True
        elif not line.strip():
            continuation = False
        elif continuation:
            bullets[-1] = f"{bullets[-1]} {line.strip()}"
    normalized = [item.casefold() for item in bullets]
    if not all(
        any(all(marker in item for marker in markers) for item in normalized)
        for markers in (
            ("observed-outcome counts", "randomized"),
            ("loss-to-follow-up", "censoring", "accounting"),
            ("complete or nearly complete",),
            ("analysis denominators", "itt membership"),
            ("planned", "scheduled", "follow-up"),
            ("treatment continuation", "discontinuation"),
            ("generic censoring rule", "actual rates", "follow-up accounting"),
        )
    ):
        raise ValueError("packaged missing-data reference availability audit is incomplete")


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
        text = [item.text for item in result.content if isinstance(item, TextContent)]
        if len(text) != 1 or json.loads(text[0]) != value:
            raise ValueError(f"{name} text and structured content differ")
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


def _acceptance_result(_evidence: dict[str, Any]) -> dict[str, Any]:
    """Build a deliberately small, fully Evidence-bound acceptance Result."""

    phrase = "requested outcome"
    return {
        "kind": "assessable",
        "trial_id": "trial",
        "relation": "exact",
        "applicability": {
            "design": "individual_parallel",
            "rationale": "The fixture represents an individually randomized parallel trial.",
            "evidence": [_evidence["handle"]],
        },
        "target": {
            "measurement": {"method": phrase},
            "time_point_or_window": {"kind": "described", "description": phrase},
            "comparison_groups": [
                {"id": "a", "assignment": phrase},
                {"id": "b", "assignment": phrase},
            ],
            "baseline_subgroup": None,
            "intended_effect_measure": phrase,
        },
        "reported": {
            "form": "group_bound_values",
            "analysis_population": phrase,
            "endpoint": {"name": phrase, "definition": phrase},
            "values": [
                {"group_id": "a", "statistic": phrase, "value": phrase, "unit": phrase},
                {"group_id": "b", "statistic": phrase, "value": phrase, "unit": phrase},
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
    proposed = await _call(
        client,
        "save_proposal",
        {"results": [result], "expected_revision": prepared["state_revision"]},
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
        if not isinstance(question, dict) or (question_ids is None and not question.get("active")):
            continue
        if question_ids is not None and question.get("id") not in question_ids:
            continue
        options = question.get("options", [])
        if not isinstance(options, list):
            raise ValueError("acceptance Domain question options are malformed")
        selected = next(
            (
                option
                for option in options
                if isinstance(option, dict) and option.get("official_answer") == "no_information"
            ),
            next(
                (
                    option
                    for option in options
                    if isinstance(option, dict) and option.get("official_answer") == "probably_no"
                ),
                None,
            ),
        )
        if not isinstance(selected, dict) or not isinstance(selected.get("id"), str):
            raise ValueError("acceptance Domain question has no usable uncertainty option")
        answer = selected["official_answer"]
        basis = (
            {
                "kind": "limitation",
                "text": "The release acceptance source does not report this fact.",
                "search_receipt": search_receipt,
            }
            if answer == "no_information"
            else {
                "kind": "direct_support",
                "evidence": evidence["handle"],
            }
        )
        answers.append(
            {"question_id": question["id"], "option_id": selected["id"], "bases": [basis]}
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
    expected_action = {
        "kind": "refine",
        "operation": "search_sources",
        "trial_id": "trial",
        "query": "release acceptance eligible lexical",
        "mode": "any",
        "source_id": source_id,
        "limit": 2,
        "cursor": None,
    }
    if (
        not isinstance(diagnostic, dict)
        or diagnostic.get("code") != "narrow_no_hits"
        or diagnostic.get("next_action") != expected_action
    ):
        raise ValueError(f"acceptance narrow-search diagnostic differs: {diagnostic}")
    widened = await _call(
        client,
        "search_sources",
        {key: value for key, value in expected_action.items() if key not in {"kind", "operation"}},
    )
    if (
        widened.get("outcome") != "success"
        or widened.get("mode") != "any"
        or not isinstance(widened.get("search_receipt"), str)
    ):
        raise ValueError(f"acceptance narrow-search action execution differs: {widened}")
    for domain_id in domains:
        context = await _call(
            client,
            "get_domain_context",
            {"trial_id": "trial", "domain_id": domain_id, "page_size": 131_072},
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
            if payload.get("mcp_command") != "rob2 mcp" or payload.get("skills") != ["rob2-assess"]:
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
                        "page_size": 131_072,
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
                if status.get("phase") != "ready_to_finalize":
                    raise ValueError("wheel process restart did not reach finalization")
                finalized = await _call(
                    client, "finalize_batch", {"expected_revision": status["state_revision"]}
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
