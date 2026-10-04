"""Review scientific-content changes between native checkpoint attempts, never merge them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _content(checkpoint: object) -> dict[str, object]:
    if not isinstance(checkpoint, dict):
        return {}
    steps = checkpoint.get("result_account")
    # Inspect rejected wrapper shapes; this is a diagnostic, not accepted input.
    if isinstance(steps, dict):
        steps = steps.get("steps")
    if not isinstance(steps, list):
        return {}
    content: dict[str, object] = {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        name = str(step.get("id", index))
        observation = step.get("observation")
        if isinstance(observation, dict):
            for field in ("text", "scope"):
                if field in observation:
                    content[f"{name}.observation.{field}"] = observation[field]
        for field in ("inference", "unknowns", "counterevidence", "counts"):
            if field in step:
                content[f"{name}.{field}"] = step[field]
    return content


def review_checkpoint_repairs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep exact attempted requests and explicit deltas from existing native receipts.

    No parser acceptance, source certification, scientific inference or retention
    policy is applied. Only completed attempts are compared; no separate ledger.
    """
    attempts: list[dict[str, Any]] = []
    prior_by_trial: dict[str, dict[str, Any]] = {}
    for event in events:
        item = event.get("item", {})
        if event.get("type") != "item.completed" or item.get("tool") != "save_working_checkpoint":
            continue
        checkpoint = item.get("arguments", {}).get("checkpoint")
        current = _content(checkpoint)
        trial = checkpoint.get("trial_id") if isinstance(checkpoint, dict) else None
        previous = prior_by_trial.get(trial) if isinstance(trial, str) else None
        prior = _content(previous["checkpoint"]) if previous else {}
        changes = [
            {
                "path": path,
                "before": prior.get(path),
                "after": current.get(path),
                "kind": "removed"
                if path not in current
                else "added"
                if path not in prior
                else "changed",
            }
            for path in sorted(prior.keys() | current.keys())
            if prior.get(path) != current.get(path) or (path in prior) != (path in current)
        ]
        attempts.append(
            {
                "item_id": item.get("id"),
                "checkpoint": checkpoint,
                "receipt": item.get("result"),
                "error": item.get("error"),
                "scientific_content_changes": changes if previous else [],
            }
        )
        if isinstance(trial, str):
            prior_by_trial[trial] = attempts[-1]
    return attempts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    args = parser.parse_args()
    events = [json.loads(line) for line in args.events.read_text().splitlines()]
    print(json.dumps(review_checkpoint_repairs(events), indent=2))
