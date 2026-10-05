from __future__ import annotations

import json
import re
from pathlib import Path

from rob2_kit.workflow_models import (
    DomainInformationLimit,
    DomainSaveAnswer,
    ProposalSelection,
    TrialClosureRequest,
    TrialReviewRequest,
)

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


def test_readme_describes_proposal_receipt_and_atomic_domain_save() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "save_proposal` with the returned `reasoning_id`" not in readme
    assert "save_domain_judgment` with its returned\n`reasoning_id`" not in readme
    assert "unique validated Proposal draft" in readme
    assert "A complete Domain draft validates and commits in one" in readme


def test_evidence_reference_contains_closed_limitation_example() -> None:
    reference = Path("src/rob2_kit/skills/rob2-assess/references/evidence.md").read_text(
        encoding="utf-8"
    )
    examples = re.findall(r"```json\s*(.*?)\s*```", reference, flags=re.DOTALL)
    objects = [json.loads(example) for example in examples]
    limitations = [limit for item in objects for limit in item.get("limitations", [])]
    assert limitations
    for limitation in limitations:
        DomainInformationLimit.model_validate(limitation)
    assert "untruncated zero-hit receipts" in reference


def test_evidence_reference_contains_valid_complete_domain_answer_examples() -> None:
    reference = Path("src/rob2_kit/skills/rob2-assess/references/evidence.md").read_text(
        encoding="utf-8"
    )
    section = reference.split("## Build a Domain answer", 1)[1].split(
        "## Recover an unresolved premise", 1
    )[0]
    examples = re.findall(r"```json\s*(.*?)\s*```", section, flags=re.DOTALL)
    assert len(examples) == 2
    answer = json.loads(examples[0])
    DomainSaveAnswer.model_validate(answer)
    assert {item["role"] for item in answer["bases"]} == {"direct_support"}
    assert answer["unknowns"] == []
    assert answer["counterevidence"] == []
    alternative = json.loads(examples[1])
    parsed = DomainSaveAnswer.model_validate({**answer, **alternative})
    assert {item["kind"] for item in parsed.canonical_payload()["bases"]} == {
        "context",
        "absence",
        "limitation",
    }


def test_read_pages_reference_contains_both_callable_request_forms() -> None:
    reference = Path("src/rob2_kit/skills/rob2-assess/references/read-main-report.md").read_text(
        encoding="utf-8"
    )
    examples = re.findall(r"```json\s*(.*?)\s*```", reference, flags=re.DOTALL)
    single_source = json.loads(examples[0])
    windows = json.loads(examples[1])

    assert set(single_source) == {"trial_id", "source_id", "pages", "start_line"}
    assert single_source["pages"] == [2]
    assert set(windows) == {"trial_id", "windows"}
    assert set(windows["windows"][0]) == {
        "source_id",
        "page",
        "start_line",
        "end_line",
    }
    assert "data.pages[].numbered_text" in reference
    assert "data.remaining_windows" in reference


def test_skill_review_examples_validate_as_tool_requests() -> None:
    skill = Path("src/rob2_kit/skills/rob2-assess/SKILL.md").read_text(encoding="utf-8")
    examples = re.findall(r"```json\s*(.*?)\s*```", skill, flags=re.DOTALL)
    payloads = [json.loads(example) for example in examples]
    normal = next(
        payload
        for payload in payloads
        if "request" not in payload and "review_reference" not in payload
    )
    close = next(payload for payload in payloads if "review_reference" in payload)

    TrialReviewRequest.model_validate(normal)
    TrialClosureRequest.model_validate(close)
    assert "permitted uncertainty answer" in skill
    assert "terminal request" in skill
    assert "supported workflow" in skill
    assert "cannot continue" in skill


def test_result_reference_contains_valid_reasoning_and_receipt_examples() -> None:
    reference = Path("src/rob2_kit/skills/rob2-assess/references/result.md").read_text(
        encoding="utf-8"
    )
    examples = re.findall(r"```json\s*(.*?)\s*```", reference, flags=re.DOTALL)

    assert len(examples) >= 3
    draft = ProposalSelection.model_validate(json.loads(examples[0])["selections"][0])
    assert draft.counterevidence[0].evidence != draft.source_passages[0]
    receipt = json.loads(examples[1])
    assert receipt == {"expected_revision": 8}
    assert draft.candidate is not None
    assert draft.candidate.target_window == "15 days after randomization"


def test_skill_requires_complete_proposal_construction_before_validation() -> None:
    skill = Path("src/rob2_kit/skills/rob2-assess/SKILL.md").read_text(encoding="utf-8")

    assert "Construct the complete request before calling" in skill
    assert "placeholders" in skill
    assert "one complete Trial selection" in skill


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
        "measurement method is appropriate and valid for that approved event",
        "methods, thresholds, schedules, and detection opportunities between randomized groups",
        "who determines whether that event occurred",
        "assessor awareness separately from susceptibility to influence",
        "influence is possible or likely, explain the mechanism",
        "all-cause mortality, distinguish establishing death from judging progression, "
        "symptoms, or cause of death",
        "composite outcomes, inspect the components and their relative frequency or",
        "passage discusses several outcomes, use only the premise that applies to the "
        "approved outcome and state any inference or unresolved link",
    )
    assert all(semantic in items[index + 1] for index, semantic in enumerate(semantic_items))


def test_missing_reference_and_skill_use_official_science_and_preserve_recovery() -> None:
    reference = Path("src/rob2_kit/skills/rob2-assess/references/missing.md").read_text(
        encoding="utf-8"
    )
    skill = Path("src/rob2_kit/skills/rob2-assess/SKILL.md").read_text(encoding="utf-8")
    for asset in (reference, skill):
        assert "official_guidance.sections" in asset
        assert "official_d3_prototype" in asset
        assert "counterevidence" in asset
        assert "missing_data" in asset
    assert "## Availability audit" not in reference
    assert "For D3.1, run the **availability audit**" not in skill
    for term in ("unopened supplements", "read_pages", "basis", "randomized - observed", "scoped"):
        assert term in reference, term
