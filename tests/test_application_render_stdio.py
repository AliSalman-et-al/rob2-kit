from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import subprocess
from pathlib import Path

import pymupdf
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from rob2_kit.application.contracts import ReviewAuthority
from rob2_kit.application.intake import (
    CaptureRequest,
    IntakePlanEntry,
    SourceCriticality,
    SourceDisposition,
    acknowledge_intake,
    capture_batch,
    save_intake_plan,
)
from rob2_kit.application.preflight import AuthorizedSourceRoot, PreflightRequest, preflight_sources
from rob2_kit.rendering import read_render


def _workspace(tmp_path: Path) -> str:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "A persistent visual page")
    document.save(tmp_path / "main.pdf")
    document.close()
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(
            roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),),
        ),
        registry_request=lambda *_: {"status": "not_found"},
    )
    candidate = preflight.candidates[0]
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (
            IntakePlanEntry(
                candidate_identity=candidate.identity,
                role="main_article",
                disposition=SourceDisposition.INCLUDE,
                criticality=SourceCriticality.REQUIRED,
            ),
        ),
    )
    acknowledgment = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    receipt = capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledgment))
    assert receipt.captured_batch is not None
    return candidate.identity


def test_render_mcp_image_and_resource_are_the_same_persistent_png(tmp_path: Path) -> None:
    source_id = _workspace(tmp_path)
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(venv)], check=True, capture_output=True, text=True)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = next(wheel_dir.glob("*.whl"))
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    environment = os.environ.copy()
    environment["ROB2_WORKSPACE"] = str(tmp_path)

    async def exercise() -> tuple[str, bytes, bytes, dict[str, object]]:
        transport = StdioTransport(
            command=str(python),
            args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
            env=environment,
        )
        async with Client(transport) as client:
            result = await client.call_tool(
                "render_page",
                {
                    "trial_id": "trial",
                    "source_id": source_id,
                    "page": 1,
                    "region": [0.0, 0.0, 0.5, 0.5],
                },
            )
            image = result.content[0]
            link = result.content[1]
            resource = await client.read_resource(link.uri)
            return (
                str(link.uri),
                base64.b64decode(image.data),
                base64.b64decode(resource[0].blob),
                dict(result.structured_content or {}),
            )

    uri, inline, image, structured = asyncio.run(exercise())
    assert uri.startswith("rob2://render/sha256:")
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert inline == image
    assert hashlib.sha256(image).hexdigest()
    assert structured["region"] == [0.0, 0.0, 0.5, 0.5]
    assert "image_bytes" not in structured
    assert all("base64" not in str(value).casefold() for value in structured.values())
    identity = uri.rsplit("/", 1)[1]
    assert read_render(tmp_path, identity)[1] == image

    async def restart() -> bytes:
        transport = StdioTransport(
            command=str(python),
            args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
            env=environment,
        )
        async with Client(transport) as client:
            resource = await client.read_resource(uri)
            return base64.b64decode(resource[0].blob)

    assert asyncio.run(restart()) == image
    render_path = tmp_path / ".rob2-kit" / "renders" / f"{identity.removeprefix('sha256:')}.png"
    render_path.unlink()
    try:
        read_render(tmp_path, identity)
    except ValueError:
        pass
    else:
        raise AssertionError("missing render bytes must fail closed")
    render_path.write_bytes(image[:40] + bytes([image[40] ^ 1]) + image[41:])
    try:
        read_render(tmp_path, identity)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupt render bytes must fail closed")
    render_path.write_bytes(b"substituted")
    try:
        read_render(tmp_path, identity)
    except ValueError:
        pass
    else:
        raise AssertionError("substituted render bytes must fail closed")
