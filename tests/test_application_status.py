from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rob2_kit.application.status import status_json


def test_cli_and_status_projection_match_on_restart(tmp_path: Path) -> None:
    expected = json.loads(status_json(tmp_path))
    environment = os.environ.copy()
    environment["ROB2_WORKSPACE"] = str(tmp_path)
    first = subprocess.check_output(
        [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "status"],
        env=environment,
        text=True,
    )
    second = subprocess.check_output(
        [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "status"],
        env=environment,
        text=True,
    )
    assert json.loads(first) == expected == json.loads(second)
