"""The Claude Code and Codex plugins must install the release they describe."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_plugins_track_the_package_release() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    claude = _json(".claude-plugin/plugin.json")
    codex = _json(".codex-plugin/plugin.json")
    assert claude["version"] == codex["version"] == version
    for manifest in (claude, codex):
        assert (ROOT / manifest["skills"] / "rob2-assess" / "SKILL.md").is_file()

    # Codex has no plugin-root variable, so it runs the tagged release; a
    # version bump must move that tag with it.
    server = _json(codex["mcpServers"])["mcpServers"]["rob2"]
    assert server["args"] == [
        "--from",
        f"git+https://github.com/AliSalman-et-al/rob2-kit@v{version}",
        "rob2",
        "mcp-codex",
    ]

    marketplace = _json(".claude-plugin/marketplace.json")
    assert [(item["name"], item["source"]) for item in marketplace["plugins"]] == [
        (claude["name"], "./")
    ]
