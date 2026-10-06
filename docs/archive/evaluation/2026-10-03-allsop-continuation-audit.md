# Allsop incomplete-run continuation audit

This is an offline audit of the preserved [completion check](2026-10-03-allsop-completion-b54db92/README.md), not a new paid run.

At frozen code `b54db92`, exact `gpt-6-luna` Medium saved D1, fetched only the first D2 context page, attempted premature finalization, and voluntarily returned an incomplete final response. No diagnostic budget fired. All D2–D5 checkpoints, Trial review/closure, and exported artifact remained absent. The server correctly refused finalization.

The D2 header was page zero of five, with no question cards and a non-null pending cursor. Its `section: complete` described the header section, while `head.next_action` named `get_domain_context` and the exact unfinished Trial/Domain but omitted the cursor and page budget. A host following that authoritative action alone would restart context rather than continue the pending sequence. The rejection likewise returned a bare context action. These are demonstrated transport ambiguities; they do not establish the cause of the model's early stop. The existing skill already required following every `next_cursor`, and the model had done so for D1.

The correction retains the same ordered delivery state and scientific basis:

- Pending context heads carry the exact next cursor and byte budget.
- Context-page `delivery_status` explicitly distinguishes incomplete from complete delivery; header section names retain their existing meaning.
- Status and non-context tool receipts recover a pending page only for the next unfinished Trial/Domain and a current Source/Result/pack/Domain checkpoint basis. Preview-only contexts do not become default continuation targets.
- Skill and workflow documentation distinguish delivered context from assessed Domains and finalized Batches.

No scientific answers, Cochrane rules, completion gates, or production token limits changed. Production has no cumulative model-input cap: its limits govern recoverable source/context transport; external hosts own model usage policy. The standalone diagnostic launcher's token guards are separate.

Validation: all 33 bounded-context tests passed after the typed page/action changes. Focused controls exercise pending status, rejected finalization and save, exact continuation, final-page status, advancement to D2, stale revised contexts, and existing source-delivery/recovery tests. Ruff and `ty check src/rob2_kit` pass. A broad unscoped `ty check` also examined archived diagnostic scripts and reported 113 diagnostics outside the production check; those unrelated files were not changed.

No completion or accuracy gain is claimed. Behavioral completion requires a separately authorized bounded model check; the earlier endpoint/result matching and unsupported temporal adjective issues remain unresolved.
