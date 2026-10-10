"""Operational references remain reachable without host filesystem tools."""

import asyncio
import hashlib
import re
from pathlib import Path

import pytest
from fastmcp import Client
from support.rob2 import _assessment_workspace

from rob2_kit.application._state import _state
from rob2_kit.application.guidance import _ROOT, read_guidance
from rob2_kit.application.status import get_status, get_status_head
from rob2_kit.interfaces.mcp.contracts import GuidanceData
from rob2_kit.interfaces.mcp.server import mcp


def test_native_tools_deliver_transitive_packaged_guidance_without_state_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
    before = _state(workspace)
    full_status, status_head = get_status(workspace), get_status_head(workspace)
    for field in ("state_revision", "phase", "continuation"):
        assert status_head[field] == full_status[field]
    assert "content" in GuidanceData.model_json_schema()["required"]

    async def inspect() -> set[str]:
        pending = ["SKILL.md"]
        seen = set()
        async with Client(mcp) as client:
            tool = next(tool for tool in await client.list_tools() if tool.name == "read_guidance")
            assert set(tool.input_schema["properties"]) == {"document"}
            while pending:
                document = pending.pop()
                if document in seen:
                    continue
                result = await client.call_tool("read_guidance", {"document": document})
                receipt = result.structured_content
                assert receipt and receipt["outcome"] == "success"
                data = receipt["data"]
                original = (_ROOT / document).read_bytes()
                assert data["content"].encode() == original
                assert data["content_sha256"] == "sha256:" + hashlib.sha256(original).hexdigest()
                name = "SKILL" if document == "SKILL.md" else Path(document).stem
                resource = await client.read_resource(f"rob2://guidance/{name}")
                assert resource[0].text.encode() == original
                seen.add(document)
                pending.extend(data["links"])
        return seen

    seen = asyncio.run(inspect())
    assert seen == {path.relative_to(_ROOT).as_posix() for path in _ROOT.rglob("*.md")}
    assert _state(workspace) == before


def test_guidance_links_resolve_to_packaged_headings() -> None:
    def slug(heading: str) -> str:
        return re.sub(r"[^a-z0-9 -]", "", heading.strip().lower()).replace(" ", "-")

    documents = {path: path.read_text(encoding="utf-8") for path in _ROOT.rglob("*.md")}
    headings = {
        path: {slug(match) for match in re.findall(r"^#+ (.+)$", text, re.MULTILINE)}
        for path, text in documents.items()
    }
    broken = []
    for path, text in documents.items():
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith("http"):
                continue
            name, _, anchor = target.partition("#")
            linked = (path.parent / name).resolve() if name else path
            if linked not in headings or (anchor and anchor not in headings[linked]):
                broken.append(f"{path.name}: {target}")
    assert broken == []


@pytest.mark.parametrize("document", ["../AGENTS.md", "/etc/passwd", "references/absent.md"])
def test_guidance_cannot_read_arbitrary_local_files(document: str) -> None:
    with pytest.raises(ValueError):
        read_guidance(document)


def test_unavailable_guidance_returns_exact_readable_packaged_paths() -> None:
    with pytest.raises(ValueError, match="Available documents:") as error:
        read_guidance("references/domain.md")
    documents = str(error.value).split("Available documents: ", 1)[1].split(", ")
    assert set(documents) == {path.relative_to(_ROOT).as_posix() for path in _ROOT.rglob("*.md")}
    assert all(read_guidance(document)["document"] == document for document in documents)
