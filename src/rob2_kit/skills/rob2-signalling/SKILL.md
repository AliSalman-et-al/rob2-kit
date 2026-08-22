---
name: rob2-signalling
description: Answer the server-derived active RoB 2 question wave with source-specific Evidence.
---

# RoB 2 signalling

Resolve the exact work packet. Submit answers only for the `question_wave`
returned by `validate_domain_judgment`; the server owns activation and ordering.
Earlier answers are persisted across waves.

For each question provide:

- the allowed answer token;
- a rationale whose first sentence has the same polarity;
- one or more evidence uses;
- for each evidence use, a literal `source_fact`, a separate `inference`, the
  relationship, and exact Evidence references.

A source fact must establish the proposition or a defensible source-specific
indirect inference. Routine practice, trial reputation, stratification, balanced
baseline groups, similar group sizes, an objective outcome, or lack of reported
problems cannot establish an unreported mechanism or complete follow-up.

In particular:

- allocation concealment needs an explicit concealment mechanism;
- randomized enrollment is not outcome-data coverage;
- intention-to-treat requires a source statement about analysis by assignment;
- selective-reporting answers require protocol, SAP, or registry comparison.

When neither direction has admissible Evidence, use `no_information`. Repair all
returned defects, validate again, read the stored candidate, then commit its
exact Transition. Consume each returned next packet immediately.
