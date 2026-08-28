# Public release contract

`public-contract.json` is generated from the typed application models exposed by
the production FastMCP adapter. It records the ordered tool catalog, annotation
policy, resource families, portable skill pointers, and canonical input-schema
hashes for both the constructible input and structured output schemas.

Regenerate it with:

```powershell
uv run python -m rob2_kit.contract_manifest --output docs/release/public-contract.json
```

The verifier regenerates the manifest before checking either the local adapter
or an installed wheel, so the checked file and packaged runtime cannot drift.

Finalized bundles also bind the exact scientific-pack ID, version, content
hash, and official-source hash. The dependency-free
`scripts/verify_bundle.py` pins the same descriptor so an independent consumer
can reject a bundle produced under different scientific guidance. Update that
descriptor only when the scientific pack changes, and update its acceptance and
tamper tests in the same change.

The dependency-free verifier is distributed with the repository and tagged
source releases, not inside the wheel. Wheel-only installations provide
`rob2 verify`; independent verification uses `scripts/verify_bundle.py` from
the matching tagged source release.

The verifier is deliberately independent of the server implementation. It
checks the local boundary or a supplied wheel. For a wheel it installs into a
fresh virtual environment and queries the real stdio process, so a packaged
catalog, schema, resource, or console-entry-point drift fails closed.

Run the complete release check with:

```powershell
./scripts/verify_v03.ps1
```

That script regenerates the public contract, runs lint, type checks, and the
parallel test suite, builds the wheel, and verifies the installed artifact.
The lower-level commands remain available for isolated contract work:

```powershell
uv run python docs/release/verify.py
uv build --wheel --out-dir dist
uv run python docs/release/verify.py --wheel dist/rob2_kit-0.3.0-py3-none-any.whl
```
