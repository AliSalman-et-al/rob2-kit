"""Generate authoritative wheel provenance after a release build."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path


def main() -> None:
    wheel = Path(sys.argv[1]).resolve()
    metadata_name = next(
        name
        for name in zipfile.ZipFile(wheel).namelist()
        if name.endswith(".dist-info/METADATA")
    )
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(metadata_name).decode()
    fields = dict(line.split(": ", 1) for line in metadata.splitlines() if ": " in line)
    if fields.get("Name", "").casefold() != "rob2-kit":
        raise SystemExit("wheel is not rob2-kit")
    pin = {
        "filename": wheel.name,
        "version": fields["Version"],
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }
    pin_name = "runtime-wheel-pin.json" if wheel.parent.name == "runtime" else "wheel-pin.json"
    target = Path(__file__).parents[1] / "release" / pin_name
    target.write_text(json.dumps(pin, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
