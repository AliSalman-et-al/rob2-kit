"""Operational references remain reachable without host filesystem tools."""

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastmcp import Client
from support.rob2 import _assessment_workspace

from rob2_kit.application._state import _state
from rob2_kit.application.guidance import _ROOT, read_guidance
from rob2_kit.interfaces.mcp.server import mcp


def test_native_tools_deliver_transitive_packaged_guidance_without_state_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
    before = _state(workspace)

    async def inspect() -> set[str]:
        pending = ["SKILL.md"]
        seen = set()
        async with Client(mcp) as client:
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


@pytest.mark.parametrize("document", ["../AGENTS.md", "/etc/passwd", "references/absent.md"])
def test_guidance_cannot_read_arbitrary_local_files(document: str) -> None:
    with pytest.raises(ValueError):
        read_guidance(document)


def test_conditional_guidance_preserves_exact_recovery_and_workflow(tmp_path, monkeypatch):
    workspace, _, _ = _assessment_workspace(tmp_path)
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
    before = _state(workspace)

    async def inspect():
        async with Client(mcp) as client:
            arguments = {"document": "references/selection.md"}
            full = (await client.call_tool("read_guidance", arguments)).structured_content
            assert full and full["outcome"] == "success"
            data = full["data"]
            conditional = (
                await client.call_tool(
                    "read_guidance",
                    {
                        **arguments,
                        "known_content_sha256": data["content_sha256"],
                    },
                )
            ).structured_content
            assert conditional and conditional["head"] == full["head"]
            assert conditional["data"] == {
                key: value for key, value in data.items() if key != "content"
            } | {"content_unchanged": True}
            recovered = (await client.call_tool("read_guidance", arguments)).structured_content
            assert recovered == full
            mismatch = (
                await client.call_tool(
                    "read_guidance",
                    {
                        **arguments,
                        "known_content_sha256": "sha256:" + "0" * 64,
                    },
                )
            ).structured_content
            assert mismatch == full
            resource = await client.read_resource("rob2://guidance/selection")
            assert resource[0].text == data["content"]

    asyncio.run(inspect())
    assert _state(workspace) == before


def test_conditional_guidance_delivers_changed_document(tmp_path, monkeypatch):
    import rob2_kit.application.guidance as guidance

    full = read_guidance("references/selection.md")
    root = tmp_path / "guidance"
    (root / "references").mkdir(parents=True)
    changed = full["content"] + "\nChanged packaged instruction.\n"
    (root / "references/selection.md").write_text(changed)
    monkeypatch.setattr(guidance, "_ROOT", root)
    result = read_guidance("references/selection.md", known_content_sha256=full["content_sha256"])
    assert result["content"] == changed
    assert result["content_sha256"] != full["content_sha256"]
    assert "content_unchanged" not in result
