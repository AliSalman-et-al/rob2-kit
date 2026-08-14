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

Batch publication and finalization share rob2-kit's cooperative single-process
workspace-lock mutation boundary. A receipt authenticates the exact bundle bytes
captured at finalization, not a path forever: unsupported direct concurrent
filesystem edits are outside that contract, and later export or receipt reads
reject resulting bundle drift.

When a wheel is supplied, the verifier permits exactly the source-contract
`rob2_kit/**/*.py` modules, two host JSONs, two skill files, and the four declared
`.dist-info` members (`METADATA`, `WHEEL`, `entry_points.txt`, and `RECORD`). It
compares every module's canonical UTF-8 text bytes to the same source contract.
Every other member, including native code, bytecode, `.pth`, `.data`, or arbitrary
assets, fails. Archive names must also be unambiguous on Windows: duplicate or
case-aliased names, reserved device names, trailing dots or spaces, and alternate
data streams are rejected.
Host JSON rejects duplicate keys at every nesting level before its exact semantic
comparison. `WHEEL` must byte-match its frozen UTF-8 LF serialization: exactly
the four hatchling headers, in order, with no body or envelope. `METADATA` must
byte-match its frozen UTF-8 LF serialization: the ordered package headers and
three frozen `Requires-Dist` headers, one LF blank separator, then the canonical
UTF-8 text bytes of the root `README.md`. This rejects extra bytes, envelopes,
CRLF, reordered headers, and malformed pre-body lines. `entry_points.txt` accepts UTF-8 LF or CRLF only (normalized to LF)
and is limited to the exact case-sensitive three-line
`[console_scripts]\nrob2-mcp = rob2_kit.server:main\n` declaration.

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

RC2 was invalidated by safety commit `a394e853ddb3ea86a47599b56ab797b59b6df7bc`.
RC3 is invalidated because its verifier did not bind the wheel's Python modules to
the frozen source contract. RC4 is invalidated by the portable skill workflow
redesign. RC5 is invalidated by versioned pre-finish judgment corrections and
receipt-bound two-phase validation. The owner-scoped Claude Code Sonnet Low
CHAARTED overall-survival evaluation completed operationally and scientifically;
its privacy-safe evidence is in `docs/evaluation/issue-195.md`. The failed
performance target is tracked by #197 and is non-blocking for the owner-authorized
#196 cutover. `greenfield-v0.1.0-rc6` may be tagged only from the clean exact final
commit after this manifest commit, final review, and remote 3x3 CI. The
implementation/base commits identify the frozen implementation lineage; CI fetches
that history to validate the ancestry contract, then exercises Python 3.11--3.13
on Ubuntu, Windows, and macOS.

Issue #193 is waived only for this release gate: accepted Claude Code real-host
evidence plus the raw-MCP checks here are sufficient. Codex CLI 0.147.0 on
Windows remains an unaccepted known limitation; no compatibility shim is shipped.

Researcher inputs, completed outputs, and private evaluation material are outside
this checkout's replacement scope. Release scans must inspect their paths and
metadata only, never their contents.
