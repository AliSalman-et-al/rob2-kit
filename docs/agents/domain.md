# Domain Docs

## Before changing domain terms or decisions, read these

- Root `CONTEXT.md`, if present
- Root `CONTEXT-MAP.md`, if present, followed by relevant context documents
- Relevant ADRs under `docs/adr/`

Read these files only for domain-modeling work. If a referenced file does not exist, continue without it.

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
