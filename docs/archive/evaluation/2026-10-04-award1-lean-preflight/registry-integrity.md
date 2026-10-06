# Offline source-integrity closure

The preserved registry text is ingested as an ordinary **local text Source**:
`origin=local_dossier`, `media_type=text/plain`, role `registry`. Its captured-byte
SHA-256 is `9680cc92144bf1e3888e0826fbbe25931c25c2b938897ba04959ec714b62db8f`;
its new projection identity is
`sha256:0e13ba693bdcbe7d448e315cc15f717c9332a3dff6ff9cf27adb7b29928bf6dd`.
It does not impersonate the historical JSON Source or borrow its raw-byte identity.

Combining the preserved text with the recorded original JSON hash and extraction
recipe reproduces the historical projection identity `41d5c767…`. This proves
consistency with that preserved text/version record, **not authentication of the
absent raw JSON**. The historical raw hash is metadata, not evidence that missing
bytes were revalidated. Original JSON remains unavailable. No source-index,
canonical record, validator, or production code was patched to admit it.

Normal `read_pages` validation checks captured bytes against their own canonical
hash and all persisted page text against the text Source's projection identity.
Scratch-only byte tampering was rejected with `EvidenceIntegrityError: captured
Source bytes do not match Canonical identity`. Scratch-only page-text tampering
was rejected with `EvidenceIntegrityError: captured Source projection identity
is corrupt`. Original sources and initial workspaces were not changed by these tests.

A clean git-archived baseline at `247db8c805c34923e2cd086124b084d040121834` and
current production consumed identical source metadata and returned text hashes,
both before and after the common Result amendment. No integrity bypass or
baseline compatibility blocker was found. The registry primary 271/119 entries
are linked to the exact 26-week journal contrast by OG000/OG003 mapping, primary
endpoint/timeframe, group LS means, and the -1.05 LS difference. They remain
analysis denominators, not observed endpoint counts.

Both amended initial workspaces have zero domain records, working checkpoints,
operator D3 fixture facts and assessment-phase reads. Canonical record kinds are
only batch, proposal, review, acknowledgment and state. Proposal visual evidence
is Figure 2A source transcription, not the offline Figure 1B fixture/counterpoint.
Historical workspaces, source-only bundle and offline fixture remain separate.

`model-task-amended.txt` makes raw JSON absence visible in both conditions using
only factual source-provenance text. No reviewer rubric, missingness counts,
preferred signals, prior domain answers or fixture interpretations were added to
the task prompt. Full source access is retained. The amended relation/population
are ordinary shared Result fields, clearly recorded as amended rather than replay.

Evidence: `registry-integrity-closure.json`, `amended-common-result.json`,
`amended-common-manifest.json`, and passed amended availability manifest. The
scratch test script/results are preserved under the private `registry-integrity`
directory. Independent review is qualified GO; inference remains unauthorized.
