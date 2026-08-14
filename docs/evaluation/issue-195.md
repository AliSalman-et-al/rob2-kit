# Issue #195 release evaluation — blocked; do not cut over

Candidate: `greenfield-v0.1.0-rc2`, annotated tag peeled to commit
`4d8daeea0bb60429b2f3380ef67529875e02007e`.

## Environment and identity

| Item | Observed value |
| --- | --- |
| Operating system | Windows |
| Python | 3.13.13 |
| Codex CLI | 0.147.0 (requested Luna / medium; not executed) |
| Claude Code | 2.1.226 |
| Requested host/model/effort | Claude Code / Sonnet / medium |
| Wheel SHA-256 | `c8eb9d47a202acaf382b28bd5af98ea8d4538552dbd821ec7a57f338159bfa4f` |
| Wheel/package identity | `rob2-kit` 0.1.0, `py3-none-any` |
| Scientific pack | `rob2.parallel.assignment` 2019.1, `sha256:42acdc84ee422ea142cf661d22d1075ec0ef376f37e401080d3f728ae31e5267` |
| Policy pack | `rob2-kit.retrieval-policy` 1.0.0, `sha256:45baf929bc557ec14b2a44584bee1b418198ef6fd743d47a37d8dfcebd9fd697` |

The candidate was cloned into an OS temporary root outside both repositories and
the private reference corpus. A wheel was built there and installed into a fresh
host environment. `docs/release/verify.py --wheel` passed before host evaluation.
Three independent blinded workspaces were prepared for the required PFS cases.
No source was opened, ingested, or rendered, and no provisional label was read.

## Host result

The #193 waiver permitted advancing the candidate through #194 despite the known
Codex-on-Windows limitation. It does **not** substitute the Codex evaluation
required by #195, nor does it waive #195's blinded scientific evaluation or
public scenarios. Codex CLI 0.147.0 with Luna at medium effort was not retried.

Claude Code was started with a strict one-shot MCP configuration pointing at the
`rob2-mcp` executable from the fresh wheel environment.

| Scenario | Result | Notes |
| --- | --- | --- |
| Claude project-skill + strict-MCP allowlisted handshake | blocked | Installed-wheel skills were copied to the project `.claude/skills` directory. An initial `--tools` restriction was incorrect for MCP permissions and exposed only a file-read tool; the corrected `--allowedTools` probe still exposed no `rob2-kit` tool. |
| Claude native project-MCP handshake | blocked | Claude's project-scoped MCP command generated a local `.mcp.json` with the installed executable and workspace environment, but its health remained `Pending approval`; the subsequent `dontAsk` session exposed only PubMed/file-read tools and could not call `list_sources`. |
| Claude local single-server approval handshake | blocked | Local Claude settings enabled only `rob2-kit` through `enabledMcpjsonServers`, but health remained `Pending approval`; the final `--allowedTools` probe still exposed no `rob2-kit` tool. |
| Claude always-load + explicit-settings handshake | blocked | The project server declared `alwaysLoad`; explicit settings enabled only `rob2-kit`, and tool search was disabled. Health remained `Pending approval` and the actual `list_sources` probe still had no such tool. |
| Claude local-scope JSON registration | blocked | The local-scope server registered, but health failed before a tool call with `CONNECTION_CLOSED: Connection closed`. |
| Claude strict transient eager-load configuration | blocked | The transient server declared `alwaysLoad`, tool search was disabled, and the exact `--allowedTools` list was supplied; the actual `list_sources` probe still had no `rob2-kit` tool. |
| Claude strict-MCP blinded CHAARTED PFS | blocked before ingestion | Three fresh attempts reported no `rob2-kit` tools in the assessment session. No source content was assessed and no provisional label was accessed. |
| Claude blinded STAMPEDE PFS | not started | Blocked by the same host seam. |
| Claude blinded TITAN PFS | not started | Blocked by the same host seam. |
| Claude public mixed-outcome scenario | not started | Blocked by the same host seam. |
| Claude restart/resume scenario | not started | Blocked by the same host seam. |

A short direct inventory probe reported the expected tool names, but actual
assessment sessions consistently lacked those tools. The project-skill,
`--setting-sources project`, strict-MCP, `dontAsk`, and the corrected exact
`--allowedTools` list did not expose a usable `rob2-kit` tool. This is
insufficiently reliable for a security-sensitive release evaluation and is
treated as a host integration failure, not as scientific evidence.

The final native project-MCP registration was also unavailable for use because
Claude Code retained a `Pending approval` health state in non-interactive mode.
The final corrected one-shot configuration used the official MCP permission form,
`--allowedTools`, rather than `--tools`; it still exposed no usable `rob2-kit`
tool. These conditions prevented the requested cheap real tool call before any
private source was opened.

As a final supported project-only mechanism, the temporary project added
`enabledMcpjsonServers` for `rob2-kit` in its local Claude settings. Health still
reported `Pending approval`, and the bounded `--allowedTools` probe exposed no
`rob2-kit` tool. No further host retries were performed.

The final configuration declared `alwaysLoad` for the project server, supplied
the same single-server approval through explicit Claude settings, and disabled
tool search so tools would load eagerly. It too remained `Pending approval` and
could not execute the no-source `list_sources` probe. No further host retries
were performed.

The final two noninteractive paths also failed. Local-scope JSON registration
returned `CONNECTION_CLOSED: Connection closed` during health checking. A separate
strict transient configuration with `alwaysLoad`, eager loading, and the official
exact allowlist exposed no `rob2-kit` tool to the actual no-source probe.

Recorded bounded Claude host diagnostics consumed USD 2.2958448 and 226.0
seconds in aggregate. The final strict transient probe consumed 7.3 seconds and
USD 0.304489; none reached source ingestion. Claude reported ordinary
service-tier usage and no usage-exhaustion signal. These are host diagnostics,
not assessment costs.

## Validation and recommendation

No Result, schema/hash, deterministic-judgment, citation, contradiction,
selective-rendering, recovery, HTML, tool-condition, latency, or usage validation
could be performed because no assessment reached ingestion. No discrepancy review
was performed because provisional labels remain unread.

**Release recommendation: DO NOT CUT OVER; #196 is blocked.** The three required
blinded scientific runs and the required public scenarios have not completed.
There are no scientific conclusions or discrepancy analyses. Private,
non-tracked diagnostics are retained outside the repository pending host-seam
investigation; this record deliberately excludes their path, diagnostic files,
source names, and source-derived material.

Before cleanup, the exact disposable target was validated as an OS-temporary
directory outside both repositories, the private reference corpus, and completed
outputs. A privacy-safe hash summary was retained in ignored evaluation storage.
The requested recursive removal was rejected by the execution policy, so the
validated temporary target remains retained privately; no protected path was
deleted.
