"""Build and verify one fresh wheel, never an artifact left by an earlier release."""

from __future__ import annotations

import subprocess
import tempfile
import tomllib
from pathlib import Path


def build_release_wheel(root: Path) -> Path:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    parent = root / ".release-dist"
    parent.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="wheel-", dir=parent))
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(output)], cwd=root, check=True)
    name = project["name"].replace("-", "_")
    wheel = output / f"{name}-{project['version']}-py3-none-any.whl"
    if not wheel.is_file() or list(output.glob("*.whl")) != [wheel]:
        raise ValueError("Release build must produce exactly the current project wheel")
    subprocess.run(
        ["uv", "run", "python", "docs/release/verify.py", "--wheel", str(wheel)],
        cwd=root,
        check=True,
    )
    return wheel


if __name__ == "__main__":
    print(f"Verified freshly built wheel: {build_release_wheel(Path.cwd())}")
