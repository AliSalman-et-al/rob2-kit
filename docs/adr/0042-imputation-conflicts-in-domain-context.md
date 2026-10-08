# Expose scoped imputation quantity conflicts in Domain context

Status: reversible context prototype; scientific benefit unproved.

Official RoB 2 guidance (22 August 2019), Box 8, question 3.1, treats imputed
outcome data as missing outcome data. Existing participant-flow reconciliation
uses a declared imputed count as a lower missing-count bound when observation
is unknown. However, explicit observed or unavailable counts can produce an
exact missing count below that same lower bound.

Use the existing source-bound Domain 3 comparison projection to expose this
local inconsistency. Require explicit Result identity, endpoint, matching window
and time-point declarations, participant units, randomized-population meaning
and imputed-outcome meaning. A conflicting event definition does not qualify.
These are host-declared premises, not a server-certified source interpretation.
An imputation method mention alone supplies no count; components, other visits,
unknown meaning and different row scopes supply no automatic constraint.

The affected context row retains every supplied quantity, scope and Evidence
basis, adds a `quantity_conflict` explanation, and withholds its derived missing
count, fraction and bounds. Conflict-report projections receive the same treatment.
Corresponding availability slots and participant-flow quantities are marked
conflicted. The model can inspect the original sources and reconcile the values
or their asserted meaning. The server selects no signalling answer or risk label.
Coherent observed-plus-imputed inputs retain their arithmetic; analysis counts
can include imputed outcomes. No probability or D3.2 evidence requirement changes.

Canonical reconciliation, stored assessments, bundle verifiers and historical
artifacts are unchanged. This is a read-only issue, not a submission/finalization
gate. It does not establish that models will act on the issue, and it cannot repair
an incorrectly interpreted premise or detect general D2/D5 applicability from
prose. No new tool, input premise schema, account, model loop or freeform review
is introduced. Behavioral improvement needs a separately authorized comparison
with true, false and unresolved conditions and checks for unsupported premise
reversals after feedback.
