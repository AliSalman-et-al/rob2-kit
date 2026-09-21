from __future__ import annotations

import json
import re
from pathlib import Path

from rob2_kit.workflow_models import (
    DescribedTiming,
    DomainLimitationBasis,
    DomainReasoningAnswer,
    ProposalReasoningDraft,
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


def test_evidence_reference_contains_closed_limitation_example() -> None:
    reference = Path("src/rob2_kit/skills/rob2-assess/references/evidence.md").read_text(
        encoding="utf-8"
    )
    examples = re.findall(r"```json\s*(.*?)\s*```", reference, flags=re.DOTALL)
    limitations = [
        json.loads(line)
        for example in examples
        for line in example.splitlines()
        if '"kind":"limitation"' in line or '"kind": "limitation"' in line
    ]
    assert len(limitations) >= 2
    assert {"search_receipt" in limitation for limitation in limitations} >= {True, False}
    for limitation in limitations:
        assert set(limitation) <= {
            "kind",
            "unresolved_premise",
            "stopping_rationale",
            "search_receipt",
        }
        DomainLimitationBasis.model_validate(limitation)
    assert "actual receipt returned" in reference


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
    DomainReasoningAnswer.model_validate(answer)
    assert {item["kind"] for item in answer["bases"]} == {"direct_support"}
    assert answer["unknowns"] == []
    assert answer["counterevidence"] == []
    basis_shapes = [json.loads(line) for line in examples[1].splitlines()]
    assert {item["kind"] for item in basis_shapes} == {"context", "absence", "limitation"}
    for item in basis_shapes:
        DomainReasoningAnswer.model_validate(
            {
                **answer,
                "bases": [item],
                "counterevidence": [],
            }
        )


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
    draft = ProposalReasoningDraft.model_validate_json(examples[0])
    assert (
        draft.assessments[0].counterevidence[0].evidence != draft.assessments[0].evidence_basis[0]
    )
    receipt = json.loads(examples[1])
    assert receipt == {
        "expected_revision": 8,
        "reasoning_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
    described = re.search(r"`(\{\"kind\": \"described\".*?\})`", reference)
    assert described is not None
    DescribedTiming.model_validate_json(described.group(1))


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
        "composite outcomes, consider every component that can determine the event",
        "passage discusses several outcomes, use only the premise that applies to the "
        "approved outcome and state any inference or unresolved link",
    )
    assert all(semantic in items[index + 1] for index, semantic in enumerate(semantic_items))


def test_missing_reference_and_skill_share_the_availability_audit() -> None:
    reference = Path("src/rob2_kit/skills/rob2-assess/references/missing.md").read_text(
        encoding="utf-8"
    )
    reference_lines = reference.splitlines()
    start = reference_lines.index("## Availability audit") + 1
    end = next(
        index
        for index in range(start, len(reference_lines))
        if reference_lines[index].startswith("## ")
    )
    bullets: list[str] = []
    continuation = False
    for line in reference_lines[start:end]:
        if line.startswith("- "):
            bullets.append(line.removeprefix("- ").strip())
            continuation = True
        elif not line.strip():
            continuation = False
        elif continuation:
            bullets[-1] = f"{bullets[-1]} {line.strip()}"
    normalized_bullets = [item.casefold() for item in bullets]
    assert any(
        "observed-outcome counts" in item and "randomized" in item for item in normalized_bullets
    )
    assert any(
        "loss-to-follow-up" in item and "censoring" in item and "accounting" in item
        for item in normalized_bullets
    )
    assert any("complete or nearly complete" in item for item in normalized_bullets)
    shortcut_requirements = (
        ("analysis denominators", "itt membership"),
        ("planned", "scheduled", "follow-up"),
        ("treatment continuation", "discontinuation"),
        ("generic censoring rule", "actual rates", "follow-up accounting"),
    )
    assert all(
        any(all(term in item for term in requirement) for item in normalized_bullets)
        for requirement in shortcut_requirements
    )

    skill = Path("src/rob2_kit/skills/rob2-assess/SKILL.md").read_text(encoding="utf-8")
    skill_lines = skill.splitlines()
    skill_start = skill_lines.index("### 6. Audit and commit the Domain once") + 1
    skill_end = next(
        index
        for index in range(skill_start, len(skill_lines))
        if skill_lines[index].startswith("### ")
    )
    audit = " ".join(line.strip() for line in skill_lines[skill_start:skill_end]).casefold()
    assert audit.count("availability audit") == 1
    assert "yes/probably yes needs actual outcome-availability evidence" in audit
    assert "analysis membership" in audit
    assert "planned or scheduled follow-up" in audit
    assert "treatment continuation or discontinuation" in audit
    assert "generic censoring rule alone do not suffice" in audit
