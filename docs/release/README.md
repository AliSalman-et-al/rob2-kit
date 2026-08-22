# Public release contract

`public-contract.json` is generated from the typed application models exposed by
the production FastMCP adapter. It records the ordered tool catalog, annotation
policy, resource families, portable skill pointers, and canonical input-schema
hashes.

Regenerate it with:

```powershell
uv run python -m rob2_kit.contract_manifest --output docs/release/public-contract.json
```

The verifier regenerates the manifest before checking either the local adapter
or an installed wheel, so the checked file and packaged runtime cannot drift.

The verifier is deliberately independent of the server implementation. It
checks the local boundary or a supplied wheel. For a wheel it installs into a
fresh virtual environment and queries the real stdio process, so a packaged
catalog, schema, resource, or console-entry-point drift fails closed.

```powershell
uv run python docs/release/verify.py
uv build --wheel --out-dir dist
uv run python docs/release/verify.py --wheel dist/rob2_kit-0.2.0-py3-none-any.whl
```
