"""Regenerate distributable JSON Schemas from the runtime pack validators."""

import json
from pathlib import Path

from rob2_kit.logic.packs import GuidancePack, LogicPack


def main() -> None:
    root = Path(__file__).parents[1] / "schemas"
    for filename, model in (
        ("logic-pack.schema.json", LogicPack),
        ("guidance-pack.schema.json", GuidancePack),
    ):
        rendered = json.dumps(
            model.model_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        (root / filename).write_text(f"{rendered}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
