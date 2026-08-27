from __future__ import annotations

from pathlib import Path
from typing import Any

from rob2_kit.application._state import _state


def _state_proposal(workspace: Path) -> dict[str, Any]:
    return _state(workspace)["proposal"]["payload"]
