import json
import os
import subprocess
import sys
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


def test_clean_wheel_install_exposes_declared_entry_points(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "rob2_kit/skills/rob2-init/SKILL.md" in names
    assert "rob2_kit/skills/rob2-assess/SKILL.md" in names
    assert "rob2_kit/rob2.lock" in names

    environment = tmp_path / "clean-venv"
    subprocess.run(
        ["uv", "venv", str(environment), "--python", sys.executable],
        check=True,
        capture_output=True,
        text=True,
    )
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    requirements = tmp_path / "locked-requirements.txt"
    subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--all-groups",
            "--no-emit-project",
            "--no-emit-workspace",
            "--no-header",
            "--no-annotate",
            "--output-file",
            str(requirements),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "-r", str(requirements)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import importlib.metadata, json; "
                "dist = importlib.metadata.distribution('rob2-kit'); "
                "print(json.dumps(sorted(ep.name for ep in dist.entry_points)))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(json.loads(result.stdout)) >= {
        "rob2",
        "rob2-mcp",
        "rob2-build-adapters",
    }
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    for entry_point in ("rob2", "rob2-mcp", "rob2-build-adapters"):
        assert any(
            (scripts / suffix).is_file()
            for suffix in (entry_point, f"{entry_point}.exe", f"{entry_point}.cmd")
        )
    rob2_script = next(
        scripts / suffix
        for suffix in ("rob2", "rob2.exe", "rob2.cmd")
        if (scripts / suffix).is_file()
    )
    subprocess.run([str(rob2_script), "--help"], check=True, capture_output=True, text=True)
