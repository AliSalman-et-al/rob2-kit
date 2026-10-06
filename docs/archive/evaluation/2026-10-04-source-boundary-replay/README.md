# Bounded offline source-boundary hypothesis check

**Reject automatic caption-continuation detection and a new adjacent-context option.** Current tools recover the required source pages without a runtime change. A full physical page can end in complete sentences while a figure legend continues on the next page; text/layout proximity does not prove semantic membership or completeness. The existing `read_pages` `pages` list/windows supports explicit adjacent context with separate provenance and normal budget continuation. No feature, generic extra-page rule, mandatory source reading or semantic completion assertion was added. No model call occurred.

## Actual historical queries and delivered ranges

The required original Code benchmark traces and preserved recovery traces are retained in `historical-receipts.json`; current public-tool replays used their exact arguments on disposable copies.

- Original Code EXSCEL query: `primary outcome intention-to-treat hazard ratio 0.91`, mode `all`, main source only. Historical and current returned pages 1 and 6. It did not search the appendix or seek Figure S9.
- Recovery query: `Figure S2 Enrollment Follow-up Vital Status`, mode `phrase`, appendix only. Historical and current both returned no hits. The model then directly read pages 30/31 and recovered the flow. No-hit lexical retrieval was not evidence of absent flow data.
- Recovery query: `Primary endpoint CV death nonfatal myocardial infarction stroke analysis plan`, mode `any`, protocol only. Historical and current first returned windows are on page184, with an explicit broad-search continuation. The model then requested pages184–193. P186 was fully delivered, lines1–45, untruncated, no remainder; the six-month composite-versus-mortality rule is at lines22–27. Current P186 numbered text is byte-for-byte identical. Thus failure to use this rule is not explained by a missing returned window. Budget boundaries later on P191 differ slightly with the smaller current envelope; neither affects P186.
- Correct-source control: original Code DAPA-HF turn2 item64 requested protocol P161 lines15–31 alongside P233/234/240. Current replay delivered the same ranges, including the planned final-amendments-before-unblinding statement at lines16–18. This is a positive locator/recovery control, not proof of actual timing compliance.

No historical Figure S9 search/read/render call was found in the inspected EXSCEL Code and recovery traces. A separately labeled reference-following query, `Figure S9`, mode `phrase`, was derived from the already-delivered main report page8 pointer. It returns actual figure page45 and contents page2, with distinct physical locators. It does not claim to recover page46's untitled continuation. This is not presented as a historical issued query or as evidence that the model should have used hindsight terms such as “six months”.

## Existing navigation and explicit adjacency

Scoped `list_sources` supplies literal page45 caption and page46 leading text (“Data analyzed in the Intention-to-Treat population using cut-off date censoring scheme…”), with explicit physical page/line locators. It supplies a recovery lead, not a certified semantic continuation. Enumerating navigation from its beginning to page46 took 16 bounded calls and 108,256 serialized structured-response bytes; the literal named-figure search is a cheaper route to page45. No suggestion to enumerate every source is made.

The first figure page ends with a complete sentence, “Patients without any assessment of the endpoint were censored at randomization.” No safe punctuation-based continuation detector can infer that its remaining legend is on page46. Bare printed page labels in navigation can also become weak heading candidates; that is not a reliable semantic boundary signal and was not repurposed into one.

| Original source | Existing read | Serialized structured bytes | Extra bytes vs first page | Calls if requested together |
|---|---|---:|---:|---:|
| EXSCEL appendix | page45 | 1,377 | — | 1 |
| EXSCEL appendix | pages45/46 | 2,977 | 1,600 | 1 |
| DAPA-HF protocol | page161 | 3,374 | — | 1 |
| DAPA-HF protocol | pages161/162 | 5,704 | 2,330 | 1 |

Both paired reads preserve the first page's exact text, issue each page's own source/line/handle provenance, have empty remaining windows and fit the unchanged 24,000-byte structured response budget. There are zero added calls when requesting both pages initially, or one extra read when the first page was already read. The DAPA-HF pair demonstrates the same source-independent affordance on an unrelated original dossier. Reading neighboring text does not make it scientifically part of the selected figure or proposition.

Existing skill guidance already says to inspect adjacent pages for mid-sentence/list continuations, select evidence per physical page, and not equate empty remaining windows with a complete definition. The multipage tool option already implements bounded adjacency. A new option would duplicate that behavior; automatic continuation would add an unsupported semantic guess. The inability to prove a legend complete from one page remains explicit.

## Integrity and preparation limitation

Original source identities match the required Code dossiers. All tools ran on disposable copies, with original canonical/working/derivative DB hashes checked unchanged. The Code DAPA-HF archive retained canonical metadata and text projections but lacked captured source-byte files, so the first control attempt correctly rejected unavailable bytes. Hash-matched original Code PDFs were restored only into the disposable copy; `control-source-restoration.json` records the preparation failure and restoration. This is not attributed to the runtime page-boundary logic. Frozen assessments and historical source receipts were not changed.

## Next supported step

`future-reading-question/` contains a concise factual task and exact historically delivered SAP windows P186 lines1–45, P187 lines30–45 and P188 lines1–18, with an offline completeness receipt and private source answer kept separate. It asks how the specified >six-month death is treated for a composite versus standalone mortality, and how the primary censoring rule differs from on-treatment/cutoff schemes. The source states a checkable distinction; no D3 label, HR bound, expected clinical answer or automatic EXSCEL rerun is involved. No launch path is included; a new bounded decision is required before paid inference. Broad EXSCEL D3 uncertainty remains underdetermined by these passages.
