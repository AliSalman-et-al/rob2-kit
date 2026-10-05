# Native review recovery and authority audit

The fresh SMART-CHOICE-3 review remains a negative scientific result. This audit
uses its preserved native receipts and offline controls only; no further model
call, label correction, or scientific revision is authorized or performed.

## Empty-window failures

Each initial failed `read_pages(windows=[])` call immediately followed a selected
`review_trial` response: items 11, 13, and 15 selected D1, D2, and D3. All three
responses were complete transport projections and contained nonempty
`evidence_expansions`: respectively 4, 6, and 3 exact Source windows. The
expansions included Source, page, and line coordinates, independent of historic
reading coverage. Therefore the observed failure is argument construction; the
trace does not demonstrate absent recovery locators. Its cause inside the model
is unknown. No new recovery operation or reviewer mechanism is introduced.

Summary projections already provide `review_page.stable_recovery` to reconstruct
the complete receipt. A selected summary can defer Evidence expansions, but
explicitly lists those deferred fields and retains this existing recovery.
Domain context omitted narrative quotes already carry a one-window executable
`read_pages` recovery, including when earlier reading receipts mark delivery
complete. Primary-report `reading_recovery` represents uncovered delivery, not a
current reviewer's memory; absence of delivery gaps does not remove Evidence
recovery. Failed empty requests cannot establish inspection.

## Authority and wording

`review_trial` binds current Result/checkpoint identities; `close_trial` checks
that lineage. The status continuation already assigns both operations to the
host. Domain context explicitly attributes evidence sufficiency to the host,
and says structural success does not establish scientific correctness. The
packaged assessment skill already says `read_complete` establishes delivery,
not comprehension or scientific sufficiency. These existing boundaries remain.

Two model-facing descriptions are corrected. “Source text is read once” becomes
read or reread, with historical delivery distinguished from current inspection.
“Domains are reviewed as assessed” becomes checkpoints bound as assessed, with
scientific support still the host's responsibility. This changes no canonical
records, algorithm, answer, judgment, researcher approval, or structural gate.
A complete review page means the requested transport projection is delivered;
it does not certify entailment. No deterministic gate can establish that a
citation supports the scientific proposition solely from identity and shape.

## Validation and limits

The existing omitted-quote control now explicitly includes prior delivery and
`read_complete` coverage and requires the same exact recovery window. Existing
controls cover partial delivery, receipt loss restoring reading recovery,
changed Source rejection, host sufficiency attribution, and review projections.
A disposable copy of historical revision 9 also executes all three original
sets of Evidence expansion windows twice. Neither original run nor its Sources
are modified. Offline receipt delivery is useful ergonomics evidence, not a
claim that the model now reads correctly or that scientific agreement improves.

The offline native reread control passed: D1/D2/D3 supplied 4/6/3 nonempty
windows; first and repeated deliveries had identical page payloads, and the
canonical workflow head remained byte-identical to historical revision 9
(`sha256:5c8ba72fbcadab2e34a7ab48aacac240aabf651eae9d02e09926588424b2f2a4`).
See [offline-reread-summary.json](offline-reread-summary.json). The original
assessment's 119 sealed files and the fresh review's 133 sealed files were
rechecked unchanged after the control. Full Source receipts remain private in
`diagnostics/native-review-recovery-audit-20261005/`.

## Demonstrated continuation regression

The focused suite initially produced 58 passes and one failure:
`test_auto_domain_context_delivery_is_sequential_and_restartable`. A partial
Domain-context response returned its next cursor, but a subsequent `get_status`
lost it (`head.next_action.cursor` was null). The status transport bypassed the
shared header-enrichment function used by the other responses. Status now uses
that same function with its already obtained current head, exposing the exact
pending cursor and original byte budget. This is a recovery-affordance fix;
it does not infer Source inspection, alter canonical data, or connect causally
to the fresh-review empty-window failures. The existing regression exercises
status, early finalize/save refusal, sequential continuation, and restart.

After the fix, the failing continuation regression plus omitted-quote recovery,
near-limit read packing with a pending cursor, host-support attribution, and
release manifest/contract controls all passed: 12 tests in 28.83 seconds. Ruff,
type checking of the changed server, and `git diff --check` passed. The earlier
58 passing controls include partial-window reading, delivery-receipt loss,
changed Source rejection, and selected-review projections. No paid behavioral
retest or full benchmark was run, so no scientific improvement is claimed.
