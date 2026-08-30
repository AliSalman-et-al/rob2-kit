"""CLI adapter for the v0.3 ledger and researcher review boundary."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from rob2_kit.application._state import _root, _state
from rob2_kit.application.finalization import finalize_batch, verify_bundle
from rob2_kit.application.intake import approve_review, discard_workspace
from rob2_kit.application.source_archive import archive_sources, verify_source_archive
from rob2_kit.application.status import get_status


def _answer(prompt: str) -> str:
    """Read one researcher answer as bytes so a piped byte order mark cannot corrupt it."""
    print(prompt, end="", flush=True)
    return sys.stdin.buffer.readline().decode("utf-8-sig", "replace").rstrip("\r\n").casefold()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rob2",
        description="RoB 2 workflow and finalized-bundle tools.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "status",
            "review",
            "finalize",
            "verify",
            "archive-sources",
            "verify-sources",
            "export-skill",
            "discard",
            "mcp",
        ),
        default="status",
    )
    parser.add_argument(
        "bundle",
        nargs="?",
        help="path to a finalized .rob2.zip bundle (required by verify)",
    )
    parser.add_argument("--workspace", default=os.environ.get("ROB2_WORKSPACE", "."))
    parser.add_argument(
        "--output",
        help=("destination for archive-sources or the rob2-assess directory for export-skill"),
    )
    args = parser.parse_args(argv)
    if args.command == "mcp":
        from rob2_kit.interfaces.mcp.server import main as run_mcp

        run_mcp()
        return 0
    if args.command == "review":
        status = get_status(args.workspace)
        continuation = status.get("continuation")
        if (
            not isinstance(continuation, dict)
            or continuation.get("operation") != "researcher_review"
        ):
            print(json.dumps(status, sort_keys=True))
            return 0
        review = _state(_root(args.workspace)).get("review")
        if not isinstance(review, dict):
            raise ValueError("review state is corrupt")
        # The CLI is the researcher-authority seam.  Display the whole exact
        # candidate before accepting an acknowledgment reference.
        print(json.dumps(review, sort_keys=True, indent=2))
        answer = _answer(
            "Acknowledge this exact Review record as researcher? "
            "[yes/no; ask the model to choose another candidate before approval] "
        )
        if answer != "yes":
            print(f"not acknowledged: {answer!r}", file=sys.stderr)
            return 1
        print(json.dumps(approve_review(args.workspace, str(review["identity"])), sort_keys=True))
        return 0
    if args.command == "finalize":
        status = get_status(args.workspace)
        print(
            json.dumps(
                finalize_batch(args.workspace, int(status["state_revision"])), sort_keys=True
            )
        )
        return 0
    if args.command == "discard":
        print(json.dumps(discard_workspace(args.workspace), sort_keys=True))
        return 0
    if args.command == "verify":
        if args.bundle is None:
            parser.error("verify requires a finalized .rob2.zip bundle path")
        if verify_bundle(args.bundle):
            print(f"verified: {args.bundle}")
            return 0
        print(f"verification failed: {args.bundle}", file=sys.stderr)
        return 1
    if args.command == "archive-sources":
        print(json.dumps(archive_sources(args.workspace, args.output), sort_keys=True))
        return 0
    if args.command == "verify-sources":
        if args.bundle is None:
            parser.error("verify-sources requires a source archive path")
        if verify_source_archive(args.bundle):
            print(f"verified: {args.bundle}")
            return 0
        print(f"verification failed: {args.bundle}", file=sys.stderr)
        return 1
    if args.command == "export-skill":
        if args.output is None:
            parser.error("export-skill requires --output")
        source = Path(__file__).resolve().parents[2] / "skills" / "rob2-assess"
        destination = Path(args.output).resolve()
        shutil.copytree(source, destination, dirs_exist_ok=True)
        print(destination)
        return 0
    print(json.dumps(get_status(args.workspace), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
