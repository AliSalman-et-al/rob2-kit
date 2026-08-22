"""CLI adapter with compact verified finalization."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rob2_kit.application.archive import ArchiveArtifact, verify_archive
from rob2_kit.application.finalization import FinalizationResult, verify_finalization_result
from rob2_kit.application.finalization_runtime import finalize_with_archive

from . import app_legacy as _legacy


def _finalize(workspace: str | Path) -> int:
    result = finalize_with_archive(workspace)
    payload = (
        result.model_dump(mode="json", exclude_none=True)
        if hasattr(result, "model_dump")
        else result
    )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    if not isinstance(payload, dict) or payload.get("outcome") != "success":
        return 1
    canonical = FinalizationResult.model_validate(
        {key: payload[key] for key in FinalizationResult.model_fields}
    )
    compact = ArchiveArtifact.model_validate(payload["compact_archive"])
    return (
        0
        if verify_finalization_result(workspace, canonical) and verify_archive(workspace, compact)
        else 1
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default="status")
    parser.add_argument("--workspace", default=os.environ.get("ROB2_WORKSPACE", "."))
    known, _unknown = parser.parse_known_args(argv)
    if known.command == "finalize":
        return _finalize(known.workspace)
    return _legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
