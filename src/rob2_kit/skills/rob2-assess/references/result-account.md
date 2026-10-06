# Selected Result reconstruction (optional typed format)

Sources → how this Result was produced → independent official propositions →
canonical judgments. This replaces question-first fact gathering, not Cochrane
question wording or decision rules. The reconstruction is an editable working
account, never a server-certified causal model or Evidence.

Keep only connected facts material to understanding the approved Result:
assignment and intervention course; collection of the outcome; transformation
and analysis of those measurements; intentions and choices leading to the report.
Identify actual arms, phases, outcome windows and methods in the observation
text. Preserve other-arm facts as other-arm facts and distinguish plans from
conduct. Retain uncertainties and source conflicts beside the relevant step;
unknown transitions are legitimate. Do not mechanically fill all four aspects.
The approved Result may cover a different window from an adjacent report table.

The optional `save_working_checkpoint` format accepts `result_account` steps
instead of `observations`, `interpretations`, `premise_records`, `drafts`,
`terminology`, or `open_questions`. Each step has a stable host `id`, an `aspect`
(`assignment_course`, `outcome_ascertainment`, `analysis`, `plan_report`), one
existing `WorkingNote` as `observation`, optional `inference`, source-located
`counterevidence`, `unknowns`, and optional existing participant-flow `counts`.
Use the same references as Domain bases in `observation.sources` and
`counterevidence[].sources`: returned Evidence handles, exact text windows, or
delivered visual transcriptions. The existing selectors resolve source locations;
a selected handle avoids copying locators. Visual references require the actual
current-Trial image-delivery receipt. Count rows
require explicit selected current-Trial Evidence bases. Quantities are optional;
completion, analysis and imputation counts do not create observed outcomes.
The server returns content identities in `get_status` and Domain context.

Request shape (illustrative only; replace all values with your current Trial,
actual returned Evidence handle and inspected facts):

```json
{"checkpoint":{"trial_id":"trial-a","result_account":[
  {"id":"collection","aspect":"outcome_ascertainment",
   "observation":{"text":"The report describes specimen collection.",
    "sources":["eh_0123456789abcdef"]}}
]}}
```

`result_account` is directly an array, without a `steps` wrapper. References
belong in `observation.sources`, not beside `observation.text`. Add optional
`unknowns`, `inference`, source-linked `counterevidence`, or `observation.scope`
only where useful; empty fields are valid. When repairing a malformed request,
compare it with the attempted draft before resubmitting. Structural repair does
not resolve scientific uncertainty: reconsider any removed or changed observation,
unknown, inference or counterpoint explicitly. No rejected content is merged into
the accepted checkpoint. Native tool receipts retain attempted requests; offline
`account_repair_review.py` can display exact scientific-content changes between
those attempts for diagnostic review.

`get_domain_context` reuses these count rows in the existing flow and missing-data
projections before any D2/D3 save. An empty account count set remains empty;
previous answers do not fill its gaps. Caller-supplied previews remain possible.
D2/D3/D5 recover the same complete account and original source coordinates. Use
`read_pages`/`render_page` and select the original Evidence through the ordinary
source tools; account prose is not a substitute for cited source material.

An answer basis can retain its factual-step dependency with:

```json
{"evidence":"eh_<returned handle>","role":"inference",
 "working_observation":{"step_identity":"sha256:<returned step identity>",
 "transfer":"Explicit scientific connection when transferring a different scope"}}
```

Use real returned IDs. The server resolves the reference into the existing
canonical warrant snapshot with the complete original step and observation.
Cited Evidence must intersect that step's source locator. Known `mismatch`
scope used as support requires `role: inference` and an explicit transfer. Context
or contradiction can retain its genuine role with an explicit relevance rationale
in `transfer`; source scope is not
rewritten. Other scope interpretations remain host assertions, not entailment.
A direct source fact still needs a question-specific scientific warrant.

Editing a relied-on step changes its content identity. `get_status` and Domain
context list affected answers in `working_checkpoint.reconsideration`; changing
an unrelied step does not flag other answers. Old snapshots and answers remain
unchanged. Inspect affected sources and decide whether a canonical correction is
warranted through ordinary Domain submission. Changed Result/Source bindings
suppress the account and require reorientation; a changed Domain leaves the
factual account available without treating old inferences as current answers.

Official basis: Cochrane Handbook chapter8, §§8.2.1–8.2.3, 8.4, 8.5 and8.7:
https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08
A result-specific assessment distinguishes assignment effects, outcome
availability and reporting choices. Shared facts do not make signalling answers
dependent; probable judgments remain available without direct proof of every link.
