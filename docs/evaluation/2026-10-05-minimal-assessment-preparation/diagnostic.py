"""Isolated assessment-only diagnostic; no production registration or paid launcher."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pymupdf
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp.types import ImageContent, TextContent
from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.application._state import _identity
from rob2_kit.application.domains import (
    _DOMAIN_GUIDANCE,
    _DOMAIN_TRAPS,
    _RESPONSE_FRAMEWORK,
    _comparison_cards,
    _domain_question_cards,
    resolve_domain_sources,
)
from rob2_kit.application.evidence import _evidence_catalog
from rob2_kit.application.source_handles import public_source_references, source_handle
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.logic.evaluator import evaluate_domain, evaluate_overall
from rob2_kit.models import Answer
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import (
    DomainCounterpoint,
    DomainId,
    DomainSaveAnswer,
    DomainSourceReference,
    NonBlankText,
    QuestionId,
)
from scripts.diagnostic_evidence_preflight import check_manifest

CASE = "baillard-2006"
CODE = Path("/home/ali/Documents/Code/rob2-kit-benchmark")
RAW = CODE / "rob2-meta-set-full-2026-09-29/trials" / CASE
CAPTURE = CODE / "benchmark-luna6-medium-2026-10-01/cases" / CASE
SOURCE_TOOLS = {
    "list_sources": "List every captured trial Source and its immutable identity.",
    "search_sources": "Search captured source text; preserve source coordinates and cursors.",
    "search_sources_batch": "Run source-text searches with the declared modes.",
    "read_pages": "Read exact source page/line text; follow next_start_line to finish a page.",
    "render_page": "Render a captured trial PDF page as an image with its authentic receipt.",
    "select_text_evidence": "Select an exact inspected source text range as reusable Evidence.",
    "select_visual_evidence": "Record inspected image text using an authentic delivery receipt.",
    "render_guidance_page": "Inspect an original official guidance PDF page and table layout.",
}
GUIDANCE_PAGES = list(range(2, 34)) + list(range(39, 68))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question_id: QuestionId
    answer: Answer
    rationale: NonBlankText
    citations: list[DomainSourceReference]
    unknowns: list[NonBlankText]
    counterevidence: list[DomainCounterpoint]


class DomainAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    domain_id: DomainId
    answers: list[AnswerDraft] = Field(min_length=1)


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    result_identity: str
    domains: list[DomainAnswers] = Field(min_length=5, max_length=5)


class SourcesOnly(Middleware):
    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        return [
            tool.model_copy(update={"description": SOURCE_TOOLS[tool.name], "output_schema": None})
            for tool in tools
            if tool.name in SOURCE_TOOLS
        ]

    async def on_list_resources(self, context, call_next):
        return []

    async def on_list_resource_templates(self, context, call_next):
        return []

    async def on_read_resource(self, context, call_next):
        raise ToolError("Only diagnostic source tools are available")

    async def on_call_tool(self, context, call_next):
        if context.message.name not in SOURCE_TOOLS:
            raise ToolError("Only diagnostic source tools are available")
        result = await call_next(context)
        if result.is_error or context.message.name == "render_guidance_page":
            return result
        value = dict(result.structured_content or {})
        # Native handlers validate their complete receipt first. Retain all data,
        # source recovery, diagnostics and PNGs; omit only workflow head/next action.
        value.pop("head", None)
        value.pop("next_action", None)
        if any(block.type == "image" for block in result.content):
            # Match the existing Codex image adapter: JSON beside actual pixels,
            # without structured_content taking precedence over image delivery.
            return ToolResult(
                content=[TextContent(type="text", text=json.dumps(value)), *result.content],
                meta=result.meta,
            )
        return ToolResult(content=result.content, structured_content=value, meta=result.meta)


def configure(root: Path) -> None:
    os.environ["ROB2_WORKSPACE"] = str(root)

    @mcp.tool(name="render_guidance_page", output_schema=None)
    def render_guidance_page(page: int) -> ToolResult:
        if page not in GUIDANCE_PAGES:
            raise ToolError("Page is outside applicable assignment-effect guidance")
        with pymupdf.open(root.parent.parent / "official.pdf") as doc:
            png = doc[page - 1].get_pixmap(dpi=100).tobytes("png")
        return ToolResult(
            content=[
                ImageContent(
                    type="image", mime_type="image/png", data=base64.b64encode(png).decode()
                )
            ]
        )

    mcp.add_middleware(SourcesOnly())


async def call(client: Client, name: str, args: dict) -> dict:
    result = await client.call_tool(name, args)
    value = dict(result.structured_content or {})
    if value.get("outcome") != "success":
        raise ValueError(f"source call failed: {name}: {value}")
    return value


def approved_input() -> tuple[dict, dict]:
    # Read only proposal/batch/approval records, never historical Domain answers.
    with sqlite3.connect(f"file:{CAPTURE / '.rob2-kit/canonical.sqlite3'}?mode=ro", uri=True) as db:
        batch = json.loads(
            db.execute("SELECT payload FROM records WHERE name='batch'").fetchone()[0]
        )
        proposal = json.loads(
            db.execute("SELECT payload FROM records WHERE name='proposal'").fetchone()[0]
        )
        acknowledgments = [
            json.loads(row[0])
            for row in db.execute("SELECT payload FROM records WHERE name LIKE 'acknowledgment:%'")
        ]
    result = proposal["payload"]["results"][0]
    if len(proposal["payload"]["results"]) != 1 or not acknowledgments:
        raise ValueError("one approved captured Result is required")
    review = json.loads((CAPTURE / "review-fixed-1.json").read_text())
    if not any(ack["review_identity"] == review["identity"] for ack in acknowledgments):
        raise ValueError("original approval does not bind the captured review")
    if proposal["payload"] != review["candidate"]["proposal"]:
        raise ValueError("approved Proposal differs from captured candidate")
    return result, batch["trials"][0]


async def prepare(root: Path, official: Path) -> None:
    if root.exists():
        raise ValueError("fresh preparation directory required; preserve existing runs")
    root.mkdir(parents=True)
    result, original_trial = approved_input()
    write(root / "approved-result.json", result)
    shutil.copy2(official, root / "official.pdf")
    if (
        digest(official.read_bytes())
        != "a9e9c4fdc4be2d29b5c0a1a6b828e09f2014a34f6d5c302a532f6153ea0fd670"
    ):
        raise ValueError("official source identity differs")
    seed = root / "seed"
    shutil.copytree(RAW, seed / "input" / CASE)
    os.environ["ROB2_WORKSPACE"] = str(seed)
    async with Client(mcp) as client:
        await call(
            client,
            "prepare_batch",
            {
                "requested_outcome": result["requested_outcome"],
                "trial_labels": [CASE],
                "expected_revision": 0,
                "acquire_registry_documents": False,
            },
        )
        sources = (await call(client, "list_sources", {"trial_id": CASE}))["data"]["sources"]
        if {(s["sha256"], s["projection_hash"]) for s in sources} != {
            (s["sha256"], s["projection_hash"]) for s in original_trial["sources"]
        }:
            raise ValueError("all original Source identities/projections must match")
        # Recreate only approved Result citations, never Domain evidence/answers.
        review = json.loads((CAPTURE / "review-fixed-1.json").read_text())
        for evidence in review["candidate"]["evidence"].values():
            if evidence["kind"] != "narrative":
                raise ValueError("initial visual Result citation requires a reviewed pixel restore")
            selected = await call(
                client,
                "select_text_evidence",
                {
                    "trial_id": CASE,
                    "source_id": source_handle(evidence["source_id"]),
                    "page": evidence["page"],
                    "start_line": evidence["start_line"],
                    "end_line": evidence["end_line"],
                },
            )
            if selected["data"]["evidence"]["identity"] != evidence["identity"]:
                raise ValueError("approved Result citation identity differs")
        shutil.copytree(seed, root / "host-audit")
        os.environ["ROB2_WORKSPACE"] = str(root / "host-audit")
        windows = []
        supplied = []
        bundle = bytearray()
        images = []
        supplied_images = []
        for source in sources:
            for page in range(1, source["page_count"] + 1):
                start = 1
                parts = []
                while True:
                    value = await call(
                        client,
                        "read_pages",
                        {
                            "trial_id": CASE,
                            "source_id": source["id"],
                            "pages": [page],
                            "start_line": start,
                        },
                    )
                    row = value["data"]["pages"][0]
                    parts.append(row["numbered_text"])
                    if row.get("next_start_line") is None:
                        break
                    start = row["next_start_line"]
                text = "\n".join(parts).encode()
                a = len(bundle)
                bundle.extend(text)
                window = {
                    "source_identity": source["id"] + "@" + source["sha256"],
                    "page": page,
                    "start_line": 1,
                    "end_line": row["line_count"],
                }
                windows.append(window)
                supplied.append(
                    {
                        **window,
                        "input_start_byte": a,
                        "input_end_byte": len(bundle),
                        "text_sha256": digest(text),
                    }
                )
                rendered = await client.call_tool(
                    "render_page",
                    {
                        "trial_id": CASE,
                        "source_id": source["id"],
                        "page": page,
                    },
                )
                png = base64.b64decode(
                    next(block.data for block in rendered.content if block.type == "image")
                )
                start_byte = len(bundle)
                bundle.extend(png)
                frame = {
                    "source_identity": window["source_identity"],
                    "page": page,
                    "png_sha256": digest(png),
                    "width": int.from_bytes(png[16:20], "big"),
                    "height": int.from_bytes(png[20:24], "big"),
                }
                images.append(frame)
                supplied_images.append(
                    {**frame, "input_start_byte": start_byte, "input_end_byte": len(bundle)}
                )
    # Host preparation consumes only a separate seed. Both model workspaces are
    # fresh intake copies, with identical tools/coverage and no Domain history.
    (root / "evidence.bundle").write_bytes(bundle)
    write(root / "sources.json", sources)
    with pymupdf.open(official) as doc:
        official_text = "\n".join(
            f"OFFICIAL PRINTED PAGE {page}\n{doc[page - 1].get_text(sort=True)}"
            for page in GUIDANCE_PAGES
        )
    index = [
        {
            "domain_id": d.id,
            "questions": [
                {
                    "id": q.id,
                    "wording": q.wording,
                    "options": [a.value for a in q.allowed_answers],
                    "activation": q.activation.model_dump(mode="json"),
                }
                for q in SCIENTIFIC_PACK.questions
                if q.domain_id == d.id
            ],
        }
        for d in SCIENTIFIC_PACK.domains
    ]
    # Fresh question cards and comparisons have no saved answers, counts or branch.
    rich = [
        {
            "domain_id": d.id,
            "questions": _domain_question_cards(d.id, set(), None),
            "comparison_cards": _comparison_cards(
                d.id, result, review["candidate"]["evidence"], [], original_trial["sources"]
            ),
        }
        for d in SCIENTIFIC_PACK.domains
    ]
    rich = {
        "domains": rich,
        "guidance": _DOMAIN_GUIDANCE,
        "traps": _DOMAIN_TRAPS,
        "response_framework": _RESPONSE_FRAMEWORK.model_dump(mode="json"),
        "references": {
            name: (
                Path(__file__).resolve().parents[3]
                / "src/rob2_kit/skills/rob2-assess/references"
                / name
            ).read_text()
            for name in [
                "randomization.md",
                "deviations.md",
                "missing.md",
                "measurement.md",
                "selection.md",
            ]
        },
    }
    common = {
        "approved_result": result,
        "result_identity": _identity(result),
        "sources": sources,
        "result_evidence": public_source_references(review["candidate"]["evidence"]),
        "questions": index,
        "official_guidance": {
            "source_sha256": digest(official.read_bytes()),
            "version": "22 August 2019",
            "printed_pages": GUIDANCE_PAGES,
            "complete_applicable_text": official_text,
        },
    }
    write(root / "common.json", common)
    write(root / "rich-scaffolding.json", public_source_references(rich))
    write(root / "response-schema.json", Assessment.model_json_schema())
    generic = (
        "Assess all five RoB 2 Domains for the exact approved Result below. Use the available "
        "trial source tools and original official guidance, including page images where "
        "layout matters. Return only JSON matching the response schema: explicit active "
        "signalling answers, source-backed rationale, material unknowns and counterevidence. "
        "Labels are computed offline from answers; do not supply risk labels. No web or new "
        "sources.\n"
    )
    for arm in ["rich", "minimal"]:
        target = root / arm
        target.mkdir()
        shutil.copytree(seed, target / "workspace")
        prompt = generic + json.dumps(common, ensure_ascii=False) + "\n"
        if arm == "rich":
            prompt += (
                "ADDITIONAL CURRENT LOCAL SCIENTIFIC SCAFFOLDING\n"
                + json.dumps(public_source_references(rich), ensure_ascii=False)
                + "\n"
            )
        (target / "prompt.txt").write_text(prompt)
        manifest = {
            "research_question": (
                "Does adding current local scientific scaffolding harm or help source-grounded "
                "all-Domain interpretation on a shared assessment-only host?"
            ),
            "input_sha256": digest(prompt.encode()),
            "evidence_bundle_sha256": digest(bytes(bundle)),
            "required_windows": windows,
            "supplied_windows": supplied,
            "required_images": images,
            "supplied_images": supplied_images,
        }
        write(target / "evidence-manifest.json", manifest)
        write(
            target / "preflight.json",
            check_manifest(
                target / "evidence-manifest.json",
                target / "prompt.txt",
                evidence_bundle_path=root / "evidence.bundle",
            ),
        )
    write(
        root / "parity.json",
        {
            "case": CASE,
            "result_identity": _identity(result),
            "all_source_projections_match_original": True,
            "sources": len(sources),
            "all_pages": len(windows),
            "official_pages": GUIDANCE_PAGES,
            "common_payload_sha256": digest(json.dumps(common, sort_keys=True).encode()),
            "model": "gpt-6-luna",
            "reasoning_effort": "medium",
            "paid_calls": 0,
        },
    )


def validate(root: Path, response: Path, workspace: Path) -> dict:
    draft = Assessment.model_validate_json(response.read_bytes())
    result = json.loads((root / "approved-result.json").read_text())
    if draft.result_identity != _identity(result):
        raise ValueError("exact approved Result required")
    if {d.domain_id for d in draft.domains} != {d.id for d in SCIENTIFIC_PACK.domains}:
        raise ValueError("exactly five distinct Domains required")
    domains = {}
    resolved = {}
    for domain in draft.domains:
        if len({a.question_id for a in domain.answers}) != len(domain.answers):
            raise ValueError("duplicate question")
        allowed = next(d.question_ids for d in SCIENTIFIC_PACK.domains if d.id == domain.domain_id)
        if any(a.question_id not in allowed for a in domain.answers):
            raise ValueError("foreign Domain question")
        values = {a.question_id: a.answer for a in domain.answers}
        domains[domain.domain_id] = evaluate_domain(domain.domain_id, values).model_dump(
            mode="json"
        )
        answers = [
            DomainSaveAnswer(
                question_id=a.question_id,
                answer=a.answer,
                bases=tuple(a.citations),
                justification=a.rationale,
                unknowns=tuple(a.unknowns),
                counterevidence=tuple(a.counterevidence),
            )
            for a in domain.answers
        ]
        normalized = resolve_domain_sources(workspace, CASE, answers)
        resolved[domain.domain_id] = [a.model_dump(mode="json") for a in normalized]
    return {
        "diagnostic_only": True,
        "result_identity": draft.result_identity,
        "domains": domains,
        "overall_default": evaluate_overall(
            {k: v["judgment"] for k, v in domains.items()}
        ).model_dump(mode="json"),
        "resolved_answers": resolved,
        "selected_evidence": _evidence_catalog(workspace),
        "semantic_support_independently_verified": False,
    }


def usage(rows: list[dict]) -> dict:
    records = {}
    for row in rows:
        if row.get("type") != "token_usage_record":
            continue
        item = row["payload"]
        key = item["response_id"]
        if key in records and records[key]["usage"] != item["usage"]:
            raise ValueError("conflicting response usage")
        records[key] = item
    totals = {
        k: sum(r["usage"].get(k, 0) for r in records.values())
        for k in ["input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"]
    }
    completed = any(r.get("type") == "turn.completed" for r in rows) and not any(
        r.get("type") in {"error", "turn.failed"} for r in rows
    )
    return {
        "responses": len(records),
        "usage": totals,
        "uncached_input_tokens": totals["input_tokens"] - totals["cached_input_tokens"],
        "missing_usage": not bool(records),
        "completion_confirmed": completed,
        "unrecorded_pending_usage_unknown": not completed,
        "cost_usd": None,
        "observed_profiles": [
            {k: r["payload"].get(k) for k in ("model", "effort")}
            for r in rows
            if r.get("type") == "turn_context"
        ],
        "reasoning_is_subset_of_output": True,
    }


def plan(root: Path) -> dict:
    """Freeze an executable command/config plan, never start inference."""
    code = root / "code"
    code.mkdir()
    repo = Path(__file__).resolve().parents[3]
    archive = root / "runtime.tar"
    with archive.open("wb") as output:
        subprocess.run(
            ["git", "archive", "HEAD", "src", "scripts"], cwd=repo, stdout=output, check=True
        )
    with tarfile.open(archive) as files:
        files.extractall(code, filter="data")
    shutil.copy2(Path(__file__), root / "diagnostic.py")
    executable = Path("/home/ali/.nvm/versions/node/v24.21.0/bin/codex")
    version = subprocess.check_output([str(executable), "--version"], text=True).strip()
    help_text = subprocess.check_output([str(executable), "exec", "--help"], text=True)
    if "--output-schema" not in help_text:
        raise ValueError("launcher lacks structured response schema support")
    cache = json.loads((Path.home() / ".codex/models_cache.json").read_text())
    model = next(m for m in cache["models"] if m.get("slug") == "gpt-6-luna")
    if "medium" not in json.dumps(model.get("supported_reasoning_levels", [])):
        raise ValueError("exact Luna medium profile is not advertised")
    arms = {}
    for arm in ["rich", "minimal"]:
        directory = root / arm
        home = directory / "home"
        home.mkdir()
        server_args = [str(root / "diagnostic.py"), "serve", str(directory / "workspace")]
        config = (
            'model = "gpt-6-luna"\nmodel_reasoning_effort = "medium"\n'
            'approval_policy = "never"\nsandbox_mode = "read-only"\n'
            'web_search = "disabled"\n[mcp_servers.rob2]\n'
            f"command = {json.dumps(sys.executable)}\n"
            f"args = {json.dumps(server_args)}\n"
            'required = true\ndefault_tools_approval_mode = "approve"\n'
            "startup_timeout_sec = 120\ntool_timeout_sec = 180\n[mcp_servers.rob2.env]\n"
            f"PYTHONPATH = {json.dumps(str(code / 'src') + ':' + str(code))}\n"
        )
        (home / "config.toml").write_text(config)
        command = [
            str(executable),
            "exec",
            "--strict-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-s",
            "read-only",
            "-m",
            "gpt-6-luna",
            "-c",
            'model_reasoning_effort="medium"',
            "-c",
            "features.code_mode={enabled=false}",
            "--disable",
            "shell_tool",
            "--disable",
            "unified_exec",
            "--json",
            "--output-schema",
            str(root / "response-schema.json"),
            "-o",
            str(directory / "response.json"),
            "-",
        ]
        check_manifest(
            directory / "evidence-manifest.json",
            directory / "prompt.txt",
            evidence_bundle_path=root / "evidence.bundle",
        )
        arms[arm] = {
            "command": command,
            "cwd": str(directory / "workspace"),
            "CODEX_HOME": str(home),
            "config_sha256": digest(config.encode()),
            "prompt_sha256": digest((directory / "prompt.txt").read_bytes()),
        }
    return {
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "cli_version": version,
        "runtime_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "adapter_sha256": digest((root / "diagnostic.py").read_bytes()),
        "arms": arms,
        "inference_launched": False,
        "credentials_copied": False,
        "launch_requirement": "Future explicit authorization; use existing launch_checked "
        "with exact frozen prompt, evidence manifest/bundle, and recorded expected manifest hash.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "serve", "validate", "usage", "plan"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--official", type=Path)
    parser.add_argument("--response", type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        asyncio.run(prepare(args.root, args.official))
    elif args.mode == "serve":
        configure(args.root)
        mcp.run()
    elif args.mode == "plan":
        value = plan(args.root)
        write(args.root / "launch-plan.json", value)
        print(json.dumps(value))
    elif args.mode == "validate":
        print(json.dumps(validate(args.root, args.response, args.workspace)))
    else:
        print(
            json.dumps(
                usage([json.loads(line) for line in args.root.read_text().splitlines() if line])
            )
        )


if __name__ == "__main__":
    main()
