# Greenfield release contract

`release-manifest.json` is the sole machine-readable release contract. Its
verifier reads the installed package assets and production FastMCP object; it does
not duplicate RoB 2 logic, data models, or report behavior. Its non-self-
referential source contract hashes, in lexical POSIX-path order, each path followed
by a NUL byte and its canonical UTF-8 text bytes. Canonical text bytes replace
CRLF and CR line endings with LF; binary files are never normalized or included.
It includes `pyproject.toml`, `uv.lock`, every
`src/rob2_kit/**/*.py`, both host JSON files, and both portable skill files. The
manifest and verifier are deliberately excluded, so the contract can be checked
without a self-referential hash.

Run from a clean checkout after restoring the locked environment:

```powershell
uv sync --locked --all-groups
uv run python docs/release/verify.py
uv run ruff format --check src tests docs/release
uv run ruff check src tests docs/release
uv run ty check src tests docs/release
uv run pytest
uv build --wheel --out-dir dist
uv run python docs/release/verify.py --wheel dist/rob2_kit-0.1.0-py3-none-any.whl
```

RC2 is invalidated by safety commit `a394e853ddb3ea86a47599b56ab797b59b6df7bc`.
RC3 is released only from a clean commit that includes this manifest. The
implementation/base commits recorded in it identify the safety-fixed pre-manifest
lineage; the annotated `greenfield-v0.1.0-rc3` tag is the final candidate
identity. CI fetches that history to validate the ancestry contract, then
exercises Python 3.11--3.13 on Ubuntu, Windows, and macOS.

Issue #193 is waived only for this release gate: accepted Claude Code real-host
evidence plus the raw-MCP checks here are sufficient. Codex CLI 0.147.0 on
Windows remains an unaccepted known limitation; no compatibility shim is shipped.

Researcher inputs, completed outputs, and private evaluation material are outside
this checkout's replacement scope. Release scans must inspect their paths and
metadata only, never their contents.
