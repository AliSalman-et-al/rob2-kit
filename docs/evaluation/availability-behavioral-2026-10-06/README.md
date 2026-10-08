# DELIVER availability evidence archive

This index preserves access to the October 6, 2026 frozen DELIVER availability experiment. The complete original protocol, source projections, images, review packets, terminal receipt and unblinding records remain unchanged at the already-published immutable commit [bd92fc767fd0a532a5291b694b84983378dccb2f](https://github.com/AliSalman-et-al/rob2-kit/tree/bd92fc767fd0a532a5291b694b84983378dccb2f/docs/evaluation/availability-behavioral-2026-10-06).

The commit is retained independently of this draft by the existing remote experiment branch `improve/registry-evidence-navigation-20261007` (verified at `972b4eb478ff9e8674dbee73a866a7176558df23`). Keep this ref when pruning experiment branches.

[The exact manifest](archive-manifest.json) records the size and SHA256 of all 461 original files: 425 text projections, 15 PNGs and 21 protocol/review/index files. This index and manifest replace the working-tree archive for packaging only; they are not inputs to the original frozen seals. This cleanup provides no new scientific result or accuracy claim.

## Restore and verify

From a clone containing the retained experiment ref, restore into a new disposable directory:

```sh
git fetch origin improve/registry-evidence-navigation-20261007
mkdir deliver-archive-restored
git archive bd92fc767fd0a532a5291b694b84983378dccb2f docs/evaluation/availability-behavioral-2026-10-06 | tar -x -C deliver-archive-restored
```

Run from this index directory, adjusting the restoration path if necessary:

```python
import hashlib
import json
from pathlib import Path

manifest = json.loads(Path("archive-manifest.json").read_text(encoding="utf-8"))
restored = Path("deliver-archive-restored") / manifest["archive_directory"]
assert len(list(p for p in restored.rglob("*") if p.is_file())) == manifest["file_count"]
for row in manifest["files"]:
    data = (restored / row["path"]).read_bytes()
    assert len(data) == row["bytes"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"]
```

Read the restored original README and frozen review/unblinding records together. Their relative links resolve within the complete restored tree. Historical reports elsewhere in the repository are unchanged.
