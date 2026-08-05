"""Normalization and semantic comparison for installed MCP replay receipts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# These names are intentionally owned by the installed package rather than by
# the release script.  The script runs from a checkout, while the behaviour it
# qualifies must be supplied by the wheel under test.
RELEASE_LOCKED_OPTIONAL_FIXTURES = (
    "registry_history",
)

def normalize_replay_trace(
    calls: Sequence[Mapping[str, Any]], *, final: Mapping[str, Any]
) -> dict[str, Any]:
    """Replace volatile installed-run handles while retaining request/response order."""

    normalizer = _ReplayNormalizer()
    return {
        "calls": [
            {
                "sequence": index,
                "name": str(call["name"]),
                "arguments": normalizer.value(call.get("arguments", {})),
                "response": normalizer.value(call.get("response", {})),
            }
            for index, call in enumerate(calls, start=1)
        ],
        "final": normalizer.value(dict(final)),
    }


def normalize_semantic_value(value: Any) -> Any:
    """Normalize volatile handles in a durable replay projection."""

    return _ReplayNormalizer().value(value)


def semantic_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Return the fields that must converge across replay variants."""

    return {
        key: receipt[key]
        for key in (
            "run_state",
            "events",
            "revisions",
            "evidence",
            "answers",
            "decision_traces",
            "judgments",
            "report_machine_data",
            "assets",
            "archive_digest",
        )
        if key in receipt
    }


class _ReplayNormalizer:
    _PRESERVED_IDENTITIES = {
        "trial_id",
        "result_id",
        "randomization_id",
        "domain_id",
        "question_id",
        "sq_id",
        "source_id",
        "unit_id",
    }

    def __init__(self) -> None:
        self._handles: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def value(self, value: Any, key: str = "") -> Any:
        if isinstance(value, Mapping):
            return {str(name): self.value(item, str(name)) for name, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(item, key) for item in value]
        if not isinstance(value, str):
            return value
        category = self._category(key, value)
        if category is None:
            return value
        identity = (category, value)
        if identity not in self._handles:
            number = self._counts.get(category, 0) + 1
            self._counts[category] = number
            self._handles[identity] = f"<{category}-{number}>"
        return self._handles[identity]

    @staticmethod
    def _category(key: str, value: str) -> str | None:
        normalized = key.casefold().replace("-", "_")
        if normalized in _ReplayNormalizer._PRESERVED_IDENTITIES:
            return None
        if normalized == "ledger_cursor":
            return "ledger-cursor"
        if normalized in {"project_root", "path", "file_path", "artifact_path"}:
            return "path"
        if normalized.endswith("_token") or normalized in {"token", "work_token"}:
            return "work-token" if "work" in normalized or normalized == "token" else "token"
        if normalized.endswith("_at") or normalized in {"timestamp", "timestamp_utc"}:
            return "timestamp"
        if normalized.endswith("_id"):
            return normalized.removesuffix("_id")
        prefix = value.split(":", 1)[0].casefold() if ":" in value else ""
        return prefix if prefix in {"run", "event", "revision", "artifact", "operation"} else None
