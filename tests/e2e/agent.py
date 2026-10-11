"""A scripted host driving the real `rob2 mcp` server over stdio.

It does what an assessing model does through the public tools only: it follows
the server's next actions, cites passages by literal quote, and supplies the
scientific choices a scenario gives it.
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.types import TextContent, TextResourceContents

REPO = Path(__file__).resolve().parents[2]


class Agent:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.trials: dict[str, dict[str, str]] = {}  # trial_id -> role -> source_id
        self.trial_id: str | None = None  # the Trial the next call concerns
        self.sources: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self._loop = asyncio.new_event_loop()
        if os.environ.get("ROB2_E2E_INPROCESS"):
            # Coverage measurement only: a stdio server is killed on disconnect and
            # never saves its data, so serve the same MCP app in this process.
            from rob2_kit.interfaces.mcp.server import mcp

            os.environ["ROB2_WORKSPACE"] = str(workspace)
            transport: Any = mcp
        else:
            transport = StdioTransport(
                command=sys.executable,
                args=["-m", "rob2_kit.interfaces.cli.app", "--workspace", str(workspace), "mcp"],
                env={
                    **os.environ,
                    "ROB2_WORKSPACE": str(workspace),
                    "FASTMCP_SHOW_CLI_BANNER": "false",
                    "FASTMCP_LOG_LEVEL": "WARNING",
                },
            )
        self._client = Client(transport)
        self._loop.run_until_complete(self._client.__aenter__())

    def close(self) -> None:
        self._loop.run_until_complete(self._client.__aexit__(None, None, None))
        del self._client
        gc.collect()
        self._loop.close()

    # -- transport -------------------------------------------------------------

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one tool; return its structured result, or {'error': text}."""
        arguments = arguments or {}
        result = self._loop.run_until_complete(
            self._client.call_tool(tool, arguments, raise_on_error=False)
        )
        text = " ".join(item.text for item in result.content if isinstance(item, TextContent))
        value = {"error": text} if result.is_error else dict(result.structured_content or {})
        self.calls.append((tool, arguments, value))
        return value

    def resource(self, uri: str) -> dict[str, Any]:
        contents = self._loop.run_until_complete(self._client.read_resource(uri))
        content = contents[0]
        assert isinstance(content, TextResourceContents)
        return json.loads(content.text)

    def ok(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        value = self.call(tool, arguments)
        assert value.get("outcome") == "success", (tool, value)
        return value

    def revision(self) -> int:
        return int(self.ok("get_status")["head"]["state_revision"])

    def next_action(self) -> dict[str, Any]:
        return self.ok("get_status")["head"]["next_action"]

    # -- workflow steps ----------------------------------------------------------

    def prepare(self, requested_outcome: str, **options: Any) -> dict[str, Any]:
        prepared = self.ok(
            "prepare_batch",
            {
                "requested_outcome": requested_outcome,
                "expected_revision": self.revision(),
                **options,
            },
        )
        self.trials = {
            trial["id"]: {source["role"]: source["id"] for source in trial["sources"]}
            for trial in prepared["data"]["trials"]
        }
        self.use(prepared["data"]["trials"][0]["id"])
        return prepared

    def use(self, trial_id: str) -> None:
        self.trial_id = trial_id
        self.sources = self.trials[trial_id]

    def read_required(self) -> None:
        """Read every window the server names before the next submission."""
        while (action := self.next_action())["operation"] == "read_pages":
            self.ok("read_pages", {"trial_id": action["trial_id"], "windows": action["windows"]})

    def read(self, role: str, pages: list[int]) -> dict[str, Any]:
        return self.ok(
            "read_pages",
            {"trial_id": self.trial_id, "source_id": self.sources[role], "pages": pages},
        )

    def cite(self, role: str, page: int, quote: str) -> str:
        selected = self.ok(
            "select_text_evidence",
            {
                "trial_id": self.trial_id,
                "source_id": self.sources[role],
                "page": page,
                "selected_text": quote,
            },
        )
        return selected["data"]["evidence"]["handle"]

    def cite_lines(self, role: str, page: int, first: str, last: str | None = None) -> str:
        """Cite the numbered lines spanning `first` through `last` (default: `first`).

        Phrases may cross line breaks, as they do in a PDF's text layer.
        """
        text = self.read(role, [page])["data"]["pages"][0]["numbered_text"]
        rows = [row.split("|", 1) for row in text.splitlines()]
        joined, starts = "", []
        for number, content in rows:
            starts.append((len(joined), int(number)))
            joined += content + " "

        def line_at(offset: int) -> int:
            return max(number for start, number in starts if start <= offset)

        begin = joined.index(first)
        end = joined.index(last or first, begin) + len(last or first) - 1
        selected = self.ok(
            "select_text_evidence",
            {
                "trial_id": self.trial_id,
                "source_id": self.sources[role],
                "page": page,
                "start_line": line_at(begin),
                "end_line": line_at(end),
            },
        )
        return selected["data"]["evidence"]["handle"]

    def propose(self, *selections: dict[str, Any]) -> dict[str, Any]:
        """Validate and save one selection per Trial (default: the current Trial)."""
        validated = self.call(
            "validate_proposal",
            {
                "selections": [{"trial_id": self.trial_id, **item} for item in selections],
                "expected_revision": self.revision(),
            },
        )
        if validated.get("outcome") != "success":
            return validated
        saved = self.call("save_proposal", validated["data"]["next_action"])
        assert saved.get("outcome") == "review_required", saved
        return saved

    def approve(self) -> None:
        """Ask for approval; the researcher then approves with `rob2 review`."""
        self.call("request_proposal_approval", {})
        reference = self.next_action()["reference"]
        reviewed = rob2(self.workspace, "review", "--review-reference", reference, input="yes\n")
        assert reviewed.returncode == 0, reviewed.stderr

    def context(self, domain_id: str | None = None) -> dict[str, Any]:
        """Drain every page of a Domain context and merge its sections."""
        arguments = {"domain_id": domain_id} if domain_id else {}
        page = self.ok("get_domain_context", arguments)
        merged = dict(page["data"])
        while (cursor := page["data"]["context_page"]["next_cursor"]) is not None:
            page = self.ok("get_domain_context", {"cursor": cursor})
            for key, value in page["data"].items():
                if isinstance(value, list):
                    merged[key] = [*merged.get(key, []), *value]
        merged["head"] = page["head"]
        return merged

    def save_domain(
        self, domain_id: str, answers: list[dict[str, Any]], **extra: Any
    ) -> dict[str, Any]:
        return self.call(
            "save_domain_judgment",
            {
                "trial_id": self.trial_id,
                "domain_id": domain_id,
                "expected_revision": self.revision(),
                "answers": answers,
                **extra,
            },
        )

    def close_trials(self) -> None:
        while (action := self.next_action())["operation"] in {"review_trial", "close_trial"}:
            if action["operation"] == "review_trial":
                self.ok(
                    "review_trial",
                    {
                        "trial_id": action["trial_id"],
                        "expected_revision": action["expected_revision"],
                    },
                )
            else:
                self.ok(
                    "close_trial",
                    {
                        "trial_id": action["trial_id"],
                        "expected_revision": action["expected_revision"],
                        "review_reference": action["review_reference"],
                    },
                )

    def finalize(self) -> dict[str, Any]:
        return self.ok("finalize_batch", {"expected_revision": self.revision()})


def answer(question_id: str, value: str, evidence: list[str], why: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "answer": value,
        "bases": [{"evidence": handle, "role": "direct_support"} for handle in evidence],
        "justification": why,
        "unknowns": [],
        "counterevidence": [],
    }


def rob2(workspace: Path, *args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
    if os.environ.get("ROB2_E2E_INPROCESS"):
        return _rob2_inprocess(workspace, args, input)
    return subprocess.run(
        [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "--workspace", str(workspace), *args],
        input=input,
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )


def _rob2_inprocess(
    workspace: Path, args: tuple[str, ...], input: str | None
) -> subprocess.CompletedProcess[str]:
    import contextlib
    import io

    from rob2_kit.interfaces.cli.app import main

    argv = ["--workspace", str(workspace), *args]
    stdout, stderr = io.StringIO(), io.StringIO()
    stdin = io.TextIOWrapper(io.BytesIO((input or "").encode("utf-8")))
    previous = sys.stdin
    sys.stdin = stdin
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = main(argv)
            except SystemExit as exit_:
                code = int(exit_.code or 0)
            except Exception as error:  # the subprocess would exit non-zero
                print(error, file=sys.stderr)
                code = 1
    finally:
        sys.stdin = previous
    return subprocess.CompletedProcess(argv, code, stdout.getvalue(), stderr.getvalue())
