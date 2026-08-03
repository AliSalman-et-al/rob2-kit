# rob2-kit

> **Draft-only hands-on preview.** This is not a public-v1 release. Only a
> human reviewer can sign off an exact Assessment revision.

Install the locked project-local Codex and Claude Code adapters, then verify the
exact execution contract:

```powershell
uv run --locked --project . rob2 bootstrap .
uv run --locked --project . rob2 doctor .
```

Start the locked Windows preview from the repository root:

```powershell
uv run --locked --project . rob2 doctor
```

See [the hands-on preview gate](docs/HANDS-ON-PREVIEW.md) for the dual-host
verification and feedback checklist.

To show exact Trial × Result identities in the Companion Ready view before
Preparation begins, see [declaring exact Results](docs/RESULT-DECLARATIONS.md).
