# Actual wheel release verification

The missing build prerequisite is resolved. The one requested CI snapshot showed
entrypoint code revision `ce13dceedbc513e47323ae7755357f8484075079` still queued
(run 37155153128); no CI wait or second status snapshot was performed.

A real wheel was built through normal PEP 517 tooling with the project's declared
`hatchling==1.32.0`, using the official `https://pypi.org/simple` registry and a
task-local cache. The wheel and its declared runtime dependencies were installed
in a new disposable task-local virtual environment. No project version or
requirement specification changed. No global install/configuration, credential
inspection, security change, model call, or benchmark occurred.

Artifact: `rob2_kit-0.11.0-py3-none-any.whl`, 399,495 bytes.
SHA-256: `0645bc339ebd5129827578ee9afe886a2ce21b7a975aa8133700e79fd254ce83`.
The retained binary is at
`/home/ali/Documents/Codex/2026-10-02/task-4/diagnostics/codex-integration-release/dist/rob2_kit-0.11.0-py3-none-any.whl`.

The disposable interpreter ran with `-I`; the checked module path proves it used
the installed wheel rather than checkout/PYTHONPATH imports. The archive passed
the project's wheel-content release verifier. Actual console stdio checks passed
for `rob2 mcp` and `rob2 mcp-codex`: full original receipt/schema metadata,
identical PNG/content blocks, matching PNG receipt hash, unchanged source/text
receipts, metadata-only structured receipt and input-error handling. The standard
mode retains output schema and structured content. The Codex mode omits the image
shortcut only for image-bearing output and preserves full schema in text/catalog
metadata. Packaged Codex/Claude launch commands and exact CLI skill export passed.
`verification.json` records 20 passing checks and installed versions;
`mcp-wire.json` and `mcp-codex-wire.json` preserve the actual installed receipts.

The offline verification harness initially omitted required `trial_id`; correcting
that call required no product change. Its next comparison took status before
`read_pages` in one mode and after in the other, so the ledger's genuine delivery
coverage differed. Equalizing observation order made the control pass. These
were test-harness failures; prior scratch workspaces and available traces remain
under `diagnostics/codex-integration-release`. No frozen smoke file was replaced.

The installed acceptance script is preserved as `verify_installed.py`, with
host-specific paths. Build/setup commands used `uv --no-config`, an explicit
public index, disabled keyring provider, and task-local cache/environment:

```sh
uv --no-config build --wheel --python /path/to/existing/python --no-python-downloads --default-index https://pypi.org/simple --keyring-provider disabled --cache-dir /task/cache --out-dir /task/dist
uv --no-config venv --python /path/to/existing/python --no-python-downloads /task/venv
uv --no-config pip install --python /task/venv/bin/python --default-index https://pypi.org/simple --keyring-provider disabled --cache-dir /task/cache /task/dist/rob2_kit-0.11.0-py3-none-any.whl
/task/venv/bin/python -I /task/verify_installed.py
```

No release blocker remains for these installed entrypoint checks. The earlier
native smoke establishes image transport on Codex 0.159.0; this offline release
check establishes packaging/runtime preservation. Neither establishes clinical
comprehension or accuracy, and the frozen strict observation score is unchanged.
