# Repository instructions

Keep the active implementation small and direct. Prefer obvious typed code, avoid
speculative abstractions and compatibility layers, and delete retired assumptions
when behavior changes. Tests should cover meaningful public behavior rather than
implementation details. Preserve researcher inputs and completed outputs; do not
perform destructive repository operations unless explicitly requested.

Issues are tracked in GitHub. Use `gh issue view <number> --comments` to read a
ticket, and use the five-role labels documented in `docs/agents/triage-labels.md`.
Read root `CONTEXT.md` and relevant `docs/adr/` files before changing the domain.
