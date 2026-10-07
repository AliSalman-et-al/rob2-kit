# Optional fresh source audit

Use this path only when the researcher requests a separate source audit. It is
advisory: omitting it never blocks ordinary assessment, Trial review or
finalization. It makes no automatic model call and adds no signalling or risk
rule. A fresh reviewer may find an unsupported factual attribution while
preserving a reasonable contextual inference; neither a valid locator nor a
reviewer's disagreement proves a correction is warranted.

## Prepare the exact handoff

The repository's existing `scripts.export_factual_audit` preparation command
exports one or all saved Domains from a current workspace, without saving a
review or requiring finalization. Its bundle exporter reads verified immutable
bundles. Preparation and structured findings validation are repository utilities,
not additional installed `rob2` CLI commands. See `docs/source-checking.md` in the
repository for their exact invocation. Installed clients can read this reference
through `read_guidance` or `rob2://guidance/source-audit`; `rob2 export-skill`
includes it in the exported skill.

Keep the exact assessment target, reported Result and relation, complete saved
warrants, unknowns, counterevidence, missing-data descriptions and original
source bindings. The reviewer's claims use opaque IDs and withhold signalling
answers and risk metadata; unchanged prose can reveal the author's view.
The separate assessor handoff retains exact accepted checkpoints and answers,
with their identities and routing. Do not supply reference labels, expected
errors or grader feedback. Do not fabricate answers for inactive questions:
only accepted canonical answers are claims. Official guidance for conditional
questions is interpretation, not a request to fill an inactive branch.

Prepared instructions include complete official elaborations for accepted
questions and the selected Domains' shared guidance, with source version, hash
and locators. The reviewer can use `read_guidance` for operational dependencies.
Those documents describe ordinary assessment operations; they do not authorize
an advisory reviewer to perform them. Scientific authority remains with official
Cochrane guidance and the assessor.

## Protect scientific state and recover sources

Use a genuinely fresh host session, not a resumed assessor transcript. Specify
assessor and reviewer settings explicitly and retain effective settings, input
hashes, source identities, actual tool returns, images, failures and usage.
Preparation makes no model call and does not certify eventual delivery.

Protect an isolated copy's captured Sources and canonical/working checkpoints at
the host filesystem boundary. A client `read-only` setting does not itself
constrain a host MCP server. Ordinary source tools can write disposable
navigation, read and pixel-delivery caches; allow those caches separately while
protecting scientific state. The exporter alone supplies no OS isolation. If a
host cannot provide this separation, state the limit before calling the workflow
read-only. Keep original checkpoints immutable and verify their hashes after
review.

All captured Sources remain available through `list_sources`,
`search_sources`/`search_sources_batch`, `read_pages` and `render_page`. Use
complete source access instead of squeezing a large dossier into one prompt.
Investigate uncited context when it can alter a factual attribution. Follow
pagination and continuation markers; a preview, tool success or availability
manifest is not proof of complete reading. Inspect inline pixels when layout or
a figure carries meaning. Preserve original citation support separately from
follow-up support. Do not acquire new sources silently. See
[receipt and source recovery](evidence.md#receipt-and-continuation-recovery) and
[exact Result scope](result.md).

Allow productive investigation without arbitrary source-call caps or silent
truncation. If necessary source context cannot be recovered or retained, record
that specific limitation rather than claim a complete audit. Scientific
diagnostics still follow the repository's frozen evidence and launch protocol;
ordinary advisory use requires the researcher's explicit request.

## Assess findings before changing an answer

The typed report covers every saved claim, including retained facts and
inferences, and distinguishes unsupported attribution, narrower support and
unresolved information. Preserve supported probability and uncertainty;
unavailable individual records do not automatically defeat a qualified
inference. A plan is not demonstrated conduct, and analysis exclusion is not
necessarily measurement cessation. Correct only what the inspected source
warrants, retaining the smallest supported qualification.

Validate the report's exact snapshot, unchanged clause and source bindings with
the existing repository utility. Its receipt checks provenance and report
coverage, not semantic correctness or absence of missed errors. The original
assessor inspects each finding and its sources, accepts or rejects it, and uses
ordinary validated Domain submission with explicit revision lineage only when a
scientific change is warranted. There is no apply operation or automatic answer
change. Closed assessments remain immutable; an advisory report cannot reopen
or overwrite them.
