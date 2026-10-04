# Inline visual reference validation

A trace-supported interface asymmetry motivated this change: Domain saves could
resolve text ranges directly, while a visual region required a separate selection
call. Saves now accept `{delivery_receipt, region, transcription, uncertainty?}`
through the existing visual selector and canonical Figure evidence type. The
server derives source, page, render and hashes from an authentic recorded delivery.
No new tool, ledger, OCR interpretation or entailment decision is introduced.

The offline public MCP comparison in `measurement.json` recorded three successful
actions for render/select/save and two for render/save. Required visual selection
values decrease from five to three; the Domain envelope remains identical.
Both paths preserved the same Result, answers, evidence, counterclaims and
uncertainty. This is a current-code transport comparison with zero model calls,
not evidence of model accuracy, token savings or general behavioral improvement.
Selected handles remain useful when a long transcription is cited repeatedly.

Neutral raster multiarm table, flowchart and plot fixtures check direct submission,
explicit roles, unknown visual interpretation and counterevidence reuse. Failure
cases cover unavailable or mismatched receipts/source records, changed pixel
hashes, invalid region geometry and metadata-only rendering. Valid geometry and
provenance do not establish that a transcription or interpretation is correct.
Text captions stay narrative evidence and cannot stand in for graphical cells.

Validation: initial focused contract/submission tests passed (27); strengthened
visual cases plus existing delivery/integrity tests passed (22); contract budget
checks passed (3). Ruff and scoped source/new-test type checks passed. These
counts overlap and are not a distinct-test total. Existing broad repository type
check debt remains outside this change. Reproduce the offline comparison with
`PYTHONPATH=src:scripts:.:tests python reproduce_paths.py <new-output-directory>`
from the checkout, using this directory's script path.

The original paid pair remains frozen: 2,956 protected/answer files in baseline
and 2,961 in lean were hash-verified after this change. Its independent AI review
and mixed-quality verdict are recorded separately in the paired run addendum.
No frozen assessment was amended and no further paid evaluation was run.
