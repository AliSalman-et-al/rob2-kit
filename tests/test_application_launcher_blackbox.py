from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_rob2_assess_help_is_available_without_a_host(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "assess", "--help"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--host" in completed.stdout
    assert "--prompt-file" in completed.stdout
