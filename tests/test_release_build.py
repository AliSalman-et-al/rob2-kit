import configparser
import subprocess
import zipfile
from pathlib import Path


def test_wheel_contains_required_package_content_and_declared_entry_points(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points_path = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = configparser.ConfigParser()
        entry_points.read_string(archive.read(entry_points_path).decode())

    assert "rob2_kit/packs/logic/rob2-parallel-assignment-2019.1.yaml" in names
    assert "rob2_kit/packs/guidance/rob2-parallel-assignment-en-2019.1.yaml" in names
    assert "rob2_kit/schemas/logic-pack.schema.json" in names
    assert "rob2_kit/schemas/guidance-pack.schema.json" in names
    assert "rob2_kit/skills/rob2-init/SKILL.md" in names
    assert "rob2_kit/skills/rob2-assess/SKILL.md" in names
    assert "rob2_kit/rob2.lock" in names
    assert set(entry_points["console_scripts"]) >= {"rob2", "rob2-mcp", "rob2-build-adapters"}
    assert not any(
        name.startswith(
            (
                "rob2_kit/review/",
                "rob2_kit/application/gateway",
                "rob2_kit/application/interfaces",
            )
        )
        for name in names
    )
