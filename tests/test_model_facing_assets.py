from __future__ import annotations

import re
from pathlib import Path

MODEL_FACING_PATHS = (
    Path("README.md"),
    Path("CONTEXT.md"),
    Path("docs/evaluation/README.md"),
    Path("docs/release/README.md"),
    Path("docs/release/public-contract.json"),
    Path("src/rob2_kit/hosts"),
    Path("src/rob2_kit/interfaces/mcp"),
    Path("src/rob2_kit/skills"),
    Path("src/rob2_kit/workflow_models.py"),
)
PRIVATE_EVALUATION_TERMS = re.compile(
    r"CHAARTED|STAMPEDE|TITAN|progression[-_ ]free|\bPFS\b|overall[_ -]survival|"
    r"NCT00309985|docetaxel|castration|prostate|androgen deprivation|\bADT\b|"
    r"adverse[-_ ]events?",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {".json", ".md", ".py"}


def _model_facing_files() -> list[Path]:
    files: list[Path] = []
    for path in MODEL_FACING_PATHS:
        if path.is_dir():
            files.extend(
                item for item in path.rglob("*") if item.is_file() and item.suffix in TEXT_SUFFIXES
            )
        else:
            files.append(path)
    return files


def test_model_facing_assets_do_not_contain_private_evaluation_terms() -> None:
    leaked: dict[str, list[str]] = {}
    for path in _model_facing_files():
        content = path.read_text(encoding="utf-8")
        matches = PRIVATE_EVALUATION_TERMS.findall(content)
        if matches:
            leaked[str(path)] = sorted(set(matches))
    assert leaked == {}


def test_domain_references_use_current_handle_only_evidence_contract() -> None:
    references = Path("src/rob2_kit/skills/rob2-assess/references")
    stale = {
        str(path): "source field"
        for path in references.glob("*.md")
        if re.search(
            r"Evidence use `source`|copy the exact selected `source`",
            path.read_text(encoding="utf-8"),
        )
    }
    assert stale == {}


def test_measurement_reference_keeps_ordered_outcome_specific_audit() -> None:
    normalized = " ".join(
        Path("src/rob2_kit/skills/rob2-assess/references/measurement.md")
        .read_text(encoding="utf-8")
        .split()
    )
    markers = list(re.finditer(r"(?<!\w)([1-9])\.\s+", normalized))
    start = next(
        index
        for index in range(len(markers) - 8)
        if [int(marker.group(1)) for marker in markers[index : index + 9]] == list(range(1, 10))
    )
    markers = markers[start : start + 9]
    items = {
        number: normalized[
            marker.end() : markers[index + 1].start()
            if index + 1 < len(markers)
            else len(normalized)
        ]
        for index, marker in enumerate(markers[:9])
        for number in [int(marker.group(1))]
    }
    semantic_items = (
        "approved Result's event definition and ascertainment method",
        "measurement method is appropriate for that approved event",
        "methods, thresholds, schedules, and detection opportunities between randomized groups",
        "who determines whether that event occurred",
        "assessor awareness separately from susceptibility to influence",
        "influence is possible or likely, explain the mechanism",
        "all-cause mortality, distinguish establishing death from judging progression, "
        "symptoms, or cause of death",
        "composite outcomes, consider every component that can determine the event",
        "passage discusses several outcomes, use only the premise that applies to the "
        "approved outcome and state any inference or unresolved link",
    )
    assert all(semantic in items[index + 1] for index, semantic in enumerate(semantic_items))
