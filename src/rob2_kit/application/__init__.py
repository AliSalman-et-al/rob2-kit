"""The shared, adapter-independent application boundary."""

from typing import Any

from . import _legacy_init as _legacy
from .bootstrap import install_runtime_hardening

__all__ = _legacy.__all__


def __getattr__(name: str) -> Any:
    return getattr(_legacy, name)


install_runtime_hardening()
