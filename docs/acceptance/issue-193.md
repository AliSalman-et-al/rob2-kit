# Issue #193 installed-host acceptance evidence

Status: waived for #194 release-candidate gating (2026-08-14).

The owner explicitly accepts the successful real-host Claude Code acceptance plus
the deterministic/raw-MCP verification as sufficient host proof for this release
candidate. This waiver does not reclassify the Windows Codex result as accepted:
Codex CLI 0.147.0 on Windows remains an unaccepted known limitation, documented
below. It is a release limitation rather than a runtime compatibility change or
an assertion that Codex has passed installed-host acceptance.

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

## Independent Codex reproduction (Luna Medium)

An independent credential-free reproduction at candidate HEAD `49f9221`
(`49f92219f2b5517bb26a3cff3c0b9a8253fd0f6e`) used Codex CLI `0.147.0`, model
`gpt-5.6-luna`, and medium reasoning.  It used a clean temporary wheel, virtual
environment, and workspace.  The packaged skills discovered from the wheel were
the canonical `rob2-workflow` and `rob2-signalling`; temporary working-copy names
used while preparing the reproduction are not discovery evidence.

Codex again failed before tool or resource discovery with the exact error:

```
MCP startup failed: handshaking with MCP server failed: connection closed: initialize response
```

The reproduction session ID was `019ffde8-45aa-7c30-9e7f-a97295e88d02`.
The non-secret Codex configuration SHA-256 was the same before and after the run:
`7091F3948E89BFF76BFD9222315A93C6935E3B71044E291B5985565804156202`.
No product processes remained afterward, and the repository was clean.

The candidate identity was exactly Git commit
`49f92219f2b5517bb26a3cff3c0b9a8253fd0f6e`; the installed product wheel was
built from that checkout. The temporary stdout/stderr transcript and result file
were not retained, so no artifact SHA-256 can be asserted retrospectively. The
commands below retain both and print their SHA-256 values, without copying,
reading, or naming authentication material.

This aligns with the reported Windows Python-stdio symptom in
[openai/codex#29247](https://github.com/openai/codex/issues/29247).  That report
is corroborating external evidence only; it does not establish an identical root
cause here.

This result is additional evidence for #193's installed-host acceptance record,
not completion of #193. The owner waiver at the top advances #194 despite this
Codex limitation; it does not waive later work or mark Codex accepted. WSL and
Docker were unavailable locally, and their installation was not authorized, so no
alternative host path was used. No runtime change or compatibility shim is
proposed by this record.

## Credential-free Codex Luna Medium reproduction

Set `$acceptRoot` to a newly created empty directory and run these commands from
the pinned checkout. The transient overlay is the complete non-secret MCP
configuration: its only environment value is the fresh workspace. No credentials
are copied or read. The command takes a byte-exact, uniquely named backup of the
non-secret Codex configuration and restores it in `finally` before comparing its
before/after SHA-256 values.

```powershell
$acceptRoot = 'C:\\Temp\\rob2-acceptance-193'
git rev-parse HEAD
git rev-parse --verify 49f92219f2b5517bb26a3cff3c0b9a8253fd0f6e
New-Item -ItemType Directory -Force "$acceptRoot\wheel", "$acceptRoot\workspace", "$acceptRoot\codex" | Out-Null
uv build --wheel --out-dir "$acceptRoot\wheel"
uv venv "$acceptRoot\venv"
uv pip install --python "$acceptRoot\venv\Scripts\python.exe" "$acceptRoot\wheel\rob2_kit-0.1.0-py3-none-any.whl"
$configPath = Join-Path $env:USERPROFILE '.codex\config.toml'
$configBackup = Join-Path $acceptRoot "codex\config.toml.$((New-Guid).Guid).backup"
Copy-Item -LiteralPath $configPath -Destination $configBackup -ErrorAction Stop
$configBeforeHash = (Get-FileHash -LiteralPath $configBackup -Algorithm SHA256).Hash
try {
    codex exec --ignore-user-config --ephemeral --skip-git-repo-check --cd "$acceptRoot\workspace" --model gpt-5.6-luna -c model_reasoning_effort='medium' -c "mcp_servers.rob2.command='$acceptRoot\venv\Scripts\rob2-mcp.exe'" -c "mcp_servers.rob2.env.ROB2_WORKSPACE='$acceptRoot\workspace'" --json "List the configured rob2 MCP tools and resources, then call rob2://current-batch." 1> "$acceptRoot\codex\result.jsonl" 2> "$acceptRoot\codex\stderr.txt"
} finally {
    Copy-Item -LiteralPath $configBackup -Destination $configPath -Force -ErrorAction Stop
    $configAfterHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
    if ($configBeforeHash -ne $configAfterHash) { throw 'Codex configuration restoration hash differs' }
}
Get-FileHash -Algorithm SHA256 "$acceptRoot\codex\result.jsonl", "$acceptRoot\codex\stderr.txt"
```
