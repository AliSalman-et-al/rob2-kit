# 2026-09-27 live assessments

Five uncoached Codex CLI assessments completed on September 27: CHAARTED overall survival; ENZAMET overall survival, progression-free survival, and adverse events; and ARASENS overall survival. Each assessment finalized a bundle. Both `rob2 verify` and the independent `scripts/verify_bundle.py` accepted all five bundles.

These runs used provisional Domain 3 card wording from the uncommitted worktree diff. The controlled D3 wording comparison failed, and the production card was reverted at 10:05 UTC. These results describe the recorded code and skill bytes only. They do not verify the reverted wording.

The runs are development checks, not evidence that rob2-kit is bug-free or scientifically accurate. The expected Results stayed in runner metadata outside each model workspace. A human researcher reviewed each source dossier and selected Proposal Result before approving its scope. Every continuation prompt contained only `Continue.`

## Run setup and commands

All five runs used Codex CLI `0.157.1`, model `gpt-6-luna`, and `medium` reasoning effort. The wrapper used `codex exec --json`, a separate `CODEX_HOME` for each run directory, and a fresh workspace populated from each case's source allowlist. It saved every invocation to `phase-N.jsonl`, with separate stderr and last-message files.

The exact first prompts were:

| Case | First prompt | Prompt SHA-256 |
| --- | --- | --- |
| CHAARTED overall survival | `/rob2-assess Assess risk of bias for overall survival in CHAARTED.` | `6f51d2878c033cce7c9298111d11b8f9b9b68a930e1e762e64d28c24c744471c` |
| ENZAMET overall survival | `/rob2-assess Assess risk of bias for overall survival in ENZAMET.` | `a0f5561873323ac330f53e77fb7b625810da868718c39fc4e2df0e2509d75917` |
| ENZAMET progression-free survival | `/rob2-assess Assess risk of bias for progression-free survival in ENZAMET.` | `9ea00e6435c0c12fde457fc876803744576905d04accdb5854eaf58a696384ce` |
| ENZAMET adverse events | `/rob2-assess Assess risk of bias for adverse events in ENZAMET.` | `0e5706efc31ad40278dae5c780c2b4eeb9cfa90ed9b9936c90a3398b7faf751e` |
| ARASENS overall survival | `/rob2-assess Assess risk of bias for overall survival in ARASENS.` | `686fa7d75d4f927132b74698424d19f1a65609b5b73a0d57f43781085e5e04ba` |

All phase 2 prompts were exactly `Continue.` followed by a newline. Their SHA-256 is `f9823f83e586d97020b451ccbce761a8f5796374ece42b6586a9394ba7ef031e`.

The commands below reproduce the launch shape for ENZAMET overall survival. Substitute the matching case and prompt paths for each row above. Use a fresh run directory for every outcome.

```powershell
uv run python scripts/run_rsi_case.py `
  --case eval/runs/2026-09-27/issues-472-476-live/inputs/ENZAMET/overall-survival.json `
  --prompt eval/runs/2026-09-27/issues-472-476-live/inputs/ENZAMET/overall-survival.txt `
  --run-dir eval/runs/2026-09-27/issues-472-476-live/runs-v2/ENZAMET/overall-survival `
  --phase 1 --model gpt-6-luna --effort medium

$run = 'eval/runs/2026-09-27/issues-472-476-live/runs-v2/ENZAMET/overall-survival'
$session = (Get-Content "$run/phase-1.meta.json" | ConvertFrom-Json).codex_session_id
uv run python scripts/run_rsi_case.py `
  --prompt "$run/continue.txt" `
  --run-dir $run --phase 2 --session $session `
  --model gpt-6-luna --effort medium
```

The researcher inspected the proposal and source material, then approved the selected Result through the researcher-only CLI review gate. Each `approved-scope.json` records the approval, review, and Result identities, along with the approval time. Phase 2 resumed the same session after approval. The runner stored the expected Result in `run-inputs.json`, beside the workspace. The model-facing workspace received only the listed source files and generated source-role metadata.

Windows used `workspace-write` with `windows.sandbox = "unelevated"`. The strict deny-by-default profile was unavailable without UAC, and these runs did not request it. The separate workspace and `CODEX_HOME` isolate run state, but they do not establish filesystem isolation from other local evaluation files.

## Results

Domain order is D1 randomization, D2 deviations from intended interventions, D3 missing outcome data, D4 measurement of the outcome, and D5 selection of the reported result. `SC` means Some concerns.

| Case | Approved Result and relation to the prompt | D1–D5 | Overall | Researcher approval (UTC) |
| --- | --- | --- | --- |
| CHAARTED overall survival | Primary all-randomized overall-survival comparison, HR 0.61 (95% CI 0.47–0.80). Exact. | Low, SC, Low, Low, SC | High | `09:18:17.989579` |
| ENZAMET overall survival | Intention-to-treat overall-survival comparison, HR 0.67 (95% CI 0.52–0.86). Exact. | Low, Low, Low, Low, Low | Low | `09:19:42.254945` |
| ENZAMET progression-free survival | Clinical PFS, HR 0.40 (95% CI 0.33–0.49), in all randomized participants. The model marked it narrower than the broad prompt; it matches the frozen clinical-PFS target. | Low, Low, Low, SC, Low | Some concerns | `09:21:01.466102` |
| ENZAMET adverse events | Grade 3 adverse events: 277/563 (49%) versus 194/558 (35%). The model marked this narrower than the broad prompt; it matches the frozen grade 3 safety target. | Low, SC, High, High, Low | High | `09:19:42.708297` |
| ARASENS overall survival | Primary OS HR 0.68 (95% CI 0.57–0.80) after 533 deaths at the October 25, 2021 cutoff. Researcher approved the reported full analysis set of 1,305 (651 darolutamide; 654 placebo), versus the frozen target of all 1,306 randomized (narrower). The abstract says 1,306; the Results section gives 1,305 in the full analysis set. D3 Q3.1: No information. | Low, SC, High, Low, SC | High | `09:44:20.081147` |

These labels are the saved judgments and the server's deterministic overall aggregation. The human gate approved Result scope. It did not independently adjudicate the five Domain judgments.

## Trace and bundle identities

The phase traces below are complete JSONL files. Each phase had zero malformed JSON lines and ended with a `turn.completed` event. The completed runs had zero MCP `item.error` records. Their traces include ordinary proposal or Domain repair responses. CLI stderr also records platform and service diagnostics described under [limitations](#limitations).

| Case | Phase 1 JSONL SHA-256 (lines) | Phase 2 JSONL SHA-256 (lines) | Bundle SHA-256 and path |
| --- | --- | --- | --- |
| CHAARTED overall survival | `87c503b06991af461490faf985afbfcf4e33ea74de17da7f1ce6a774523e12a8` (38) | `4db4ba06abad424a196944ec2bd9432a874c1f45332081415369f0758140d5fc` (136) | `9068bf309daa133c3eb754f05fec71311c344239af0aca7143b4867b381be686`<br>`runs-v2/CHAARTED/overall-survival/workspace/.rob2-kit/finalized/295b96f22589c143564c1a223ea4111893441793da87e9f3b4527cb61e0d0996.rob2.zip` |
| ENZAMET overall survival | `6bd1713a677482a22450047c866ddf1c5950649a20cb022d6e8f0ae31e316bbb` (58) | `49580871fe16fb475b352bd6a109f878edf898a71df711b6e68e2346770253e7` (160) | `2960e5bbe3c222da17086c2bc70a1a6c8d5a2e081c8a6edc39c645c301fd8472`<br>`runs-v2/ENZAMET/overall-survival/workspace/.rob2-kit/finalized/af04f8f3a47a3d8a91739ae0b8bc6707283c7fba406e5528785d8dfc4066e855.rob2.zip` |
| ENZAMET progression-free survival | `d5ce2b9cb272311286c0e5db416ce217f6e0d13c405abc2c54c890ce29c1aedd` (66) | `f63bd618a5031d77279845f665b41186d28397f99dbc3b8c97dc46bbd52122f6` (248) | `849496053a70f4c782e9a6cbfd748546059a8c2eb7df79493be02f88b7111d56`<br>`runs-v2/ENZAMET/progression-free-survival/workspace/.rob2-kit/finalized/2939543006dd52a9c78067e54a4c1fe111522be18f18f3ab8c85037d1b01630c.rob2.zip` |
| ENZAMET adverse events | `cc96db1695f713e955b5bd861d2b37db9b75971caefe348f455a48e5531483cc` (36) | `2e4e0d472a3decad87228e5265fa79751e525bff37e6301c137df477babaf0d4` (117) | `953d1f3a928c3244091f3ad169d31b3e310738b5d040cde9334c3e97c40399d2`<br>`runs-v2/ENZAMET/adverse-events/workspace/.rob2-kit/finalized/ae2bb56b3ed6aaf4eb6a0fdc30677d443e14245ae96ae8ba12dadd9598e568ac.rob2.zip` |
| ARASENS overall survival | `2808593cc8c4cb93ec335f497d16b92f8a87ed6e178db455af50413ae94562a7` (49) | `ffd531fa84cec744124587418d89295ac5731babddf7d1c29487a81193659372` (210) | `8dece58503383eafd18f7d99797ce4aafad8411f44c9070cc47146e2d64944d4`<br>`runs-v2/ARASENS/overall-survival/workspace/.rob2-kit/finalized/a8579d5b6dd051319e76832651d1887a3f4c0b44014e08d1745483c97d00e84b.rob2.zip` |

Each bundle passed both verification commands:

```powershell
.venv/Scripts/rob2.exe verify <bundle.rob2.zip>
uv run python scripts/verify_bundle.py <bundle.rob2.zip>
```

The archive's filename contains its internal artifact identity. The SHA-256 in the table is the hash of the ZIP file bytes.

## Code and skill versions

All five completed runs record Git commit `8fa90ed5aec80de8bfc5dfb55e480b7a38f65dd8` and exported `rob2-assess` skill SHA-256 `7fef49616b4599c118c416059f50071674ffac5ab1913c1de9ddb40d471133a2`. The four CHAARTED and ENZAMET builds record build SHA-256 `8452d3c2b0f3c8642bf2f266b5ccb10426287eb6f71f9b02d4c96eb0dac51ab4`; ARASENS records `cd953cad4523210799ceabf1421991ada8c5c019632426a0f059b1d301fa2dc1`.

The shared Git commit does not identify the complete run code because the worktree had uncommitted changes. The build and skill hashes identify the recorded bytes. Those bytes include the provisional D3 card wording. Rerun the assessments against the post-revert build before using them as final-code verification.

## Limitations and source review

The assessments cover one CHAARTED endpoint, three ENZAMET endpoints, and one ARASENS endpoint. They do not establish that every rob2-kit workflow is bug-free. They also do not estimate scientific accuracy. The expected labels were not used to grade these runs, and no independent Domain-by-Domain source adjudication was completed here.

The CHAARTED D2 judgment is an open source-review candidate. The earlier audit flagged an inference from treatment awareness and non-initiation to trial-context deviations. The reasons for individual withdrawals and refusals remain unknown. The earlier audit calls this a candidate causal-inference weakness, not an established error. See the [September 27 agent audit](2026-09-27-agent-audit.md#source-to-answer-examples). The current CHAARTED run saved D2 as Some concerns, so the earlier High judgment does not establish that this run's rationale is correct or incorrect.

CLI stderr contains a PowerShell shell-snapshot warning in each run. The CHAARTED and ENZAMET OS continuation stderr files also contain model-catalog refresh timeouts. The ENZAMET OS and AE continuations contain telemetry send warnings. ARASENS phase 1 ended at the researcher approval point and logged an approval-tool argument parse error (`unknown field question, expected title or options`) plus a thread-not-found warning during rollout flush. The researcher then inspected the proposal and source, approved the selected Result at `09:44:20.081147 UTC`, and the resumed phase 2 completed with exit code 0. Both ARASENS JSONL traces parse completely, each has one `turn.completed` event and no malformed lines or MCP `item.error` records. The finalized bundle passed both verifiers. These diagnostics remain part of the retained logs.

ARASENS is recorded using the provisional D3 wording and the distinct build hash above. Its expected scope freezes all 1,306 randomized participants; the approved primary OS Result reports a full analysis set of 1,305. The researcher retained this documented discrepancy after inspecting the source and proposal. This is a Result-scope approval record, not a claim that the 1,305/1,306 population difference is scientifically resolved. No scientific accuracy claim is made for the saved Domain judgments.

## Final-code v3 assessments

These are separate post-revert runs against build SHA-256 `0875ce7a42bdd05aa76844412e88470a7f270884bb7727546935ccc5e07752e3`. The v2 runs above used provisional D3 wording and are not final-code evidence. The completed v3 records cover CHAARTED overall survival and ENZAMET overall survival, clinical progression-free survival, and adverse events. CHAARTED progression-free survival has no v3 run.

All v3 runs used Codex CLI `0.157.1`, `gpt-6-luna`, medium reasoning, Git commit `8fa90ed5aec80de8bfc5dfb55e480b7a38f65dd8`, and `rob2-assess` skill SHA-256 `0187435cc7ecc7363e782062dbd40fa18e77344d9fa66335303ac66187a4aac1`. They used Windows `workspace-write` with `windows.sandbox = "unelevated"`; strict deny-by-default isolation was not requested or available in this profile. Separate run workspaces do not establish operating-system isolation from other local files.

### Prompts and approved Results

The first prompt in each assessment was the minimal `/rob2-assess` request below. The human messages that follow are recorded as sent; they were corrections after the model surfaced an alternate candidate, not hints about Domain judgments. Every completed assessment resumed with `Continue.` (SHA-256 `f9823f83e586d97020b451ccbce761a8f5796374ece42b6586a9394ba7ef031e`).

| Case | Initial prompt and SHA-256 | Subsequent human message(s) and SHA-256 |
| --- | --- | --- |
| CHAARTED overall survival | `/rob2-assess Assess risk of bias for overall survival in CHAARTED.`<br>`6f51d2878c033cce7c9298111d11b8f9b9b68a930e1e762e64d28c24c744471c` | `Continue.` (common hash above) |
| ENZAMET overall survival | `/rob2-assess Assess risk of bias for overall survival in ENZAMET.`<br>`a0f5561873323ac330f53e77fb7b625810da868718c39fc4e2df0e2509d75917` | `Continue.` (common hash above) |
| ENZAMET progression-free survival | `/rob2-assess Assess risk of bias for progression-free survival in ENZAMET.`<br>`9ea00e6435c0c12fde457fc876803744576905d04accdb5854eaf58a696384ce` | `Please assess the reported clinical progression-free survival result rather than PSA progression-free survival.`<br>`130713c29dbfe094432736d50ef8ed351d9e2632bafae695d4cee76026c49480`<br>Then `Continue.` (common hash above) |
| ENZAMET adverse events | `/rob2-assess Assess risk of bias for adverse events in ENZAMET.`<br>`0e5706efc31ad40278dae5c780c2b4eeb9cfa90ed9b9936c90a3398b7faf751e` | `Please assess the reported grade 3 or higher adverse events result rather than serious adverse events.`<br>`8bf54a5abdc80de7f4c23b429ffdc010676a45e7cb4f774a6dd6d81862f0d71b`<br>`Use the reported grade 3 adverse events result: grade 3 only, not a combined grade 3–5 result or serious adverse events.`<br>`a119224f0abed155b8eb4ca88f16b3adcf81602738de8edaae35f88c5614871e`<br>Then `Continue.` (common hash above) |

The researcher reviewed the source-linked Proposal and approved each Result through the researcher-only CLI gate. Approval times were CHAARTED OS `10:30:49.827708 UTC`, ENZAMET OS `10:34:19.755892 UTC`, ENZAMET PFS `10:37:13.074645 UTC`, and ENZAMET adverse events `10:43:20.120591 UTC`. For adverse events, the frozen target named grade 3 or higher; the model noted that the report has no combined grade 3-or-higher total, and the researcher clarified the available Grade 3 row only. The expected Results remain in `run-inputs.json`, outside each model workspace. The gate approves Result scope; it does not independently validate the Domain judgments.

| Completed case | Approved Result scope | D1–D5 judgments | Overall | Saved scientific caveat |
| --- | --- | --- | --- | --- |
| CHAARTED overall survival | Primary intention-to-treat comparison, all 790 randomized patients; ADT plus docetaxel versus ADT alone; HR for death 0.61 (95% CI 0.47–0.80), median OS 57.6 vs 44.0 months, survival cutoff December 23, 2013 (median follow-up 28.9 months). Exact. | Low, Low, Low, Low, Low | Low | D3 Low cites follow-up status as of December 23, 2014, one year later than the selected OS cutoff. Treat the timing mismatch as a caveat; it does not establish complete follow-up at the 2013 cutoff. D5 also notes that the supplied protocol is dated 2014 and the exact plan-finalization and investigator-unblinding dates are not fully documented. |
| ENZAMET overall survival | Primary ITT comparison of 563 enzalutamide and 562 standard-care patients; first interim result after 245 deaths and median follow-up 34 months; HR 0.67 (95% CI 0.52–0.86; P=0.002). Exact. | Low, Some concerns, Low, Low, Low | Some concerns | D2 Q2.3 is No information: the report lists four standard-care-assigned participants who received no study drug but does not state why. This is saved uncertainty, not a demonstrated trial-context cause or proven error. The proposal notes this is an interim survival estimate. |
| ENZAMET clinical progression-free survival | Corrected from the initially proposed PSA PFS result. Clinical PFS in all 1,125 randomized participants; 167 vs 320 events, 3-year event-free survival 68% vs 41%, HR 0.40 (95% CI 0.33–0.49). The selected clinical endpoint is narrower than an unqualified PFS request and matches the frozen target. | Low, Low, Low, Some concerns, Low | Some concerns | D4 concerns open-label, judgment-dependent components of clinical progression: cancer-attributable symptoms and initiation of another anticancer treatment. The assessment records that the supplied evidence did not resolve whether assignment knowledge influenced these assessments. |
| ENZAMET adverse events | Grade 3 only from Table 2, 277/563 (49%) versus 194/558 (35%); safety population of patients receiving at least one dose. Four randomized standard-care patients who received no study drug were excluded. This is a Grade 3 component of the frozen grade 3-or-higher target; the source does not report a combined grade 3+ total. | Low, Some concerns, High, High, Some concerns | High | D3 High reflects uncertainty about complete Grade 3 event ascertainment. For D4, the model answered Probably yes because longer treatment in one group affords more time for Grade 3 events to occur or be recorded, although visit schedules and the post-treatment safety window were similar. This is an unresolved exposure/opportunity versus ascertainment distinction, not an adjudicated error; the saved High judgment is not claimed as correct or incorrect. D5 cites uncertainty about timing of the final SAP relative to access to unblinded results. |

The initial PSA PFS proposal had a source-linked working checkpoint for its own Result identity. After the human correction selected clinical PFS, the trace marked the old checkpoint stale with `result_changed`. The model then saved a checkpoint for the clinical PFS Result identity, and the first post-approval domain context reported that checkpoint as current. The adverse-event SAE checkpoint was also replaced after clarification to the Grade 3-only Result; phase 4 showed current checkpoint identity `sha256:db22289a0997677b57d4dc0e8c0fb4ed8708d7e9afd66de76eb67890f4218dc3` bound to approved Grade 3 Result identity `sha256:d891daceb029f95b23bac18b8982010532cb6678be654ae23546daa12938098d`. CHAARTED and ENZAMET OS likewise showed their approved Result identity on a current checkpoint when phase 2 resumed. Later `canonical_newer` staleness follows saved Domain judgments; it is distinct from invalidation after a Result change.

### V3 trace and bundle identities

The listed phase traces parse with no malformed JSON lines; each completed phase has one `turn.completed` and no `item.error` event. Each completed bundle passed both `.venv/Scripts/rob2.exe verify` and `uv run python scripts/verify_bundle.py`.

| Case | Phase 1 JSONL SHA-256 (lines) | Phase 2 JSONL SHA-256 (lines) | Phase 3 JSONL SHA-256 (lines) | Phase 4 JSONL SHA-256 (lines) | Final bundle SHA-256 and path |
| --- | --- | --- | --- | --- | --- |
| CHAARTED overall survival | `9bcbd6e28e5895b9a1b04626565a5a93e8ab749e2c3e5d0ca7a27609643741ef` (39) | `f1f4ba1620e5b0dec3691904c3c66b2c1abb904e6b0b935eb481d6013f9b950e` (110) | — | — | `8cd95f880bb71eda6cae9df462eb6e83cca48d523fd8b7545e9fc5ce061caee3`<br>`runs-v3/CHAARTED/overall-survival/workspace/.rob2-kit/finalized/cd6cd6dcfaca879581446d715ad32e1439d5f4fc7eebbf53c8e739b793fbdfb9.rob2.zip` |
| ENZAMET overall survival | `860ea71a83b4297e443fb5602e92c029b95a9e8863e643b806fe72002185f821` (46) | `bc44d4122d65805c123afa745c0550b3556ef74cd2114c1497beea8513c30d5c` (216) | — | — | `3adb1006ec9ceb233d4def0c3b9bc132c01e9b01cf42f1dbc31ece2b23cdcbb0`<br>`runs-v3/ENZAMET/overall-survival/workspace/.rob2-kit/finalized/13a465e95973212506f1f6ed7313c914a86d1f87e03862156bce0d3fe64d4320.rob2.zip` |
| ENZAMET clinical progression-free survival | `0162ce0cb32125478fad830af84f81d15ae6fc651e90ade42526857cecb1ecee` (46) | `c6a6a8e4d799b06444ea7e5c9162c792b4ec729aa565b7d5074f42cf12b3a442` (21) | `19061d3a7c9095ba5cf56c413feef58c72c5576a8745e08298066311499beb23` (129) | — | `2d372398a1d29e27a39d6c56aabc9754e1b8b455f75c271532d81103b9bcfb27`<br>`runs-v3/ENZAMET/progression-free-survival/workspace/.rob2-kit/finalized/25d23922fd2e0c9437f1b13bafb18ce7c8c7d5052ab9093780f52c3c0ac8cdac.rob2.zip` |
| ENZAMET adverse events | `fd6f7392c5dffe361447b800c58aab0bcc7fb558d256b68378c53d7148897842` (46) | `e128482005aa9489f7b564adf9f822cb2e5536ac2ae42bd2fb77c4ae9195956c` (17) | `0b5ea0ea54bb22a7796438e148f3dcd608e5d885e4b697757b71bfe7ac84a93c` (15) | `de622cf11cb9c3ebde786073de9e332d8eb071cc433f26c06122bcf9b6d9705a` (216) | `681caabe314afc4ad12936e1076a68fb50177f48f17c45b1e137bc488a1c7767`<br>`runs-v3/ENZAMET/adverse-events/workspace/.rob2-kit/finalized/6205e9f1053c80df433e8f17ea855475ba46bbe9b7fe342bf2c72bb44705a08e.rob2.zip` |

All four finalized v3 bundles passed both verification commands. ENZAMET adverse-events phase 4 exited 0; its JSONL trace is complete, with one `turn.completed`, no malformed lines, and no `item.error` event. Its saved High overall judgment and Domain judgments are model outputs, not independent scientific adjudications.

V3 stderr retains PowerShell shell-snapshot warnings. ENZAMET OS phase 2 and ENZAMET PFS phase 1 also logged model-catalog refresh timeouts. ENZAMET adverse-events phase 2 logged a Codex tool-router parse error at `10:39:01 UTC` (`unknown field question, expected title or options`) before the phase 3 Grade 3-only clarification and later successful researcher approval. These stderr diagnostics are distinct from malformed JSONL or MCP `item.error` events; completed phase invocations exited 0 and all finalized bundles passed verification.

### Reviewable run evidence

The selected v2/v3 JSONL traces, inputs, phase metadata, stderr, researcher
review records, four v3 finalized bundles, and controlled contrast logs are
packaged in [the run evidence archive](2026-09-27-run-evidence.zip) (SHA-256
`affe37c39b9505870bd1d4ff7fb4a6ac186bd3f98baf7ea7a0ae43a48181e4ba`).
[Its manifest](2026-09-27-run-evidence-manifest.json) lists 543 member paths,
sizes, and SHA-256 hashes. Extracting the archive at the repository root
restores the documented `eval/runs/2026-09-27/` paths for inspection. The
captured Source PDFs and earlier September 26–27 benchmark raw JSONL files are
not in this archive; those remain in the local ignored eval tree. The committed
cohort manifests and reconciliation records describe that earlier campaign,
but a clean checkout cannot replay its raw-log import without the original
files.
