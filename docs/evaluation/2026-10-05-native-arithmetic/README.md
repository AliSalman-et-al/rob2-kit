# Optional native decimal arithmetic: review packet

The actual native-only hosts disabled shell/unified execution/code mode and rejected
non-native activity. They exposed no general calculation path. Scoped count reconciliation
and proposal-derived sum/difference/ratio are not assessment scratch arithmetic.
`capability-evidence.json` binds configurations, supervisors and original submitted warrants.
No original case was rerun, changed or used as a new accuracy observation.

## Implementation and boundary

One optional native tool, `calculate_arithmetic`, accepts a decimal expression,
optional named decimal-string inputs, caller units and assumption annotations.
It returns the exact expression, supplied numeric inputs, annotations, decimal result,
precision and rounding semantics, and inexact/rounded flags. Defaults represent
omitted inputs/annotations as empty collections. No units conversion or dimensional
validation is performed. Calculation does not validate source selection, units,
assumptions or scientific inference. There are no implicit statistical formulas,
risk labels, evidence creation, required calls or answer gates.

The implementation uses Python's standard parser to construct syntax only, then an
explicit recursive whitelist of decimal literals, known input names, unary signs,
binary +,-,*,/ and parentheses. No eval or code execution, calls, attributes, indexing,
functions, powers, integer division, comments, strings or executable syntax are allowed.
Decimal literal spelling is recovered from the expression rather than converted from
Python's binary floating-point representation.

Limits: expression512characters/64syntaxnodes; at most16letter-led input names of
32characters; numeric strings64characters; no exponent notation/nonfinite inputs;
units200characters; at most8assumptions of200characters. Arithmetic uses a fresh local
Decimal context with28significant digits and ROUND_HALF_EVEN at each binary operation
and final result, exponent range[-256,256]. Unary plus preserves its operand exactly;
unary minus changes only its sign with `copy_negate()`, without rounding. Negative
literal and named-input representations therefore retain the same value before
binary arithmetic. Undefined operations, zero division and numeric
range/underflow are rejected. Flags expose rounding/inexactness; exact mathematical
rational values beyond this precision are not claimed.

The pure operation and native adapter never access a workspace. Its typed closed
output is scratch data without a workflow head, Source/Evidence identity or ledger.
It carries `outcome=success` for native observation bookkeeping; public normalization,
output validation and schema helpers preserve this stateless shape. Invalid requests
use native MCP tool errors. Existing workflow operations retain their
prior receipts, schemas and lifecycle behavior. Native inventory and observation-import allowlists gain only
this tool; supervisors already allow rob2-native calls, so no external tool, shell or
code permission was enabled. Previously frozen launcher/config/source artifacts remain
unchanged. Skill discoverability adds one short optional-use paragraph without named
trial examples or a mandatory workflow.

## Offline validation

53 integrated numeric/native/schema/contract-budget/observation-allowlist checks passed
17.68seconds. After final explicit-context hardening, all47arithmetic checks passed
again21.61seconds.
Four transitive exact-guidance/recovery checks also passed16.93seconds. They cover
signed contrasts, changed denominators, fractions/explicit percentages, negative/unary
values, exact decimal literals, repeating division, half-even precision ties, independence
from ambient decimal precision/traps, zero division, nonfinite/malformed/oversized values,
numeric overflow/underflow and executable syntax rejection. Native tests poison workspace
access, verify unchanged canonical state and validate public output. An initial schema
metadata-description failure was corrected. A new altered-global-decimal-trap test
exposed inherited default traps; the final evaluator supplies traps and flags explicitly
and that test passes. Ruff lint
and formatting and focused type checks accompany closure.

`schema-compatibility.json` compares against8a917d6: all22existing tools' input/output
schemas, descriptions and annotations are exactly unchanged. Only the new tool is added;
closed schema and total existing contract budget checks pass without increasing the budget.

`offline-examples.json` contains source-independent examples and conditional arithmetic
from the already sealed Castoldi/Ashar warrants. The Castoldi signed contrast remains
positive under the declared assumptions; Ashar's original illustration is numerically
consistent. These are arithmetic examples, not validated scientific premises, proof that
the calculator prevents the original mistake, or a reason to change any original label.
A wrong arm, missing observed value assumption or clinical threshold interpretation can
still yield exact arithmetic and a scientifically wrong conclusion.

This closes a verified execution-affordance gap; actual model benefit remains untested.
Independent review should assess syntax/resource bounds, deterministic precision,
state isolation, compatibility and limits before any later separately authorized locked
case. No paid inference, full benchmark or merge occurred.

## Independent review follow-up

Independent AI review of `c3f36fd` reported 10,000 generated reference cases
(9,985 numeric matches and 15 zero-divisions), 5,000 malformed-input fuzz cases
and 109 targeted checks. It identified representation-dependent early rounding
from decimal unary signs. The follow-up uses exact unary identity/sign inversion
and adds literal, named-input and nested-sign cancellation regressions. Binary
rounding, final-result precision, grammar and workspace isolation remain unchanged.
This is arithmetic implementation validation, not scientific or model-benefit validation.

Follow-up validation: all55arithmetic checks pass, including the eight added exact-sign
cancellation cases and native state-isolation checks. Focused Ruff/format/type checks pass.
