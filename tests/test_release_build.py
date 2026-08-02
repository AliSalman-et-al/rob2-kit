import subprocess
import zipfile
from pathlib import Path


def test_wheel_ships_pack_sources_and_schemas(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "rob2_kit/packs/logic/rob2-parallel-assignment-2019.1.yaml" in names
    assert "rob2_kit/packs/guidance/rob2-parallel-assignment-en-2019.1.yaml" in names
    assert "rob2_kit/schemas/logic-pack.schema.json" in names
    assert "rob2_kit/schemas/guidance-pack.schema.json" in names
