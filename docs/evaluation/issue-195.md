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

After interactive workspace trust and single-server approval, the retained local
configuration was rechecked before any source access. It still reported
`CONNECTION_CLOSED: Connection closed`; consequently no zero-source probe or
scientific run was started, and no further configuration changes were made.

## Remediation after the release-safety defect

The `greenfield-v0.1.0-rc2` candidate is invalidated. It must not be tagged or
advanced: a host/model invoked `discard_active_batch` as error recovery despite
the workflow prohibition, which destroyed approved runtime state. The replacement
requires the current frozen-batch hash, an exact destructive confirmation literal,
actor, UTC observation time, and a nonblank researcher reason. Invalid requests
and stale identities must leave state unchanged, while the recoverable #192
discard path remains available only after an explicit researcher instruction in
the current conversation. These request fields make accidental invocation harder;
they do not prove that a human authored a request. Scientific-evaluation host
allowlists are intended to exclude discard entirely; only the separate public
recovery scenario may permit it.

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

## RC4 isolated re-evaluation — incomplete; do not cut over

Candidate: `greenfield-v0.1.0-rc4`, annotated tag peeled to
`71e681259c22b1a94c1401baab177d1ebdd42272`.

A fresh full-history temporary checkout passed the hardened source and wheel
verifier before the host run. The fresh wheel SHA-256 was
`bb6534c965072bdf6d507539b8ca3937a82d0216fca7d9daa58b1f2d180a5750`.
The candidate test suite passed (190 tests; one expected duplicate-archive
fixture warning). The initial shallow checkout was stopped before wheel creation:
the verifier correctly rejects it because the manifest's required ancestry is
unavailable.

Claude Code 2.1.226, Sonnet, medium, used a single strict MCP configuration
whose command resolved to the fresh-wheel executable and whose
`ROB2_WORKSPACE` exactly matched the single-run root. Its allowlist contained
the ten non-destructive MCP workflow tools and `ReadMcpResource`; it excluded
`discard_active_batch`. The zero-source handshake completed in 39.129 seconds at
USD 0.3017264, read the current-batch resource, and made one permitted
`list_sources` probe. The release verifier independently passed the complete
11-tool, 3-resource, 2-skill contract.

The first scientific invocation was externally terminated at 124.037 seconds.
That timeout was an evaluator-imposed process bound, not a Claude/MCP failure;
it emitted no receipt and left no workflow state or output. A one-time retry was
therefore allowed after verifying the same fresh run had zero state/output files.
It used Claude's `--max-budget-usd 12` and a 20-minute wall-clock cap. The retry
finished normally in 158.243 seconds at USD 0.5509289 (17 turns, zero permission
denials, empty stderr), with no workflow state or output written.

The retry confirmed a safe integration blocker rather than a disconnection:
the model could read the no-active current-batch resource and call the allowed
MCP tools, but the prompt supplied a manifest path while prohibiting filesystem
reads and did not supply the manifest's concrete primary-PDF path. The MCP API
cannot resolve that local manifest before ingestion. It correctly rejected a
manifest-as-PDF probe, did not guess a source path, and could not record a
`needs_input` terminal before approval. No evidence content or provisional label
was read, no proposal/batch/trial was created, and discard was not callable.

No further retry is authorized: the corrective action would be to supply the
concrete already-authorized primary-input path (or permit a bounded local manifest
read) in a new fresh run. The remaining two blinded trials, all frozen-artifact
checks and label comparison, and public mixed-terminal/restart scenarios remain
unperformed.

**RC4 recommendation: REJECT / DO NOT CUT OVER; #196 remains blocked.** This is
an operationally incomplete evaluation, not scientific evidence against a trial.

## RC5 Claude Sonnet Low CHAARTED restart evaluation

### Evaluation result

`greenfield-v0.1.0-rc5` (tag object `bbedf4ef03e96e4d3802d70a7fbb452e042ce667`,
peeled commit `7c4231ca50bb18c9cf63b6addeb99fcf87e8bbe3`) was built in a
fresh full-history detached checkout. Source and fresh-wheel verification passed.
The wheel SHA-256 was `d271d0ff7528a4726386f5df2a1a8f7f05fc167083165af4475835cd8c96bc0b`.

A fresh, nonce-scoped Claude Code 2.1.226 / Sonnet / low workspace passed a
zero-source attestation before blinded CHAARTED intake. The host completed a
blinded terminal assessment after a durable restart. The first context saved
checkpoints; an intentional crash-style restart was made after a confirmed
durable checkpoint boundary, and a new context resumed the exact workspace to
finish and finalize. No destructive workflow tool was available or invoked.

The finalized artifact independently passed the installed receipt verifier:
six files, SHA-256 bundle hash
`bc5fda1e045f170a1dc6d20dc8b7e14da659c6354d158f6b00ff894c7b31803c`,
summary hash `eadd4937fe7fd1c047715442605b446cd9e840750b7eccf7b13bab0f298e9ed1`,
and index hash `090027a44ae8eeed940843a948d8c7924188c0075e44ae8da61965fa86762bf1`.
This record intentionally excludes source material, labels, and private paths.

The subsequent isolated STAMPEDE transport diagnostic was stopped before source
access when a fresh foreground host invocation failed the nonce-MCP identity
check. This is a fail-closed host integration blocker; it produced no STAMPEDE
proposal, approval, checkpoint, terminal outcome, or artifact.

Owner-approved evaluation scope is CHAARTED and STAMPEDE only; TITAN is not run
as part of this acceptance record.

### Older RC5 performance investigation

One corrected blinded run reached a finalized assessment. Its private receipt
reported 97 turns, 1,047.874 seconds, and USD 5.4231043; the durable store
advanced during the session and contained nine records after finalization. The
receipt reported five completed checkpoints and a terminal assessment. Its sole
permission denial was a denied host-shell attempt to inspect a cached tool
result; it was not an MCP workflow tool or the destructive discard operation.

A prompt-only bounded A/B used the same model/effort with a 45-turn, USD 3,
and 12-minute cap. It stopped after 48 reported turns, 722.113 seconds, and USD
2.87833765 with an approved batch but no checkpoint or terminal. It could not
discover canonical signalling-question identifiers: the prompt requested generic
resource discovery, but only the parameterized guidance-resource reader was
available. A cheap zero-source probe established the smallest seam correction:
an explicit known domain-guidance URI returns the canonical identifiers within
three turns, 6.370 seconds, and USD 0.0825989. No provisional reference label
was accessed in either activity.

The attempted final A/B was invalid and is excluded from scientific comparison.
It exited in 67.215 seconds at USD 0.37789635 without an assessment after the
host attached to an inherited workspace rather than the intended fresh one.
Its supplied one-server configuration itself parsed correctly, referenced an
existing installed executable, and declared the intended workspace; the host
initialization reported one MCP server but did not attest its workspace. This
is therefore a host-launch isolation failure, not evidence about trial quality.

Future evaluation launchers must fail closed before a scientific prompt: use a
fresh working directory and a unique nonce MCP server name, load only an explicit
strict configuration and restricted setting sources, parse the initialization
event to require that unique server and only its expected tool prefix, then make
a zero-source resource/inventory probe that attests the intended empty workspace.
The streaming monitor must retain a redacted event ledger (time, event type,
tool name, status only), poll durable state metadata, and abort before ingestion
on any identity mismatch. Once identity is established, use all five explicit
domain-guidance URIs at phase zero; keep the bounded evidence plan and preserve
the five-checkpoint, contradiction, source-priority, and terminal/export guards.

## Private launcher hardening follow-up

The private #195 launcher now gives every Claude context a new nonce-scoped
project CWD while retaining the isolated `ROB2_WORKSPACE` as the only durable
workflow location. Each project has exactly one nonce MCP configuration and
fresh, non-appending debug, stderr, and redacted-event logs. The launcher records
metadata-only initialization server names and MCP tool prefixes before applying
its fail-closed identity check, and records whether a process exited, hit the
outer bound, or stalled.

A required STAMPEDE zero-source attestation uses a launcher-only nonexistent
trial identifier. It must fail closed before a source tool executes; this is a
transport/isolation check only and is not an assessment. Scope remains
CHAARTED and STAMPEDE only; TITAN remains out of scope.

## Final owner-scoped CHAARTED acceptance (a6fcc79)

The owner superseded the earlier multi-trial scope: this final acceptance is
CHAARTED overall survival only. A fresh full-history detached checkout at
`a6fcc7981b48e73eca528726debdb1d17be3b24e` built and passed source and wheel
release verification. The wheel used for the fresh workspace had SHA-256
`28f3bc764317643b518ba8ef86a568ce51211a8e619295c6f5c0700e8f627995`.

Operationally, the fresh human-style run succeeded: five frozen domain
checkpoints, an assessed terminal state, and a `FinalizedBatch` receipt. The
independently recomputed canonical bundle hash was
`728e0b9ed13bd04f10141c0086166e044e23aa8f945cc03b4759ccb28ddb8a5c`; the
canonical HTML report hash was
`95bcbf4d0bdacc28aaf8af76a1e1224a0ff59f2c2067129edda0530b83372bd8`.

The owner-authorized CHAARTED overall-survival provisional-reference comparison
agreed exactly: D1--D5 and the overall judgement were all Low. The frozen
assessment was not altered for this comparison. No rationale or citation
discrepancy requiring an evaluation note was identified.

This acceptance nevertheless failed the performance criterion: USD $12.813,
31.15 minutes wall time, and 153 turns. The recorded friction was source/anchor
repair before proposal approval, a first-domain validation condition repaired
without a durable write, and rate-limit warnings without a denial. No runtime
code was changed.
