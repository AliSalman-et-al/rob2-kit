# Native registry planning-document intake

The prior feature was available through host `sources.toml` only. Added an optional
argument to the existing public `prepare_batch` tool; no additional fetch tool,
approval layer or active-Batch insertion was added:

```json
{
  "requested_outcome": "primary outcome",
  "expected_revision": 0,
  "trial_labels": ["exact input directory label"],
  "acquire_registry_documents": true
}
```

The dossier supplies its NCT identifier through the existing manifest. True
requires exact named Trial labels and overrides those Trials' manifest document
setting at initial intake. False disables document acquisition, including a host
manifest opt-in. Omission retains existing manifest/default behavior; historical
tests and archived workspaces do not become live by default. The explicit choice
binds the intake declaration. An identical retry returns the captured Batch
without requests; changing the choice on an existing Batch is rejected and leaves
it intact. Optional missing documents do not require restarting the assessment.

Opt-in captures the official current record's supported planning PDFs through the
existing bounded transport, plus a readable acquisition-provenance Other Source.
When explicitly augmenting a retained registry replay, its bytes/hash remain
unchanged and current discovery metadata becomes a distinct Other Source. This is
new evidence, not a replay of historical availability. Metadata records whether
the request came from the native argument or manifest and its effective setting.

A native assessor receives distinct Source handles from `list_sources`, reads
protocol/SAP pages with `read_pages`, searches exact Sources and renders their PDF
pages. Public readers deliver `numbered_text`, line ranges and passage handles;
application-layer `text` dictionaries are not the public receipt shape. Reading
metadata about a PDF is distinct from receiving its pages. Receiving text/pixels
verifies delivery, not model comprehension or scientific sufficiency.

Complete received PDF bytes have hashes and page counts; capture does not establish
an exhaustive universe of plans, publications, amendments or eligible analyses.
Dates separately describe document, upload and retrieval metadata; none proves
actual finalization before unblinded access. Role/registry links are association
evidence, not applicable-plan or conduct certainty. The original report remains
available under no links, failed fetch or unavailable identifier conditions.
No acquisition outcome writes a Domain answer, NI or prespecification certainty.

## Public-boundary verification

`tests/test_native_registry_intake.py` uses actual FastMCP discovery, input/output
schemas and returned native handles, with neutral HTTP fixtures. It follows all
transitive packaged operational guidance and verifies content hashes. It exercises
opt-in, explicit disabled, default offline replay, augmented replay, no links,
failed PDF access, no identifier and rejection of unscoped opt-in. It confirms:

- Original main-report input and registry replay bytes/hashes remain unchanged.
- Protocol/SAP Sources have distinct identities, correct entire fixture byte hashes,
  registry origins and no prespecification-certainty field.
- Native handles support list, numbered page reading, Source-filtered search and
  render receipts with actual image blocks before Proposal Review.
- Provenance is independently readable, retries issue no refresh, and altered
  acquisition choices cannot replace active Sources.
- No missing-document state creates an extra review gate or scientific judgment.

Validation: 16 final focused native/schema/error checks passed; 66 broader
intake/registry/budget checks passed, with the newly extended schema-property
expectation corrected and passing in the final focused run. Full src/tests type
checks, focused Ruff and diff checks passed.

This is an offline public-protocol integration check, not a live Codex model/tool
choice trial. Prior real registry examples remain DAPA-HF `NCT03036124` and ACTT-1
`NCT04280705`, with their public capture reports and byte hashes retained.
`request_companion_source` remains a reference-recording host handoff, not automatic
acquisition or reading; its staged/admitted/read flags were not broadened.

## One prospective D5 pilot protocol — no launch

Prepared [pilot-protocol.json](pilot-protocol.json) and copied all six original
DAPA-HF input files byte-for-byte from
`/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials/dapa-hf`
into a private prospective input workspace. No labels, gold or prior scored
judgments were consulted. DAPA-HF was chosen for its parallel randomized design
and observed separate public protocol/SAP availability (103/52 pages). Original
publisher protocol/appendix material remains supplied; registry files may duplicate,
clarify or differ from it, so augmentation is not assumed to improve accuracy.

Research question: can native acquisition and source-specific reading distinguish
plan content/applicability, document chronology and actual unblinded-access timing
for the exact reported cardiovascular-death/worsening-HF Result, without treating
metadata or intended safeguards as proof of actual conduct?

Investigator criteria, kept out of model instructions: verify source identities and
complete needed passage delivery; retain content/version conflicts and missing
premises; judge scientific support against the exact approved Result; accept
supported inference or honestly bounded unknowns without predetermined labels.
Do not claim accuracy gains from source augmentation or compare this enriched
corpus to the October-1 score as though evidence were unchanged.

The existing Code benchmark launcher explicitly configures `gpt-6-luna` with
medium reasoning; its file hash and relevant lines are recorded. No launcher or
model was run. Pilot outline is prepared but not launch-ready: it still requires
future diagnostic authorization, prospective Source capture, a precise cited
Result, frozen research criteria/model input/all required uncited text or image
windows, and a passing `scripts/diagnostic_evidence_preflight.py:launch_checked`
before any inference. This checker verifies declared coverage, not scientific
sufficiency. No criteria/answers/gold are inserted into the model input.

Raw PDFs and the copied input remain local under
`diagnostics/native-registry-intake-20261004`. Only code/tests/provenance and the
unlaunched protocol are published. No paid calls, full benchmark, merge, CI wait,
Astra, archived-capture modification or accuracy claim.
