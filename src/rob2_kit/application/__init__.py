"""Typed public application boundary for durable Run coordination."""

from rob2_kit.application.lifecycle import (
    RESULT_TRANSITIONS,
    RUN_TRANSITIONS,
    ResultState,
    RunState,
)


def __getattr__(name: str):
    """Load contract/engine exports lazily to keep ingestion importable.

    ``ingestion.project`` uses the preparation models, which imports the
    ``rob2_kit.application`` package.  Eagerly importing contracts here would
    re-enter ``ingestion.project`` while it is still defining its models.
    """

    if name in {"RUN_OPERATION_CONTRACTS", "RUN_OPERATION_NAMES", "RunOperation"}:
        from rob2_kit.application.contracts import (
            RUN_OPERATION_CONTRACTS,
            RUN_OPERATION_NAMES,
            RunOperation,
        )

        return {
            "RUN_OPERATION_CONTRACTS": RUN_OPERATION_CONTRACTS,
            "RUN_OPERATION_NAMES": RUN_OPERATION_NAMES,
            "RunOperation": RunOperation,
        }[name]
    if name == "RunEngine":
        from rob2_kit.application.run_engine import RunEngine

        return RunEngine
    raise AttributeError(name)

__all__ = [
    "RESULT_TRANSITIONS",
    "RUN_OPERATION_CONTRACTS",
    "RUN_OPERATION_NAMES",
    "RUN_TRANSITIONS",
    "ResultState",
    "RunEngine",
    "RunOperation",
    "RunState",
]
