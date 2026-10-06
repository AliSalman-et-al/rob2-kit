# EXSCEL offline scientific inspection before actual approval

No inference, approval, domain assessment or source-coverage update. Exact saved Review remains `sha256:c8091d311b549d5d26848195814279c93f2ce1e8ef2b9709bcf692c91c7a4a66`, proposal `sha256:28982d105319fc9fddb2b437f6ffbac041a811e0b2fc209ea1213202ee4aba5d`, revision 3. Read-only canonical/derivative/working database hashes are unchanged. The operator-only definitions here were not delivered to the model and do not make its investigation complete.

## Scientific inspection

The exact Review selects the primary first cardiovascular death, nonfatal MI or nonfatal stroke; assignment to exenatide 2 mg weekly versus matching placebo; all 14,752 randomized participants (7356/7396); randomization through trial closeout/censoring; HR 0.91, 95% CI 0.83–1.00. Median follow-up 3.2 years is descriptive, not a fixed-risk window. Main article pages 1, 3 and 6 independently support endpoint, ITT, assignment, window and quantity. No component/recurrent-event/per-protocol substitution or substantive benchmark-target change is evident. Raw endpoint definition is null; source-owned label is `Primary composite outcome`; interpreted meaning remains in target/rationale. Noninferiority met and superiority not met are hypotheses about this Result, not a reason to select a different effect.

Bounded supplied appendix inspection: Clinical Events Classification Committee Charter excerpt, version 6.0, physical pages 15–23 (page 24 also retained to delimit the subsequent secondary HF definition). Numbered source text and source/projection identities are in `operator-only-numbered-definitions.json`.

- Stroke: page 15 lines 11–16 defines vascular neurologic deficit and excludes subdural hematomas from adjudicated stroke analyses. Lines 39–49 qualify the 24-hour duration with shorter-duration intervention/imaging/death alternatives. Confirmation list continues onto page 16 line 4 with “other compelling evidence”; page 16 lines 6–10 qualifies worsening of previous deficits. These matter to measurement interpretation but do not change the primary nonfatal-stroke component into another endpoint.
- MI: page 16 lines 33–50 establishes myocardial necrosis plus ischemia for spontaneous MI; its reference-limit footnote continues from lines 52–53 to page 17 lines 4–9. Other procedural/historical criteria continue through pages 17–20; page 17 lines 35–46 expressly permits PCI-related MI without ischemic symptoms. Do not generalize spontaneous-MI criteria to every included MI.
- Death: page 21 lines 6–7 classifies deaths as cardiovascular unless an unequivocal noncardiovascular cause is established. Categories continue through page 22; page 23 lines 34–37 separately describes undetermined cause. Main Table 1 page 6 explicitly says cardiovascular death includes unknown cause, so this is corroborating qualification, not contradiction or an operator-created endpoint expansion. It does not establish complete vital ascertainment.
- Secondary HF hospitalization starts page 23 line 39. Its distinct definition must not be substituted for the primary MACE endpoint.

**Finding:** no material contradiction to primary Result correspondence was found. These are material component-definition qualifications for later D4 and related scope reasoning. The saved `measurement=specified` can denote that a first-event method is identified; it must not be presented as completed investigation of operational criteria or established unbiased measurement. All-eight-facets-specified is stronger than demonstrated reading closure. The model never read these appendix pages. Approval can authorize assessment of this correctly identified primary Result while explicitly retaining this investigation gap; if Ali wants the immutable clarity assertion changed, request a replacement Proposal and fresh Review rather than editing this record. No request or correction is made on Ali's behalf.

## Registry provenance

Original Code `FILES.csv` maps the four published EXSCEL PDFs to these exact dossier hashes. The original OUTCOMES row explicitly names EXSCEL primary MACE and NCT01144338; the supplied primary article page 1 names EXSCEL/NCT01144338. Original unchanged sources.toml uniquely declares NCT01455896 in the inspected corpus manifests. The archived original case retained that declaration; its presence is provenance for the metadata conflict, not evidence of registry equivalence. Acquisition record is the September 23 chrome sweep; no source here explains how the inconsistent declaration arose. Thus **published Trial identity resolves to EXSCEL/NCT01144338; original metadata inconsistency remains**. No claim is made about the contents of the other registry ID. Neither identifier was retrieved or silently corrected. Normal intake's unavailable NCT01455896 condition and all original manifest bytes remain visible.

## Actual approval paths

There is no generated web approval link, local app UI or known active ChatGPT widget in this run. The immutable JSON/packet links are inspection artifacts, not acceptance links. The paid launcher did not enable request_proposal_approval; no accepted elicitation exists. Production MCP supports `request_proposal_approval({})`, but requires a host elicitation capability and actual accepted `approved=true`; without that capability it returns proposal_approval_unsupported. No widget availability is asserted without an actual host event.

The sanctioned local **researcher CLI** is available and explicitly binds acknowledgment to the exact displayed Review. Ali can run this command, inspect the complete Review it prints, then type `yes` or `no`. The same command can be executed by an authorized worker only **after Ali explicitly approves this exact immutable Review in conversation**; that written decision must be retained as authorization. Broad optimization/benchmark approval is insufficient. For a delegated acknowledgment after that decision, supply `yes` to this CLI's stdin, never call an internal approve function or fabricate an acknowledgment record. Do not run this command before approval:

```bash
PYTHONPATH=/home/ali/Documents/Codex/2026-10-02/task-4/diagnostics/frozen-exscel-bd92ec8-code/src \
/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python \
-m rob2_kit.interfaces.cli.app review \
--workspace /home/ali/Documents/Codex/2026-10-02/task-4/diagnostics/frozen-exscel-bd92ec8/workspace \
--review-reference sha256:c8091d311b549d5d26848195814279c93f2ce1e8ef2b9709bcf692c91c7a4a66
```

It rejects a changed Review identity, prints the exact whole candidate, reads an explicit yes, and calls the sanctioned approval application seam. It records Review identity, purpose, caller/method `cli`, timestamp, workflow basis and content-derived acknowledgment identity in canonical state/history; retains the immutable approved Proposal/Review; clears the pending Review; initializes pending Domain state; advances phase to assessment and revision. It does not edit Result/source/clarity facts, create Domain judgments or finalize. Written approval and the CLI record have different provenance: do not claim Ali personally typed at a terminal if a delegated worker recorded his explicit written decision. Read status/receipt afterward and retain acknowledgment before any separately authorized inference continuation.

Repository implementation: `src/rob2_kit/interfaces/cli/app.py` review command; `application/intake.py` approve_review. Skill requires presenting the exact Review and actual researcher gate. No actual approval was recorded here.

## Concise approval-request material

Approve assessment of the saved EXSCEL primary assignment/ITT first-event MACE HR 0.91 (0.83–1.00), not a declaration that RoB is Low. Published identity NCT01144338 is supported; inconsistent original metadata NCT01455896 remains preserved. Detailed component criteria qualify measurement and are unread by the model; no primary correspondence contradiction was found offline. Full D1–D5, source recovery, Trial review/closure and final verification remain pending. Reject/correct if exact Result or clarity needs replacement; any replacement requires a new immutable Review. The actual reference to approve is printed above.

## Diagnostic runner correction and verification

The original run, archived runner and four post-save calls are unchanged. Future runner now calls `scripts/proposal_probe_terminal.py`: a save_proposal receipt with success/review_required stops only when its explicit next action names a researcher-authority Proposal Review with a reference. Validation success, arbitrary success/condition, wrong authority and missing Review do not masquerade as a saved terminal. The exact patch is retained. Two focused tests replay the actual archived validation/save receipts and neutral boundary cases; tests and focused Ruff checks pass. No paid test/relaunch. This corrects observer control, not model scientific reasoning.

Latest invocation usage remains **939,302 total input-plus-output tokens**: input **934,335**, cached **844,544**, uncached **89,791**, output **4,967** including 787 reasoning. 17 MCP calls, 138.7705 seconds; dollars unknown. No new inference usage. Current full post-fix CI remains unknown; previous checkpoint CI was queued. No CI wait or new logs.
