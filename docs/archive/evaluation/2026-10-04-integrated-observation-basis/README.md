# Integrated Evidence-basis interpretations

The successful Aarnoutse D2 submission used seven Evidence bases containing only
`evidence` and `role`; the successful Freeman D3 submission used eight such bases.
Neither saved working observations. Freeman selected three passages (one visual);
Aarnoutse reused available Evidence without explicit selection calls. These frozen
runs establish nonuse of the earlier optional checkpoint workflow, not that the
new interface changes model behavior.

`save_domain_judgment` now accepts an optional compact `working_observation` with
`text` and optional `scope` on the Evidence basis already submitted. The server
captures the cited Evidence locator and stores a source-bound observation in that
basis. Exact quote/transcription remains separate. Visual render provenance and
uncertainty remain on the cited Evidence. Scope is supplied by the host; no Result
scope, missing dimension, answer, relevance decision, or count threshold is inferred.
Existing checkpoint-linked observations retain their membership checks and durable
snapshots. Inline observations do not create an advisory checkpoint or extra ledger.

For an already selected Evidence item, the old capture path required three actions:
`save_working_checkpoint`, `get_status`, and `save_domain_judgment`. The new path uses
one ordinary judgment submission. A minimal scoped note previously required seven
additional scalar values in the checkpoint (trial, text, source, page, two lines,
relation), then seven in the basis link (checkpoint identity and repeated note).
The compact path adds text and relation once: two scalar values. Routine unchanged
judgment fields are excluded from these counts. Scope itself is optional.

## Aarnoutse scientific qualification

The report's methods explicitly plan about 20 participants per arm for PK power
and 50 per arm for safety (page 11, lines 47–59). Week-six PK curves were collected
in hospitalized patients (page 10, lines 52–64). Therefore 23/21/19 measured PK
participants versus 50 randomized per arm does not by itself demonstrate an
inappropriate assignment-effect analysis. A planned endpoint-specific sampled
cohort can legitimately retain randomized assignments. The available corpus has
no independently timestamped protocol/SAP establishing prespecification.

The selected Result describes an all-randomized target and a related reported PK
result; applicability of the hospitalized cohort remains a qualification, not an
automatic D2 failure. Exact nonsampling reasons are unresolved. Methods counts
23/20/20 conflict with results 23/21/19, and abstract/narrative control AUC 24.6
conflicts with Table 2's 23.9. These conflicts remain preserved. The saved definite
Yes analysis judgment is under-explained about planned sampling and target
applicability; its label has not been demonstrated scientifically wrong. This
change neither rewrites that frozen judgment nor makes an accuracy claim.

## Validation and limits

Six neutral native submission cases cover mismatched arms/stages, partial time
scope, sampled populations/methods, shared context, unknown applicability, and
omitted scope. They verify exact Evidence text, server-captured locators, supplied
scope, absence of inferred Result scope, durable context recovery, and no advisory
checkpoint creation. Finalized text and visual bundles pass product and standalone
verification. Visual tests preserve render receipts, transcription, and distinct
source/host uncertainty. Six legacy checkpoint-link tests pass. Public closed-shape
and surface-budget checks pass with unchanged limits; generated release contract
and type/lint checks are refreshed.

No paid model calls ran for this change. Adoption and behavioral benefit are
unmeasured; mechanical capture is verified, scientific entailment is not certified
by typing or bundle verification. Full benchmark remains off.
