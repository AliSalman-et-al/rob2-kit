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
    save_attempts: int = Field(ge=1)
    identical_rejections: int = Field(ge=2)
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
            + f". Stop after an accepted save, {self.save_attempts} total save attempts, "
            f"{self.identical_rejections} consecutive identical rejections "
            "or first observed guard. "
            f"At most {self.save_attempts - 1} model-owned construction corrections are allowed "
            "within these same "
            "guards; no new invocation or automatic retry. Use returned source recovery and "
            "preserve unresolved scientific premises. The launcher exposes rob2 tools directly "
            "with their complete typed inputs. Follow every returned Domain context and source "
            "reading continuation; an unavailable capture is not evidence of absence."
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
    saves: int,
    identical_rejections: int,
    wall_seconds: float,
    idle_seconds: float,
) -> str | None:
    checks = (
        (saves >= limits.save_attempts, "save attempt limit"),
        (identical_rejections >= limits.identical_rejections, "repeated identical rejection"),
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


def rejection_fingerprint(result: dict[str, Any]) -> str:
    """Compare validation defects, ignoring volatile receipt heads and syntax examples."""
    structured = result.get("structured_content") or {}
    repairs = structured.get("repairs")
    if repairs:
        defects = [
            {
                "code": row["code"],
                "path": row["path"],
                "active": (row.get("answer_path") or {}).get("active_question_ids"),
                "missing": (row.get("answer_path") or {}).get("missing_question_ids"),
                "detail": None if row.get("answer_path") else row["detail"],
            }
            for row in repairs
        ]
    else:
        text = "\n".join(item.get("text", "") for item in result.get("content", []))
        prefix = "invalid_tool_arguments: no assessment was submitted or saved. "
        if text.startswith(prefix):
            defects, _ = json.JSONDecoder().raw_decode(text[len(prefix) :])
        else:
            defects = [{"error": text or structured}]
    return hashlib.sha256(
        json.dumps(
            sorted(defects, key=lambda row: json.dumps(row, sort_keys=True)),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
