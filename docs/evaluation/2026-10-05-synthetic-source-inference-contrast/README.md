# Synthetic source-to-inference contrast — offline design

Status: frozen for parent design review; **no paid run authorized or performed**.
This is an operator-authored synthetic mechanism test, not benchmark validation,
a natural saved assessment, or evidence of improved scientific accuracy.
Production behavior is unchanged. The proven information-preservation repair at
a572af7 remains useful without a model-benefit claim; 83d10b8's Chua no-go stands.

Question: does asking for evidence that distinguishes an adopted explanation from
its closest plausible rival reduce unsupported premise promotion and correct its
dependent reasoning, while retaining supported facts and qualified inference?

## Four independent worlds

Three stroke rehabilitation situations hold assignment, selected endpoint,
randomized/analyzed totals and three adopted warrants constant. Only the reason
and outcome-observation status of two exclusions varies: explicitly unavailable,
explicitly observed but excluded for another missing variable, or unspecified
incomplete records. The asthma situation supplies outcome-specific attendance and
measurement evidence without per-arm counts. A directly supported calibrated
measurement claim is an unchanged control. These clinical contexts differ from
Baillard. The original warrants are intentionally fallible synthetic statements;
they are not model outputs or reference risk labels.

The model sees opaque case IDs in one fixed interleaved order. All four cases are
present in each arm. Sibling cases cannot establish facts in another case. The
panel may make the distinction salient in both arms and create a ceiling; this
limits extrapolation and is recorded rather than hidden.

## Frozen controls and sole intervention

Both arms receive exactly the same numbered source texts, selected endpoints,
claims, official-guidance paraphrase, instructions, case order, output schema and
review budget. Only one sentence differs; see `sole-intervention.diff`:

- Ordinary: check what the provided source evidence supports.
- Contrastive: ask what source evidence distinguishes the adopted explanation
  from its closest plausible rival.

No rival descriptions, expected factual decisions or scoring rubric are supplied
to the model. The source-to-claim problem is interpretation with complete tiny
sources, not retrieval or full RoB assessment. The guidance paraphrase follows
Cochrane's 22 August 2019 detailed guidance, pages 29 and 39 (existing local PDF
SHA256 a9e9c4fdc4be2d29b5c0a1a6b828e09f2014a34f6d5c302a532f6153ea0fd670).

Proposed future execution, subject to parent design approval: one isolated Codex
CLI session per arm, exact model **gpt-6-luna**, reasoning **medium**, existing
0.159.0 launcher. One review pass and identical 24,000-byte response acceptance
budget; no answer-feedback retries. This is a declared acceptance budget, not an
assertion that the CLI offers a provider output-token cap. Both arms have no
shell, web, MCP, external-file or other tools. Use the existing isolated CLI
configuration, ignoring user configuration/rules. Confirm the actual launcher
model, configuration, tool exposure and usage/time guards before any launch.
Do not construct a new launcher framework or silently substitute models.

Any authorized launch must use existing
`scripts/diagnostic_evidence_preflight.py:launch_checked`, with the frozen
manifest SHA and prompt. Preserve failures and raw usage privately. A schema
rejection is a failed run, not permission for a corrected paid repeat. No paid
launcher or sessions have been created in this offline step.

## Output and evaluation

`output.schema.json` reuses the existing SourceCheckReport wire schema inside an
advisory draft wrapper. Every claim requires a finding and a revision; dependent
warrants are separate claims. The revision text is never automatically applied.
Synthetic `sh_…` identifiers are explicitly fixture shorthands, not native
captured-Trial handles. No claim is made that canonical workspace validation has
run. A future offline result checker must bind claim IDs, whole clauses, snapshot
identity, case ownership, line ranges and contiguous quotes against the frozen
packet; ordinary type/schema validation alone is insufficient. No permanent
production types or additional framework are introduced.

`independent-rubric.md` is evaluator-only and must not enter model input, session
files accessible to the model, or feedback. Parent independent review should
approve factual expectations before execution and review anonymized outputs
without arm labels. The operator who built the fixtures cannot count as an
independent reviewer. Record disagreements and adjudication; do not force one
classification, wording, signalling answer or risk label.

The primary report is paired claim-level descriptive counts with denominators:
missed unsupported promotions, false alarms, unjustified loss of usable
information, and propagation into dependent reasoning. A perfect ordinary arm
is a non-discriminating ceiling result. One stochastic pair supports only a
mechanism observation; it cannot establish accuracy gains, robust model effects,
benchmark agreement or JAMIA-ready validation. Neither result authorizes
production-default changes or a full benchmark.

## Offline evidence

`offline-verification.json`: both existing coverage checks pass for all source
lines, 13 claims, shared strict-schema subset passes, exact single-sentence
contrast verified, zero paid calls. This validates declared byte coverage and
wire structure, not semantic sufficiency, provider acceptance or entailment.
`freeze.json` records SHA256 identities of all reviewable artifacts (excluding
itself). The private one-off preparation script is in diagnostics; there is no
new permanent runner or test framework.
