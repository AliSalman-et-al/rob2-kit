# Issue #193 installed-host acceptance evidence

Status: partial (2026-08-14).

The production wheel was built from `95d626ab5267dcf7935f3bae269811f5f3a6ea4b`
and installed into an isolated virtual environment.  Its installed package contained
the two host manifests and exactly these portable skill directories:
`rob2-workflow` and `rob2-signalling`.

## Isolation

All product configuration, wheel, virtual environment, workspace, skills, and
transcripts used a fresh `%TEMP%\\rob2-acceptance-<id>` root.  No credentials were
copied or read.  Codex authentication necessarily remained in its existing home;
the invocation used `--ignore-user-config --ephemeral`.  Claude used its existing
login only, with `--strict-mcp-config`, a transient plugin directory, and an
explicit transient MCP JSON configuration.

The non-secret Claude settings file SHA-256 was unchanged before and after:
`6BAA43F1A8D1FAC28CB5644A7EE8D36DEDF28290E602373704CB91BC1564BD38`.

The first Codex invocation modified its non-secret `config.toml` despite both
isolation switches.  A bounded retry took an exact byte backup first and restored
it in `finally`; its before/after SHA-256 values both were
`7091F3948E89BFF76BFD9222315A93C6935E3B71044E291B5985565804156202`.  No
authentication file was inspected or modified.

## Actual host results

The direct clean-wheel stdio initialize exchange succeeds for protocol versions
`2025-03-26` and `2025-11-25`, returning server `rob2-kit` / FastMCP `3.2.4`.
Nevertheless the actual Codex run closed during MCP initialization before it could
list tools or resources.  `codex mcp get` confirmed the explicit configuration:
the clean virtual-environment `rob2-mcp.exe`, no arguments, and the explicit
temporary `ROB2_WORKSPACE`.  Its credential-free transcript records repeated
`MCP startup failed: handshaking with MCP server failed: connection closed:
initialize response` errors.  Thus this is an installed Codex host-seam failure,
not a claim based on an in-process client test.

Two final Windows command-launch compatibility forms produced the identical real
Codex failure: (1) the clean venv `python.exe` with arguments `-m
rob2_kit.server`; and (2) `C:\\Windows\\System32\\cmd.exe /d /s /c` invoking the
same clean `rob2-mcp.exe`.  Each run captured Codex stderr and used a byte backup
and `finally` restore of non-secret `config.toml`; each restoration hash matched.
The host emitted no child-process stderr beyond its own handshake error.  There is
no #183 native-host command pattern recorded in this checkout to compare against.

The actual Claude run started the configured clean-wheel server, loaded both
transient plugin skills, and read concrete instances of all three resources:
current batch, randomization guidance, and an uncaptured registry record.  With
an explicit MCP allowlist it enumerated and could invoke all eleven named tools,
including `search_sources`; the first inventory response had been incomplete model
reporting, not a server-discovery failure.

No mixed-outcome workflow, resume, registry-unavailable, contradiction, or page
rendering acceptance is claimed because Codex cannot enter the server at all.

## Reproduction commands

Substitute `%ACCEPT_ROOT%` for the fresh temporary root:

```powershell
uv build --wheel --out-dir %ACCEPT_ROOT%\\wheel
uv venv %ACCEPT_ROOT%\\venv
uv pip install --python %ACCEPT_ROOT%\\venv\\Scripts\\python.exe %ACCEPT_ROOT%\\wheel\\rob2_kit-0.1.0-py3-none-any.whl
claude -p --strict-mcp-config --mcp-config %ACCEPT_ROOT%\\claude-project\\mcp.json --plugin-dir %ACCEPT_ROOT%\\claude-project\\plugin --permission-mode dontAsk --max-budget-usd 1 --output-format json "Discover the configured rob2 MCP inventory and call rob2://current-batch."
```
