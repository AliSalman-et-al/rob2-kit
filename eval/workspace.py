"""Manage private real-RCT evaluation projects without leaking reference labels."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

DEFAULT_EVAL_ROOT = Path(__file__).resolve().parent
OUTCOME_LABEL_FILES = {
    "Adverse Events": "adverse-events.csv",
    "Overall Survival": "overall-survival.csv",
    "Progression-Free Survival": "progression-free-survival.csv",
}


@dataclass(frozen=True)
class TrialEntry:
    label: str
    slug: str
    primary: Path
    supplements: Path
    nct_number: str
    outcomes: tuple[str, ...]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _catalog_path(eval_root: Path) -> Path:
    return eval_root / "reference" / "catalog" / "trials.csv"


def _load_trials(eval_root: Path) -> tuple[TrialEntry, ...]:
    catalog = _catalog_path(eval_root)
    if not catalog.is_file():
        raise FileNotFoundError(
            f"private evaluation catalog not found: {catalog}. "
            "See eval/README.md for the expected layout."
        )
    with catalog.open(newline="", encoding="utf-8-sig") as handle:
        rows = tuple(csv.DictReader(handle))
    repo_root = eval_root.parent.resolve()
    private_root = (eval_root / "reference").resolve()
    entries: list[TrialEntry] = []
    for row in rows:
        primary = (repo_root / row["primary_source"].strip()).resolve()
        supplements = (repo_root / row["supplements"].strip()).resolve()
        if not primary.is_relative_to(private_root) or not supplements.is_relative_to(
            private_root
        ):
            raise ValueError(
                f"{catalog}: source path for {row['trial_label']!r} "
                "escapes eval/reference"
            )
        entries.append(
            TrialEntry(
                label=row["trial_label"].strip(),
                slug=row["trial_slug"].strip(),
                primary=primary,
                supplements=supplements,
                nct_number=row["nct_number"].strip(),
                outcomes=tuple(
                    outcome.strip()
                    for outcome in row["outcomes"].split(";")
                    if outcome.strip()
                ),
            )
        )
    return tuple(entries)


def _resolve_trial(entries: tuple[TrialEntry, ...], value: str) -> TrialEntry:
    normalized = _slug(value)
    matches = tuple(
        entry
        for entry in entries
        if normalized in {_slug(entry.label), _slug(entry.slug)}
    )
    if len(matches) != 1:
        available = ", ".join(entry.label for entry in entries)
        raise ValueError(f"unknown or ambiguous Trial {value!r}; choose one of: {available}")
    return matches[0]


def _resolve_outcome(entry: TrialEntry, value: str) -> str:
    normalized = _slug(value)
    matches = tuple(outcome for outcome in entry.outcomes if _slug(outcome) == normalized)
    if len(matches) != 1:
        available = ", ".join(entry.outcomes)
        raise ValueError(
            f"outcome {value!r} is not declared for {entry.label}; "
            f"choose one of: {available}"
        )
    return matches[0]


def _role_for_supporting_source(path: Path) -> str:
    return "protocol" if "protocol" in path.stem.casefold() else "supplement"


def _relative_to_repo(path: Path, eval_root: Path) -> str:
    return path.relative_to(eval_root.parent.resolve()).as_posix()


def list_cases(eval_root: Path) -> None:
    for entry in _load_trials(eval_root):
        availability = "ready" if entry.primary.is_file() else "missing primary"
        print(f"{entry.label} [{entry.nct_number}] — {availability}")
        for outcome in entry.outcomes:
            print(f"  - {outcome}")


def validate(eval_root: Path) -> None:
    entries = _load_trials(eval_root)
    errors: list[str] = []
    labels_root = eval_root / "reference" / "catalog" / "provisional-labels"
    declared = {
        (entry.label, outcome)
        for entry in entries
        for outcome in entry.outcomes
    }
    for entry in entries:
        if not entry.primary.is_file():
            errors.append(f"{entry.label}: missing primary source {entry.primary}")
        if not entry.supplements.is_dir():
            errors.append(f"{entry.label}: missing supplements directory {entry.supplements}")
    for outcome, filename in OUTCOME_LABEL_FILES.items():
        label_path = labels_root / filename
        if not label_path.is_file():
            errors.append(f"missing provisional-label file {label_path}")
            continue
        with label_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = tuple(csv.DictReader(handle))
        for row in rows:
            key = (row["Trial"].strip(), outcome)
            if key not in declared:
                errors.append(
                    f"{label_path.name}: label for undeclared Trial/outcome {key!r}"
                )
    if errors:
        raise ValueError("evaluation workspace is invalid:\n- " + "\n- ".join(errors))
    pdf_count = sum(
        1
        for entry in entries
        for path in (entry.primary, *entry.supplements.glob("*.pdf"))
        if path.is_file()
    )
    print(f"Valid private evaluation workspace: {len(entries)} Trials, {pdf_count} PDFs")


def create_run(
    eval_root: Path,
    *,
    trial_value: str,
    outcome_value: str,
    host: str,
    run_id: str | None,
) -> Path:
    entries = _load_trials(eval_root)
    entry = _resolve_trial(entries, trial_value)
    outcome = _resolve_outcome(entry, outcome_value)
    if not entry.primary.is_file():
        raise FileNotFoundError(f"primary source is missing: {entry.primary}")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = run_id or f"{timestamp}-{_slug(host)}-{entry.slug}-{_slug(outcome)}"
    if Path(name).name != name:
        raise ValueError("run id must be one portable directory name")
    run_root = (eval_root / "runs" / name).resolve()
    expected_runs_root = (eval_root / "runs").resolve()
    if not run_root.is_relative_to(expected_runs_root):
        raise ValueError("run path escapes eval/runs")
    if run_root.exists():
        raise FileExistsError(
            f"evaluation run already exists: {run_root}. Use a new --run-id."
        )

    trial_root = run_root / "input" / entry.slug
    supplements_root = trial_root / "supplements"
    supplements = tuple(sorted(entry.supplements.glob("*.pdf")))
    supplements_root.mkdir(parents=True)
    shutil.copy2(entry.primary, trial_root / entry.primary.name)
    for source in supplements:
        shutil.copy2(source, supplements_root / source.name)

    documents = [
        {"path": entry.primary.name, "roles": ["primary_report"]},
        *[
            {
                "path": f"supplements/{source.name}",
                "roles": [_role_for_supporting_source(source)],
            }
            for source in supplements
        ],
    ]
    trial_manifest = {
        "schema_version": 1,
        "trial": {
            "label": entry.label,
            "registry_id": entry.nct_number,
        },
        "outcome_target": outcome,
        "documents": documents,
    }
    (trial_root / "trial.yaml").write_text(
        yaml.safe_dump(trial_manifest, sort_keys=False),
        encoding="utf-8",
    )
    (run_root / "output").mkdir()
    run_manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "host": host,
        "trial": entry.label,
        "trial_slug": entry.slug,
        "registry_id": entry.nct_number,
        "outcome_target": outcome,
        "source_count": 1 + len(supplements),
        "reference_labels_included": False,
    }
    (run_root / "eval-run.yaml").write_text(
        yaml.safe_dump(run_manifest, sort_keys=False),
        encoding="utf-8",
    )
    relative = _relative_to_repo(run_root, eval_root)
    print(f"Created private evaluation run: {relative}")
    print(f'Initialize: uv run --frozen rob2 init "{relative}" --authorize --json')
    print(
        "Agent boundary: do not inspect "
        "eval/reference/catalog/provisional-labels until the Assessment is complete."
    )
    return run_root


def show_reference(eval_root: Path, *, trial_value: str, outcome_value: str) -> None:
    entries = _load_trials(eval_root)
    entry = _resolve_trial(entries, trial_value)
    outcome = _resolve_outcome(entry, outcome_value)
    filename = OUTCOME_LABEL_FILES.get(outcome)
    if filename is None:
        raise ValueError(f"no provisional-label file is configured for {outcome}")
    label_path = (
        eval_root / "reference" / "catalog" / "provisional-labels" / filename
    )
    with label_path.open(newline="", encoding="utf-8-sig") as handle:
        match = next(
            (
                row
                for row in csv.DictReader(handle)
                if _slug(row["Trial"]) == _slug(entry.label)
            ),
            None,
        )
    if match is None:
        raise ValueError(f"no provisional reference label for {entry.label} / {outcome}")
    print("PROVISIONAL REFERENCE LABEL — not a correctness oracle")
    print(f"Trial: {entry.label}")
    print(f"Outcome: {outcome}")
    print(
        " | ".join(
            f"{field}: {match[field]}"
            for field in ("D1", "D2", "D3", "D4", "D5", "Overall Risk")
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-root",
        type=Path,
        default=DEFAULT_EVAL_ROOT,
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list materializable Trial/outcome cases")
    subparsers.add_parser("validate", help="validate the private corpus layout")
    create = subparsers.add_parser("create", help="materialize a fresh rob2-kit project")
    create.add_argument("--trial", required=True)
    create.add_argument("--outcome", required=True)
    create.add_argument("--host", choices=("codex", "claude"), required=True)
    create.add_argument("--run-id")
    reference = subparsers.add_parser(
        "reference",
        help="show a provisional label after an Assessment is complete",
    )
    reference.add_argument("--trial", required=True)
    reference.add_argument("--outcome", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    eval_root = args.eval_root.resolve()
    if args.command == "list":
        list_cases(eval_root)
    elif args.command == "validate":
        validate(eval_root)
    elif args.command == "create":
        create_run(
            eval_root,
            trial_value=args.trial,
            outcome_value=args.outcome,
            host=args.host,
            run_id=args.run_id,
        )
    else:
        show_reference(
            eval_root,
            trial_value=args.trial,
            outcome_value=args.outcome,
        )


if __name__ == "__main__":
    main()
