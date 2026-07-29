# Canonical contract ownership

Issue #14 establishes schema ownership without implementing workflows.

| Canonical records | Owning module or follow-up |
| --- | --- |
| IDs, Actor, dependencies, supersession, schema envelopes | `rob2_kit.domain.revisions` |
| Project manifest revision and Outcome target | `rob2_kit.domain.projects` |
| Result and ResultSpec revision | `rob2_kit.domain.results` |
| Source inventory revision and Source components | `rob2_kit.domain.sources`; acquisition, Parse records, Coverage maps: #17 |
| Evidence candidates, claims, facts, bundles, consideration/context manifests | `rob2_kit.domain.evidence`; search index and coverage receipts: #19 |
| Visual transcriptions | `rob2_kit.domain.evidence`; inspection workflow: #20 |
| SQ Answers, judgments, Decision traces, overrides | `rob2_kit.domain.assessment`; evaluation: #15 and #21 |
| Review findings, dispositions, reviewer profiles, sign-off | `rob2_kit.domain.assessment`; human workflow: #22 |
| Assessment revision | `rob2_kit.domain.assessment`; assembly: #21 |
| Preparation attempts/outcomes and Review receipts | `rob2_kit.application.preparation`; workflow: #21/#22 |
| Logic and Guidance pack releases | `rob2_kit.domain.releases`; contents/evaluator: #15 |
| Policy releases and Project rules | `rob2_kit.domain.releases`; policy behavior: #15–#22 |
| Host-neutral operation envelopes | `rob2_kit.application.interfaces`; transports/adapters: #23 |
| Ledger events, artifacts, invalidation | #16 |
