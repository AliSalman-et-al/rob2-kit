"""Build the pinned runtime artifact before the public wheel."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())['project']['version']


def main() -> None:
    output = ROOT / "dist" / "runtime"
    output.mkdir(parents=True, exist_ok=True)
    for stale_wheel in output.glob("rob2_kit*.whl"):
        stale_wheel.unlink()
    embedded = ROOT / "release" / "runtime"
    hidden_root = Path(tempfile.mkdtemp(prefix="rob2-runtime-build-"))
    hidden = hidden_root / "runtime"
    runtime_pin = ROOT / "release" / "runtime-wheel-pin.json"
    hidden_pin = hidden_root / runtime_pin.name
    project_file = ROOT / "pyproject.toml"
    original_project = project_file.read_bytes()
    shutil.move(str(embedded), str(hidden))
    if runtime_pin.exists():
        shutil.move(str(runtime_pin), str(hidden_pin))
    embedded.mkdir(parents=True, exist_ok=True)
    project_for_runtime_build = original_project
    for forced_include in (
        b'"release/runtime" = "rob2_kit/release/runtime"',
        b'"release/runtime-wheel-pin.json" = "rob2_kit/release/runtime-wheel-pin.json"',
    ):
        project_for_runtime_build = project_for_runtime_build.replace(
            forced_include + b"\r\n", b""
        ).replace(forced_include + b"\n", b"")
    project_file.write_bytes(project_for_runtime_build)
    try:
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(output)], cwd=ROOT, check=True)
    finally:
        project_file.write_bytes(original_project)
        if embedded.exists():
            embedded.rmdir()
        shutil.move(str(hidden), str(embedded))
        if hidden_pin.exists():
            shutil.move(str(hidden_pin), str(runtime_pin))
    wheel = next(output.glob("rob2_kit-*.whl"))
    # Keep a wheel-compatible normalized distribution filename; the artifact
    # is separately scoped by its runtime directory and pin, while METADATA
    # remains the canonical rob2-kit distribution.
    runtime = output / wheel.name
    if wheel.resolve() != runtime.resolve():
        shutil.copyfile(wheel, runtime)
    runtime_root = ROOT / "release" / "runtime"
    for stale_wheel in runtime_root.glob("rob2_kit*.whl"):
        stale_wheel.unlink()
    embedded = runtime_root / runtime.name
    shutil.copyfile(runtime, embedded)
    runtime_project = runtime_root / "pyproject.toml"
    runtime_project.write_text(
        "[project]\nname = \"rob2-kit-project-runtime\"\n"
        f"version = \"{VERSION}\"\nrequires-python = \">=3.13\"\n"
        f"dependencies = [\"rob2-kit=={VERSION}\"]\n\n"
        "[tool.uv]\npackage = false\n\n[tool.uv.sources]\n"
        f"rob2-kit = {{ path = \"{runtime.name}\" }}\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["uv", "lock", "--refresh", "--project", str(ROOT / "release" / "runtime")],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pin_release_wheel.py"), str(runtime)],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(ROOT / "dist")],
        cwd=ROOT,
        check=True,
    )
    main_wheel = next((ROOT / "dist").glob("rob2_kit-*.whl"))
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pin_release_wheel.py"), str(main_wheel)],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
