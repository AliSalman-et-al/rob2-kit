# Public regulatory source acquisition audit

The current native workflow cannot discover or capture public regulatory reviews, even when a relevant review URL is already known. This is a source-access capability gap, not evidence that a regulator document would change every unresolved answer. No production code or paid assessment was changed by this audit. The DELIVER pair remains frozen.

## Evidence

- `search_sources` in `application/evidence.py` searches the captured Trial projection, not the public web. The isolated native diagnostic disables web/shell/apps; general host browsing is not a practical route in that environment.
- `CompanionReference` in `application/companion_sources.py` accepts only protocol/SAP role hints. `_validated_reference` requires a literal citation and URL/DOI in an already captured Source page. A later regulatory review cannot generally be found through an earlier publication's literal citations.
- `PUBLIC_DOCUMENT_HOSTS` in `application/public_documents.py` permits ClinicalTrials.gov CDN, PLOS and PMC, but not FDA. Offline probes demonstrate rejection of the known official FDA URL before network access and rejection of a regulatory-review role.
- Initial registry acquisition in `application/registry_documents.py` downloads only posted protocol/SAP attachments. It is useful but does not search regulatory review packages.
- Five original Code benchmark cases were inspected read-only: DAPA-HF, DECLARE-TIMI58, CANVAS, MONARCH-plus and DELIVER. Their D3/D5 submissions include 46 captured-source search calls and no acquisition calls. These historical runs predate recent companion work, so this is not evidence that a current agent would ignore that functionality. The current structural restrictions above independently establish the gap.

DECLARE explicitly distinguishes planned informative-censoring analyses from unknown conducted analyses and results. MONARCH-plus lacks the applicable registry-listed SAP and cannot resolve analysis intentions: that is a protocol/SAP acquisition need, not an argument for regulator-specific retrieval. CANVAS already reports a conducted missing-event imputation result and supports 3.2 from it. DAPA-HF and DELIVER preserve timing/overlap uncertainties while allowing probable judgments. See `code-trace-evidence.json`; these are purposeful examples, not a prevalence estimate or reference re-scoring.

## Verified DELIVER example

The independently supplied FDA review URL was retrieved separately with a bounded 20 MB audit limit. It is not admitted into either model arm. The [May 2023 FDA review package](https://www.accessdata.fda.gov/drugsatfda_docs/nda/2023/202293Orig1s026.pdf), physical page 101/internal 31, distinguishes the Applicant's consideration of a tipping-point analysis from the reviewers' worst-case analysis: incomplete dapagliflozin primary-endpoint follow-up is assigned an event at censoring and incomplete placebo follow-up is assigned no event. Physical page 108/internal 38 identifies DELIVER's full-analysis-set primary endpoint and reports that reviewer-added worst-case HR as 0.85 (95% CI 0.77–0.96).

This supplies performed sensitivity evidence beyond the frozen dossier's planned missing-follow-up analysis. It does not make the primary Result a different sensitivity Result, independently verify patient data, or prove that all trial analyses were prespecified. The document is a later regulatory review containing both Applicant and reviewer analyses; its approval date must not be treated as the SAP finalization date. The source hash and exact physical/printed windows are in `fda-source-receipt.json`.

## Smallest supported candidate

Generalize the existing optional acquisition/admission path to accept a known authoritative public-document URL with its actual discovery provenance and an unverified linkage rationale. Reuse immutable PDF capture, provenance, Other-Source admission, page reading and existing revision behavior. Add the official FDA document host rather than trial-specific URLs. A protocol/SAP hint must not be required for a regulatory review. A URL discovered outside the captured dossier must not require a fabricated citation inside an older Source. Preserve the distinction between source-located citations and externally discovered locators.

This removes the demonstrated capture barrier and permits ordinary host search results or researcher-provided official links to enter the same native reading path. It does **not** solve discovery for a strictly tools-only agent. A bounded official-index lookup would still be needed there; its simplest provider/query interface should be established against real FDA metadata before adding a search tool. No automatic dossier expansion, new approval gate, per-question search requirement or regulator-specific answer rule is warranted by this audit.

Read every candidate as evidence, then match trial identity, comparison, population, exact endpoint/estimator, analysis cutoff and version. Keep Applicant-conducted analyses, reviewer reanalyses, regulator synthesis and prospective protocol plans distinct. Source category is provenance, not an automatic evidence hierarchy or preferred judgment. Optional acquisition failure remains a bounded limitation, not a forced NI response.

The first prospective test, if authorized later, should compare actual source acquisition and faithful use of a performed analysis; supplied-URL capture alone cannot be claimed as discovery success. No further paid testing is proposed until the candidate interface and source acquisition question are reviewed.
