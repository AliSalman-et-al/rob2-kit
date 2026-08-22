"""Isolated host launcher with authoritative, contradiction-free status output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from . import launcher_legacy as _legacy
from .application.status import current_status
from .application.transport import actionable_json, sanitize_model_output
from .launcher_legacy import (
    EXIT_FINALIZED,
    EXIT_HOST_FAILURE,
    EXIT_PAUSED,
    EXIT_POSTFLIGHT_FAILURE,
    Host,
    LaunchResult,
    UnsupportedHostIsolation,
)


def launch_assessment(
    workspace: str | Path,
    host: Host,
    model: str | None,
    prompt: str,
    *,
    executable_env: dict[str, str] | None = None,
) -> LaunchResult:
    environment = dict(executable_env or {})
    environment.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
    environment.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
    result = _legacy.launch_assessment(
        workspace,
        host,
        model,
        prompt,
        executable_env=environment,
    )
    status = current_status(Path(workspace).resolve(strict=True))
    marker = "Verified rob2-kit status\n"
    model_output, separator, _old_status = result.output.partition(marker)
    if not separator:
        model_output = result.output
    model_output = model_output.rstrip("\n")
    sanitized = sanitize_model_output(model_output, cast(Any, status))
    block = marker + actionable_json(status)
    output = (
        sanitized.text
        + ("\n" if sanitized.text and not sanitized.text.endswith("\n") else "")
        + block
        + "\n"
    )
    if result.status_path.exists():
        try:
            payload = json.loads(result.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        payload["status"] = status.model_dump(mode="json", exclude_none=True)
        payload["suppressed_model_status_claims"] = list(sanitized.contradictions)
        result.status_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    return LaunchResult(
        result.exit_code,
        output,
        result.error,
        result.status_path,
    )


__all__ = [
    "EXIT_FINALIZED",
    "EXIT_HOST_FAILURE",
    "EXIT_PAUSED",
    "EXIT_POSTFLIGHT_FAILURE",
    "Host",
    "LaunchResult",
    "UnsupportedHostIsolation",
    "launch_assessment",
]