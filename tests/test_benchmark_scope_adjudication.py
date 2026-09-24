from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def scope_adjudication(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    scripts = Path(__file__).parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "benchmark_scope_adjudication.py"))


def test_scope_adjudication_requires_all_frozen_identities(
    scope_adjudication: dict[str, Any], tmp_path: Path
) -> None:
    expected = {"trial": "trial-a", "estimate": "0.75"}
    expected_hash = scope_adjudication["expected_result_sha256"](expected)
    row = {
        "outcome": "Overall Survival",
        "trial": "TRIAL-A",
        "expected_result_sha256": expected_hash,
        "review_identity": "sha256:review",
        "result_identity": "sha256:result",
        "observed_relation": "exact",
        "decision": "equivalent",
        "rationale": "The reviewed value is the same estimate with equivalent formatting.",
        "source_citation": "Main article abstract, p. 1.",
    }
    path = tmp_path / "scope-adjudications.json"
    path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-scope-adjudications.v2",
                "adjudications": [row],
            }
        ),
        encoding="utf-8",
    )
    rows = scope_adjudication["load_scope_adjudications"](path)

    match = scope_adjudication["matching_scope_adjudication"]
    assert match(
        rows,
        outcome="Overall Survival",
        trial="TRIAL-A",
        expected_result=expected,
        review_identity="sha256:review",
        result_identity="sha256:result",
        relation="exact",
    ) == row
    assert match(
        rows,
        outcome="Overall Survival",
        trial="TRIAL-A",
        expected_result={**expected, "estimate": "0.76"},
        review_identity="sha256:review",
        result_identity="sha256:result",
        relation="exact",
    ) is None
    assert match(
        rows,
        outcome="Overall Survival",
        trial="TRIAL-A",
        expected_result=expected,
        review_identity="sha256:old-review",
        result_identity="sha256:result",
        relation="exact",
    ) is None
    assert match(
        rows,
        outcome="Overall Survival",
        trial="TRIAL-A",
        expected_result=expected,
        review_identity="sha256:review",
        result_identity="sha256:old-result",
        relation="exact",
    ) is None


def test_scope_adjudication_rejects_malformed_decision(
    scope_adjudication: dict[str, Any], tmp_path: Path
) -> None:
    path = tmp_path / "scope-adjudications.json"
    path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-scope-adjudications.v2",
                "adjudications": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "TRIAL-A",
                        "expected_result_sha256": "0" * 64,
                        "review_identity": "sha256:review",
                        "result_identity": "sha256:result",
                        "observed_relation": "exact",
                        "decision": "correction_required",
                        "rationale": "Not an equivalence.",
                        "source_citation": "Main article abstract, p. 1.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported scope adjudication decision"):
        scope_adjudication["load_scope_adjudications"](path)


def test_scope_adjudication_accepts_only_broader_or_related_scope_differences(
    scope_adjudication: dict[str, Any], tmp_path: Path
) -> None:
    expected = {"trial": "TRIAL-A"}
    base = {
        "outcome": "Overall Survival",
        "trial": "TRIAL-A",
        "expected_result_sha256": scope_adjudication["expected_result_sha256"](expected),
        "review_identity": "sha256:review",
        "result_identity": "sha256:result",
        "rationale": "The source supports the accepted relation.",
        "source_citation": "Main article, p. 1.",
        "decision": "accepted_with_scope_difference",
        "observed_relation": "broader",
    }
    path = tmp_path / "scope-adjudications.json"
    path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-scope-adjudications.v2",
                "adjudications": [base],
            }
        ),
        encoding="utf-8",
    )

    rows = scope_adjudication["load_scope_adjudications"](path)
    assert rows == [base]
    assert scope_adjudication["matching_scope_adjudication"](
        rows,
        outcome="Overall Survival",
        trial="TRIAL-A",
        expected_result=expected,
        review_identity="sha256:review",
        result_identity="sha256:result",
        relation="broader",
    ) == base
    assert scope_adjudication["matching_scope_adjudication"](
        rows,
        outcome="Overall Survival",
        trial="TRIAL-A",
        expected_result=expected,
        review_identity="sha256:review",
        result_identity="sha256:result",
        relation="related",
    ) is None

    for relation in ("exact", "narrower", "component"):
        invalid = {**base, "observed_relation": relation}
        path.write_text(
            json.dumps(
                {
                    "schema": "rob2-kit.benchmark-scope-adjudications.v2",
                    "adjudications": [invalid],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="broader or related"):
            scope_adjudication["load_scope_adjudications"](path)
