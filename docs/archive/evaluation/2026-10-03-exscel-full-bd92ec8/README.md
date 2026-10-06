# EXSCEL approved full-workflow continuation — premature stop

**Assessment did not complete.** One authorized `gpt-6-luna` medium continuation exited normally after 53.368 seconds and six MCP calls. It saved no Domain, produced no Trial review/closure or bundle, and exhausted no authorized guard. Phase remains assessment, revision 4, with EXSCEL pending. The final model response explicitly acknowledges unfinished source reading and context pagination, then stops. No operator repair or relaunch was performed. No new scientific Result/Domain output exists to compare against reference judgments; this is workflow failure, not a RoB disagreement or a scientific gain.

## Actual approval and preserved runtime

Ali's explicit “Yes” to the disclosed EXSCEL scope (ChatGPT message Sentinel_78073e975f34819187a70a3cd3344979, October 3 13:08 UTC) is retained alongside his standing authority. Immediately before acknowledgment, exact pending phase proposal/revision3, Review `sha256:c8091d311b549d5d26848195814279c93f2ce1e8ef2b9709bcf692c91c7a4a66` and Proposal `sha256:28982d105319fc9fddb2b437f6ffbac041a811e0b2fc209ea1213202ee4aba5d` matched. The sanctioned identity-checked `rob2 review` CLI displayed that immutable Review and received delegated `yes`. It recorded caller/method cli and acknowledgment `sha256:77106748490f20591e5eb09f1d521000d181c0c28abaf14a4a519c66f478f975`, observed_at 2026-10-03T13:10:16.960353Z. This is actual authorized delegated recording, not independent human RoB adjudication or an invented approval token. Phase advanced to assessment/revision4 before inference.

Runtime stayed clean frozen `bd92ec84fb1b24a05ac742db8ea01f3c9b7bcf6a`, using the preserved approved workspace and production skill from that same commit. Exact launcher and durable model/effort are verified. A fresh isolated model home reused unchanged existing auth/model-cache files; no old rollout or Domain answers/labels were supplied. Four original PDFs and sources.toml remain hash-matching. Original NCT01455896 metadata versus article NCT01144338 conflict remains recorded; no registry retrieval/replacement occurred. Model instruction contained the full production skill/references and generic completion requirements, no supplement page hints or desired signalling judgments.

## Exact sequence and failure diagnosis

1. `get_status`: approved Result/current notes and randomization next action returned.
2. `get_domain_context(domain:randomization)`: page index0/count3, delivery_status incomplete, explicit next cursor `.1`.
3. `read_pages`: requested all 12 main-report pages for assessment. Delivered pages1–4 and page5 through line76, with exact remaining_windows.
4. `read_pages`: model shortened the Source handle to `sh_693e51915e5ffcf` for seven continuation windows, dropping one hexadecimal character from `sh_693e51915e5ffefc`. Native schema rejected those handles. No valid content was lost or misattributed.
5. `read_pages`: model autonomously repaired all handles and received the continuation. Response explicitly left page9 lines257–295 and pages10–12 pending.
6. `get_domain_context(cursor:.1)`: successful questions page index1/count3, delivery_status incomplete, explicit next cursor `.2` and recovery action returned. The model then emitted its incomplete-work response and exited0.

No source, transport, runtime, authentication or approval blocker appears in the last successful receipts. Reading/context continuations were callable and explicit. There was one mechanical handle error, recovered successfully. It does not explain or justify quitting with pending valid continuations. No tool/guard commanded this stop. No implementation change can truthfully be called a fix for that model decision based on this trace alone. Do not add a semantic gate, force scientific answers, or automatically relaunch to manufacture completion.

The model did not read any new appendix definitions or relevant protocol/SAP pages in this continuation. Operator-only supplement inspection remains outside its coverage. Main-report proposal-phase coverage was complete, but assessment-phase delivery now remains partial. These distinctions are preserved in read-receipts rather than merged into a claim of comprehension/complete assessment.

## Diagnostic observer limitation

Original run.json reports no other_error_records because the native schema rejection appears as `item.status: failed`, `error: null`, `structured_content: null`, with error text in content. The observer checked structured outcomes/error only. Raw events preserve the rejection. One recovered error did not reach the two-identical-failure stop threshold; no guard breach is asserted. Future monitors must include failed item status when classifying errors. This is an observer accounting defect, separate from the model's premature exit. The run is immutable and not retrospectively relabeled successful or operator-terminated.

## Usage and guards

Continuation: **336,209 total input-plus-output tokens**, **334,932 input**, **268,800 cached**, **66,132 uncached**, **1,277 output** including196reasoning. Six direct MCP calls; zero wrapper calls. 53.368seconds. No observed output15,000/tool70/wall1200/idle180/four-saves-per-Domain/two-identical-error guard exhaustion. No saves attempted. Input telemetry only; dollar billing unknown.

Combined fresh EXSCEL proposal plus continuation: **1,275,511 total**, **1,269,267 input**, **1,113,344 cached**, **155,923 uncached**, **6,244 output**. 23 MCP calls and192.139seconds across two explicitly authorized invocations. Approval CLI is local, not another paid invocation. These are case totals, not total improvement-campaign billing.

## Remaining work and claims

All five Domains, complete applicable source investigation, Trial review, closure, finalization and verification remain undone. The approved Result and acknowledgment are preserved. This one-continuation authorization is closed without relaunch; any later decision must explicitly account for this failure and avoid accuracy-based retries. There is no final warrant to audit or matched accuracy gain to claim. Prior scope/definition/reference qualifications remain as documented in the [preapproval audit](../2026-10-03-exscel-preapproval-audit/README.md).

Artifacts include exact prompts/skills/runtime config, written approval and CLI output, approved seed/final state, all events, read receipts, durable usage and model identity. No auth files are committed. Bundle-verification records explicitly report assessment phase and verified=false because no bundle exists. Current full post-fix CI is unknown; no CI wait or logs retrieved. No full benchmark or merge.
