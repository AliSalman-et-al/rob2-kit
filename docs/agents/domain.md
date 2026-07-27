# Domain Docs

## Before exploring, read these

- Root `CONTEXT.md`, if present
- Root `CONTEXT-MAP.md`, if present, followed by relevant context documents
- Relevant ADRs under `docs/adr/`

If these files do not exist, proceed silently. The domain-modeling workflow creates them lazily when terminology or decisions are resolved.

## File structure

This is a single-context repository:

```text
/
├── CONTEXT.md
├── docs/adr/
└── src/
```

## Vocabulary and decisions

Use terminology defined in `CONTEXT.md` rather than introducing synonyms. If a proposed change conflicts with an existing ADR, surface that conflict explicitly instead of silently overriding the decision.
