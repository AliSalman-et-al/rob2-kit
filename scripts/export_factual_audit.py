"""Opt-in source-check preparation and advisory validation; no implicit model call.

Reuses current selected-Trial review and immutable bundle projection. The original
assessor alone can change a Domain through the existing canonical submission path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from rob2_kit.application._state import _identity, _root, _state
from rob2_kit.application.evidence import _render_page_png
from rob2_kit.application.source_check import (
    INSTRUCTION,
    SourceCheckReport,
    build_packet,
    export_current_packet,
    validate_report,
)
from scripts.verify_bundle import verify

READ_TOOLS = ("list_sources", "read_pages", "search_sources", "search_sources_batch", "render_page")


def export_packet(bundle: Path, trial_id: str, domain_id: str) -> dict[str, Any]:
    valid, message = verify(bundle)
    if not valid:
        raise ValueError(f"Bundle verification failed: {message}")
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        evidence = {
            record["identity"]: record
            for name in archive.namelist()
            if name.startswith("evidence/")
            for record in [json.loads(archive.read(name))]
        }
    domain = canonical["domain_records"].get(f"{trial_id}:{domain_id}")
    if not isinstance(domain, dict):
        raise ValueError("No saved domain for the requested Trial and Domain")
    sources = {
        source["id"]: source
        for trial in canonical["batch"]["trials"]
        if trial["id"] == trial_id
        for source in trial["sources"]
    }
    result = next(
        result
        for result in canonical["proposal"]["payload"]["results"]
        if result["trial_id"] == trial_id
    )
    return build_packet(result, [domain], evidence, sources, trial_id)


def prepare_native_review(
    workspace: Path,
    trial_id: str,
    domain_id: str | None,
    output: Path,
    *,
    assessor_model: str,
    assessor_effort: str,
    reviewer_model: str,
    reviewer_effort: str,
) -> dict[str, Any]:
    """Freeze a fresh Codex request using native exec, existing MCP and output schema.

    Does not launch or authenticate. An explicitly authorized diagnostic launcher
    must use launch_checked and record effective model/settings and native events.
    """
    packet = export_current_packet(workspace, trial_id, domain_id)
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "packet.json", packet)
    _write(output / "response-schema.json", SourceCheckReport.model_json_schema())
    (output / "instructions.md").write_text(INSTRUCTION, encoding="utf-8")
    images = []
    for span in packet["cited_spans"]:
        if span["kind"] != "figure":
            continue
        # Verification already checked the original receipt, captured source and
        # canonical pixels. CLI image arguments deliver those same full-page bytes;
        # the model must use the cited normalized region within each page.
        from rob2_kit.application.source_handles import resolve_source_handle

        source_id = resolve_source_handle(workspace, trial_id, span["source_id"])
        pixels = _render_page_png(
            _root(workspace), trial_id, source_id, span["render"]["page"], count=False
        )
        digest = hashlib.sha256(pixels).hexdigest()
        if "sha256:" + digest != span["render"]["png_sha256"]:
            raise ValueError("Review image differs from original captured pixels")
        path = output / (digest + ".png")
        path.write_bytes(pixels)
        images.append(
            {
                "evidence_identity": span["evidence_identity"],
                "path": str(path.resolve()),
                "png_sha256": digest,
                "region": span["region"],
                "transport": "native Codex --image; not a new MCP delivery receipt",
            }
        )
    image_order = "\n".join(
        f"Attached image {index}: Evidence {image['evidence_identity']}; "
        f"use normalized region {image['region']}."
        for index, image in enumerate(images, 1)
    )
    prompt = json.dumps(packet, ensure_ascii=False, indent=2) + "\n" + image_order + "\n"
    (output / "prompt.txt").write_text(prompt, encoding="utf-8")
    config: dict[str, Any] = {
        "model_reasoning_effort": reviewer_effort,
        "model_instructions_file": str((output / "instructions.md").resolve()),
        "web_search": "disabled",
        "features.shell_tool": False,
        "features.unified_exec": False,
        "features.view_image": False,
        "features.apps": False,
        "features.plugins": False,
        "features.skill_search": False,
        "features.skip_host_skill_discovery": True,
        "features.multi_agent": False,
        "features.multi_agent_v2": False,
        "features.browser_use": False,
        "features.computer_use": False,
        "features.code_mode.enabled": True,
        "features.code_mode.direct_only_tool_namespaces": ["mcp__rob2"],
        "mcp_servers.rob2.command": sys.executable,
        "mcp_servers.rob2.args": ["-m", "rob2_kit.interfaces.cli.app", "mcp-codex"],
        "mcp_servers.rob2.required": True,
        "mcp_servers.rob2.default_tools_approval_mode": "approve",
        "mcp_servers.rob2.enabled_tools": list(READ_TOOLS),
        "mcp_servers.rob2.env.ROB2_WORKSPACE": str(workspace.resolve()),
        "mcp_servers.rob2.env.PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    command = [
        "codex",
        "exec",
        "--strict-config",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "-m",
        reviewer_model,
    ]
    for key, value in config.items():
        command += ["-c", key + "=" + json.dumps(value, separators=(",", ":"))]
    for image in images:
        command += ["--image", image["path"]]
    command += [
        "--output-schema",
        str((output / "response-schema.json").resolve()),
        "--json",
        "-o",
        str((output / "response.json").resolve()),
        "-",
    ]
    state = _state(_root(workspace))
    routing = [
        {
            "claim_id": _identity(
                {"checkpoint": record["identity"], "question": answer["question_id"]}
            ),
            "domain_id": record["domain_id"],
            "question_id": answer["question_id"],
            "checkpoint_identity": record["identity"],
        }
        for record in state["domain_records"].values()
        if record["identity"] in packet["checkpoint_identities"]
        for answer in record["answers"]
    ]
    manifest = {
        "assessor_routing_not_model_input": routing,
        "snapshot_identity": packet["snapshot_identity"],
        "assessor": {
            "model": assessor_model,
            "effort": assessor_effort,
            "role": "scientific decision authority; declared provenance",
        },
        "reviewer": {
            "model": reviewer_model,
            "effort": reviewer_effort,
            "role": "advisory source checker; effective settings must be verified at launch",
        },
        "fresh_exec": True,
        "resume": False,
        "allowed_tools": list(READ_TOOLS),
        "images": images,
        "command": command,
        "files_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output.iterdir()
            if path.is_file()
        },
        "model_calls": 0,
        "launch_protocol": "Explicit authorization only. Reuse diagnostic_evidence_preflight."
        "launch_checked and run_rsi_case._run_owned_codex for bounded native "
        "execution; freeze research criteria/availability manifest first. "
        "Preserve events, effective model, usage, stderr and protected hashes. "
        "No retry or canonical tool is part of this request.",
    }
    _write(output / "request.json", manifest)
    return manifest


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="immutable bundle or current workspace")
    parser.add_argument("trial_id")
    parser.add_argument("domain_id", nargs="?")
    parser.add_argument("--prepare", type=Path, help="new native request directory; no model call")
    parser.add_argument("--assessor-model")
    parser.add_argument("--assessor-effort")
    parser.add_argument("--reviewer-model")
    parser.add_argument("--reviewer-effort", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument(
        "--packet", type=Path, help="original frozen packet for advisory validation"
    )
    parser.add_argument(
        "--findings", type=Path, help="structured reviewer response; no application"
    )
    args = parser.parse_args()
    if args.findings:
        if args.packet is None:
            parser.error("--findings requires the exact original --packet")
        value = validate_report(
            args.input,
            json.loads(args.packet.read_text(encoding="utf-8")),
            SourceCheckReport.model_validate_json(args.findings.read_bytes()),
        )
    elif args.prepare:
        if not all(
            (args.assessor_model, args.assessor_effort, args.reviewer_model, args.reviewer_effort)
        ):
            parser.error("preparation requires explicit assessor and reviewer models/settings")
        value = prepare_native_review(
            args.input,
            args.trial_id,
            args.domain_id,
            args.prepare,
            assessor_model=args.assessor_model,
            assessor_effort=args.assessor_effort,
            reviewer_model=args.reviewer_model,
            reviewer_effort=args.reviewer_effort,
        )
    elif args.input.is_dir():
        value = export_current_packet(args.input, args.trial_id, args.domain_id)
    else:
        if args.domain_id is None:
            parser.error("bundle export requires a Domain selector")
        value = export_packet(args.input, args.trial_id, args.domain_id)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
