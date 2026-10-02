"""One fixed, reviewed guard configuration for the isolated single-Domain probe."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProbeLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    wall_seconds: int = Field(ge=1)
    idle_seconds: int = Field(ge=1)
    tool_calls: int = Field(ge=1)
    rejected_submissions: int = Field(ge=1)
    input_tokens: int = Field(ge=1)
    uncached_input_tokens: int = Field(ge=1)
    output_tokens: int = Field(ge=1)

    def identity(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )

    def prompt_suffix(self) -> str:
        return (
            "\n\nProbe guards (one invocation; reactive checks may overshoot within a generation): "
            + json.dumps(self.model_dump(), sort_keys=True)
            + ". Stop after an accepted save, the rejection limit or first observed guard. "
            "At most one model-owned construction correction is allowed within these same "
            "guards; no new invocation or automatic retry. Use returned source recovery and "
            "preserve unresolved scientific premises. If you need a tool signature, inspect "
            "only that tool's input declaration, omitting the Promise/output portion. Do not "
            "print the full tool catalog. The hosted nested answer schema has already been "
            "verified; no repeated schema demonstration is required. For large tool responses, "
            "set the code-mode output budget to retain all returned content, or request a "
            "smaller server page and follow its continuation. Do not treat clipped output as "
            "complete reading."
        )


def approved_limits() -> ProbeLimits:
    return ProbeLimits.model_validate_json(
        Path(__file__).with_name("domain_probe_limits.json").read_text()
    )


def write_controls(root: Path, manifest: dict[str, Any], task: str) -> None:
    """Write the manifest and prompt from the same reviewed guard values."""
    if any((root / name).exists() for name in ("manifest.json", "prompt.txt", "run.json")):
        raise ValueError("probe preparation must preserve existing controls and run records")
    limits = approved_limits()
    if "guards" in manifest and ProbeLimits.model_validate(manifest["guards"]) != limits:
        raise ValueError("requested guards differ from the reviewed probe configuration")
    prompt = task.rstrip() + limits.prompt_suffix()
    manifest = {
        **manifest,
        "guards": limits.model_dump(),
        "guard_identity": limits.identity(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (root / "prompt.txt").write_text(prompt)


def load_controls(root: Path) -> tuple[dict[str, Any], ProbeLimits, str]:
    """Reject control drift before the launcher creates a model process."""
    manifest = json.loads((root / "manifest.json").read_text())
    requested = ProbeLimits.model_validate(manifest["guards"])
    if requested != approved_limits() or manifest.get("guard_identity") != requested.identity():
        raise ValueError("manifest guards do not match the reviewed probe configuration")
    prompt = (root / "prompt.txt").read_text()
    if not prompt.endswith(requested.prompt_suffix()):
        raise ValueError("prompt guard section does not match the manifest")
    if hashlib.sha256(prompt.encode()).hexdigest() != manifest.get("prompt_sha256"):
        raise ValueError("prompt identity does not match the manifest")
    return manifest, requested, prompt


def guard_stop(
    limits: ProbeLimits,
    usage: Mapping[str, int],
    *,
    tools: int,
    rejections: int,
    wall_seconds: float,
    idle_seconds: float,
) -> str | None:
    checks = (
        (rejections >= limits.rejected_submissions, "rejected submission limit"),
        (tools >= limits.tool_calls, "tool limit"),
        (usage.get("input_tokens", 0) >= limits.input_tokens, "total input threshold"),
        (
            usage.get("input_tokens", 0) - usage.get("cached_input_tokens", 0)
            >= limits.uncached_input_tokens,
            "uncached input threshold",
        ),
        (usage.get("output_tokens", 0) >= limits.output_tokens, "output threshold"),
        (wall_seconds >= limits.wall_seconds, "wall threshold"),
        (idle_seconds >= limits.idle_seconds, "idle threshold"),
    )
    return next((reason for reached, reason in checks if reached), None)
