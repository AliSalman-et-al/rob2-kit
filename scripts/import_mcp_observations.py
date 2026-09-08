"""Import Codex MCP JSONL transcripts into a privacy-safe observation artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rob2_kit.evaluation.observations import (
    ObservationImportError,
    dump_observations,
    import_observations,
    load_manifest,
)


def _transcript(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("transcripts must use TRANSCRIPT_ID=PATH")
    transcript_id, path = value.split("=", 1)
    if not transcript_id or not path:
        raise argparse.ArgumentTypeError("transcripts must use TRANSCRIPT_ID=PATH")
    return transcript_id, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import captured Codex MCP JSONL observations.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--transcript",
        "--transcripts",
        action="append",
        default=[],
        type=_transcript,
        metavar="ID=PATH",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        supplied: dict[str, bytes] = {}
        for identity, path in args.transcript:
            if identity in supplied:
                raise ObservationImportError("supplied transcript: duplicate identity")
            try:
                supplied[identity] = path.read_bytes()
            except OSError as error:
                raise ObservationImportError(
                    f"transcript {identity}: unable to read JSONL"
                ) from error
        artifact = import_observations(manifest, supplied or None)
        dump_observations(artifact, args.output)
    except (OSError, ObservationImportError) as error:
        print(f"import failed: {error}", file=sys.stderr)
        return 2
    print(
        f"imported {artifact['reconciliation']['workflow_attempts']} attempts, "
        f"{artifact['reconciliation']['mcp_calls']} MCP calls",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
