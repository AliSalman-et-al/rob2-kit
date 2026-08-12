# ADR-0024: Retire v2 Evidence-navigation compatibility

## Status

Accepted.

## Decision

Current HEAD supports only the v3 Evidence-navigation state contract,
`evidence-navigation-state:3.0.0`, Search policy `policy:evidence-search-4.0.0`,
and Read policy `policy:evidence-read-3.0.0`. It does not decode, migrate,
resume, alias, or dual-write v2 state or tokens. Unsupported state and retired
token kinds direct callers to supersede Preparation. Current-kind tokens with a
different policy binding fail as stale policy, rather than being reinterpreted.

Historical v2 audit inspection requires checkout of immutable decoder-bearing
commit `6f279e1b8d2de1a76ea5061060a5036c2153c675`.

## Consequences

The release makes a deliberate compatibility break in exchange for one active
schema, one active policy identity, and no hidden decoder attack surface.
ADR-0024 supersedes only ADR-0023's promise to decode v2 in the current
release; ADR-0023 remains an accurate historical record.
