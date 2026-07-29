from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from eval.workspace import create_run, show_reference, validate


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def private_workspace(tmp_path: Path) -> Path:
    eval_root = tmp_path / "eval"
    source_root = eval_root / "reference" / "sources" / "TRIAL-A"
    primary = source_root / "primary" / "report.pdf"
    protocol = source_root / "supplements" / "protocol.pdf"
    primary.parent.mkdir(parents=True)
    protocol.parent.mkdir(parents=True)
    primary.write_bytes(b"primary")
    protocol.write_bytes(b"protocol")
    _write_csv(
        eval_root / "reference" / "catalog" / "trials.csv",
        (
            "trial_label",
            "trial_slug",
            "primary_source",
            "supplements",
            "nct_number",
            "outcomes",
        ),
        [
            {
                "trial_label": "TRIAL A",
                "trial_slug": "TRIAL-A",
                "primary_source": "eval/reference/sources/TRIAL-A/primary/report.pdf",
                "supplements": "eval/reference/sources/TRIAL-A/supplements",
                "nct_number": "NCT00000001",
                "outcomes": "Progression-Free Survival",
            }
        ],
    )
    label_fields = ("Trial", "D1", "D2", "D3", "D4", "D5", "Overall Risk")
    labels = eval_root / "reference" / "catalog" / "provisional-labels"
    _write_csv(labels / "adverse-events.csv", label_fields, [])
    _write_csv(labels / "overall-survival.csv", label_fields, [])
    _write_csv(
        labels / "progression-free-survival.csv",
        label_fields,
        [
            {
                "Trial": "TRIAL A",
                "D1": "L",
                "D2": "L",
                "D3": "L",
                "D4": "S",
                "D5": "L",
                "Overall Risk": "Low",
            }
        ],
    )
    return eval_root


def test_materialized_run_excludes_provisional_labels(tmp_path: Path) -> None:
    eval_root = private_workspace(tmp_path)

    validate(eval_root)
    run_root = create_run(
        eval_root,
        trial_value="trial-a",
        outcome_value="progression free survival",
        host="codex",
        run_id="codex-trial-a-pfs",
    )

    run_manifest = yaml.safe_load((run_root / "eval-run.yaml").read_text())
    trial_manifest = yaml.safe_load(
        (run_root / "input" / "TRIAL-A" / "trial.yaml").read_text()
    )
    assert run_manifest["reference_labels_included"] is False
    assert trial_manifest["outcome_target"] == "Progression-Free Survival"
    assert trial_manifest["documents"] == [
        {"path": "report.pdf", "roles": ["primary_report"]},
        {"path": "supplements/protocol.pdf", "roles": ["protocol"]},
    ]
    assert not any(
        "Overall Risk" in path.read_text(errors="ignore")
        for path in run_root.rglob("*")
        if path.is_file()
    )


def test_reference_label_is_a_separate_explicit_action(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    eval_root = private_workspace(tmp_path)

    show_reference(
        eval_root,
        trial_value="TRIAL A",
        outcome_value="Progression-Free Survival",
    )

    output = capsys.readouterr().out
    assert "PROVISIONAL REFERENCE LABEL" in output
    assert "D4: S" in output


def test_catalog_source_paths_cannot_escape_private_reference_root(
    tmp_path: Path,
) -> None:
    eval_root = private_workspace(tmp_path)
    catalog = eval_root / "reference" / "catalog" / "trials.csv"
    catalog.write_text(
        catalog.read_text().replace(
            "eval/reference/sources/TRIAL-A/primary/report.pdf",
            "outside/report.pdf",
        )
    )

    with pytest.raises(ValueError, match="escapes eval/reference"):
        validate(eval_root)
