from __future__ import annotations

import html
import json
import runpy
import zipfile
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

import pytest
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _finalize_assessment,
    _standalone_verify,
)
from test_bundle_verifier import _rewrite_zip, _update_manifest_hash

from rob2_kit.application._state import _state
from rob2_kit.application.finalization import _human_report, verify_bundle
from rob2_kit.logic.evaluator import evaluate_domain
from rob2_kit.packs import SCIENTIFIC_PACK


@pytest.fixture(scope="module", params=["no_information", "probably_yes", "probably_no"])
def assessed_report(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> tuple[Path, dict, dict, str]:
    tmp_path = tmp_path_factory.mktemp("human-report")
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        draft = _domain_draft("trial", domain.id, revision, evidence)
        if domain.id == "domain:missing":
            for answer in draft["answers"]:
                answer["answer"] = {
                    "sq:missing:data-available": "no",
                    "sq:missing:evidence-unbiased": "no",
                    "sq:missing:true-value-dependent": "yes",
                    "sq:missing:likely-dependent": request.param,
                }[answer["question_id"]]
                answer["justification"] = (
                    "Incomplete observed follow-up leaves dependence unresolved."
                )
                answer["unknowns"] = ["Observed outcomes for noncompleters remain unknown."]
                answer["bases"].append(
                    {
                        "kind": "limitation",
                        "unresolved_premise": (
                            "Reasons for unavailable outcome values are not established."
                        ),
                        "stopping_rationale": "The selected report does not resolve those reasons.",
                    }
                )
        elif domain.id == "domain:selection":
            for answer in draft["answers"]:
                if answer["question_id"] == "sq:selection:multiple-measurements":
                    answer["answer"] = "probably_no"
                    answer["justification"] = (
                        "No competing eligible measurement was established; this remains qualified."
                    )
        saved = _call(workspace, "save_domain_judgment", draft)
        assert saved["outcome"] == "success", saved
        revision = saved["head"]["state_revision"]
    original_records = deepcopy(_state(workspace)["domain_records"])
    finalized = _finalize_assessment(workspace, revision)
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / finalized["data"]["artifact"]["path"]
    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        claims = json.loads(archive.read("claims.json"))
        report = archive.read("report.html").decode()
    assert canonical["domain_records"] == original_records
    return artifact, canonical, claims, report


def test_report_preserves_original_answers_warrants_and_precautionary_route(
    assessed_report: tuple[Path, dict, dict, str],
) -> None:
    artifact, canonical, claims, report = assessed_report
    assert canonical["report_format"] == "rob2-kit.human-report.v1"
    record = canonical["domain_records"]["trial:domain:missing"]
    answer = next(
        item for item in record["answers"] if item["question_id"].endswith("likely-dependent")
    )
    assert record["judgment"] == ("some_concerns" if answer["answer"] == "probably_no" else "high")
    domain_report = report.split("<h3>domain:missing</h3>")[1].split("<h3>", 1)[0]
    assert ("The recorded algorithm route includes a No information answer." in domain_report) == (
        answer["answer"] == "no_information"
    )
    assert html.escape(answer["justification"]) in report
    assert "Reasons for unavailable outcome values are not established." in report
    assert "Observed outcomes for noncompleters remain unknown." in report
    assert "Probably no</h4>" in report
    assert "No competing eligible measurement was established; this remains qualified." in report
    assert "Algorithm rule identifiers describe derivations, not empirical findings." in report
    assert "Approved Result: target, reported result and scope" in report
    assert _human_report(canonical, claims) == report
    independent = runpy.run_path("scripts/verify_bundle.py")["_human_report"]
    assert independent(canonical, claims) == report
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0


def test_rehashed_html_warrant_tampering_is_rejected(
    assessed_report: tuple[Path, dict, dict, str],
    tmp_path: Path,
) -> None:
    artifact, _canonical, _claims, report = assessed_report
    changed = report.replace(
        "Incomplete observed follow-up leaves dependence unresolved.",
        "Missingness was proven harmless.",
    ).encode()
    assert changed != report.encode()
    with zipfile.ZipFile(artifact) as archive:
        manifest = archive.read("manifest.json")
    tampered = tmp_path / "report-tamper.rob2.zip"
    _rewrite_zip(
        artifact,
        tampered,
        {
            "report.html": changed,
            "manifest.json": _update_manifest_hash(manifest, "report.html", changed),
        },
    )
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1


def test_report_format_rejects_legacy_downgrade_and_marker_stripping(
    assessed_report: tuple[Path, dict, dict, str],
    tmp_path: Path,
) -> None:
    artifact, canonical, claims, _report = assessed_report
    legacy = (
        "<html><body><h1>Batch finalized</h1><pre>"
        + json.dumps(claims, sort_keys=True)
        + "</pre></body></html>"
    ).encode()
    with zipfile.ZipFile(artifact) as archive:
        manifest = archive.read("manifest.json")
    downgraded = tmp_path / "legacy-downgrade.rob2.zip"
    changed_manifest = _update_manifest_hash(manifest, "report.html", legacy)
    _rewrite_zip(artifact, downgraded, {"report.html": legacy, "manifest.json": changed_manifest})
    assert not verify_bundle(downgraded)
    assert _standalone_verify(downgraded).returncode == 1

    unmarked = deepcopy(canonical)
    unmarked.pop("report_format")
    changed_canonical = json.dumps(unmarked, sort_keys=True, separators=(",", ":")).encode()
    stripped = tmp_path / "marker-stripped.rob2.zip"
    _rewrite_zip(
        artifact,
        stripped,
        {
            "report.html": legacy,
            "canonical.json": changed_canonical,
            "manifest.json": _update_manifest_hash(
                changed_manifest, "canonical.json", changed_canonical
            ),
        },
    )
    assert not verify_bundle(stripped)
    assert _standalone_verify(stripped).returncode == 1


def test_unresolved_route_member_does_not_imply_it_determined_the_judgment() -> None:
    answers = {
        "sq:missing:data-available": "no",
        "sq:missing:evidence-unbiased": "no",
        "sq:missing:true-value-dependent": "no_information",
        "sq:missing:likely-dependent": "probably_no",
    }
    evaluation = evaluate_domain("domain:missing", answers)
    clarified = evaluate_domain(
        "domain:missing",
        {
            **answers,
            "sq:missing:true-value-dependent": "probably_yes",
        },
    )
    assert evaluation == clarified
    assert evaluation.judgment.value == "some_concerns"
    assert "sq:missing:true-value-dependent" in evaluation.driver_questions
    canonical = {
        "proposal": {"payload": {"results": []}, "evidence": {}},
        "batch": {"trials": []},
        "dispositions": {"trial": "assessed"},
        "domain_records": {
            "trial:domain:missing": {
                "trial_id": "trial",
                "domain_id": "domain:missing",
                "judgment": evaluation.judgment.value,
                "trace": list(evaluation.trace),
                "driver_questions": list(evaluation.driver_questions),
                "answers": [
                    {"question_id": question, "answer": answer}
                    for question, answer in answers.items()
                ],
            }
        },
    }
    claims = {"authoritative_wording": "Rendering counterexample", "overall": {}}
    report = _human_report(canonical, claims)
    assert "The recorded algorithm route includes a No information answer." in report
    assert "That premise remains unresolved" in report
    assert "the recorded rule&#x27;s response to unresolved information" not in report
    assert "The proposed judgment is" not in report
    independent = runpy.run_path("scripts/verify_bundle.py")["_human_report"]
    assert independent(canonical, claims) == report


@pytest.mark.parametrize("render_identity", ["sha256:" + "c" * 64, "javascript:alert(1)"])
def test_report_escapes_untrusted_text_and_uses_only_local_evidence_links(
    render_identity: str,
) -> None:
    identity = "sha256:" + "a" * 64
    figure_identity = "sha256:" + "b" * 64
    malicious = '<script>alert("x")</script><a href="javascript:alert(1)">x</a>'
    canonical = {
        "proposal": {
            "payload": {"results": []},
            "evidence": {
                identity: {
                    "identity": identity,
                    "kind": "narrative",
                    "source_id": "source",
                    "page": 3,
                    "start_line": 9,
                    "end_line": 12,
                    "quote": malicious,
                },
                figure_identity: {
                    "identity": figure_identity,
                    "kind": "figure",
                    "source_id": "source",
                    "render": {"identity": render_identity, "page": 7},
                    "region": [0.1, 0.2, 0.6, 0.9],
                    "transcription": malicious,
                },
            },
        },
        "batch": {
            "trials": [{"sources": [{"id": "source", "sha256": identity, "label": malicious}]}]
        },
        "dispositions": {malicious: "assessed"},
        "domain_records": {
            "record": {
                "trial_id": malicious,
                "domain_id": "domain:missing",
                "judgment": "high",
                "answers": [
                    {
                        "question_id": "sq:missing:likely-dependent",
                        "answer": "no_information",
                        "justification": malicious,
                        "unknowns": [malicious],
                        "bases": [{"evidence": identity}, {"evidence": "javascript:alert(1)"}],
                    }
                ],
                "driver_questions": ["sq:missing:likely-dependent"],
                "trace": ["missing.likely_dependent"],
            }
        },
    }
    claims = {"authoritative_wording": malicious, "overall": {malicious: "high"}}
    report = _human_report(canonical, claims)
    assert malicious not in report
    assert html.escape(malicious) in report
    assert "&quot;page&quot;: 3" in report
    assert "&quot;start_line&quot;: 9" in report
    assert "&quot;end_line&quot;: 12" in report

    class Links(HTMLParser):
        references: list[str]

        def __init__(self) -> None:
            super().__init__()
            self.references = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            assert tag != "script"
            for key, value in attrs:
                assert not key.startswith("on")
                if key in {"href", "src"}:
                    assert value is not None
                    self.references.append(value)

    parsed = Links()
    parsed.feed(report)
    expected = {
        "#evidence-" + "a" * 64,
        "evidence/" + "a" * 64 + ".json",
        "evidence/" + "b" * 64 + ".json",
    }
    if render_identity.startswith("sha256:"):
        expected.add("visual/" + "c" * 64 + ".png")
    assert set(parsed.references) == expected
