"""Read packaged operational guidance through clients without filesystem tools."""

import hashlib
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parents[1] / "skills" / "rob2-assess"


def read_guidance(document: str = "SKILL.md") -> dict[str, Any]:
    if not re.fullmatch(r"(?:SKILL\.md|references/[a-z][a-z0-9-]*\.md)", document):
        raise ValueError("Choose SKILL.md or a returned references/*.md guidance document")
    path = _ROOT / document
    if not path.is_file():
        available = [
            "SKILL.md",
            *sorted(
                candidate.relative_to(_ROOT).as_posix()
                for candidate in (_ROOT / "references").glob("*.md")
                if re.fullmatch(r"[a-z][a-z0-9-]*\.md", candidate.name)
            ),
        ]
        raise ValueError(
            "Packaged guidance document is unavailable. Available documents: "
            + ", ".join(available)
        )
    body = path.read_bytes()
    content = body.decode("utf-8")
    links = set()
    for target in re.findall(r"\]\(([^\s)]+)\)", content):
        target = target.split("#", 1)[0]
        if not target or ":" in target or not target.endswith(".md"):
            continue
        linked = (path.parent / target).resolve()
        if not linked.is_relative_to(_ROOT.resolve()):
            raise ValueError("Guidance link leaves the packaged skill")
        links.add(linked.relative_to(_ROOT.resolve()).as_posix())
    return {
        "outcome": "success",
        "document": document,
        "content": content,
        "content_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "links": sorted(links),
    }
