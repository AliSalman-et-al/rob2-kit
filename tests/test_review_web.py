import json
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from rob2_kit.application.gateway import ApplicationGateway
from rob2_kit.review.service import ReviewService
from rob2_kit.review.web import ReviewWebConfig, create_review_app
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    Transition,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)
from tests.test_ingestion import StubParser, page
from tests.test_review_service import NOW, case, reviewer, service


def client(tmp_path: Path) -> tuple[TestClient, str]:
    review = service(tmp_path, case())
    config = ReviewWebConfig(
        project_root=tmp_path.resolve(),
        session_lifetime=timedelta(minutes=30),
        allowed_origin="http://testserver",
    )
    app, token = create_review_app(review, config)
    return TestClient(app), token


def companion_client(tmp_path: Path) -> tuple[TestClient, str]:
    review = service(tmp_path, case())
    secured_pdf = review.ledger.artifacts.put(
        b"%PDF-1.4\n% secured first page\n",
        "application/pdf",
    )
    initialization = {
        "project_id": "project:critical-care",
        "root": str(tmp_path),
        "authorized": True,
        "initialization": {
            "manifest": {
                "project_name": "Critical care review",
                "input_root": str(tmp_path),
                "output_root": str(tmp_path / "outputs"),
                "state_root": str(tmp_path / ".rob2"),
            },
            "trials": [
                {
                    "trial_id": "trial:ready",
                    "status": "inventory_ready",
                    "inventory": {
                        "inventory_id": "inventory:ready",
                        "trial_id": "trial:ready",
                        "coverage_limitations": [],
                        "sources": [
                            {
                                "source_id": "source:ready-primary",
                                "title": "primary-report.pdf",
                                "relative_path": "primary-report.pdf",
                                "roles": ["primary_report"],
                                "criticality": "required",
                                "classification": {
                                    "authority": "folder_position",
                                    "cues": ["top-level PDF"],
                                    "classifier_version": "1",
                                },
                                "availability": "acquired",
                                "processing": "usable",
                                "artifact_hash": secured_pdf.content_hash,
                                "coverage": [
                                    {
                                        "page_index": 0,
                                        "state": "text_usable",
                                        "diagnostics": [],
                                        "recovery_attempted": False,
                                    },
                                    {
                                        "page_index": 1,
                                        "state": "text_usable",
                                        "diagnostics": [],
                                        "recovery_attempted": False,
                                    },
                                ],
                            }
                        ],
                    },
                    "failure": None,
                },
                {
                    "trial_id": "trial:failed",
                    "status": "trial_failed",
                    "inventory": {
                        "inventory_id": "inventory:failed",
                        "trial_id": "trial:failed",
                        "coverage_limitations": ["primary report unavailable"],
                        "sources": [
                            {
                                "source_id": "source:failed-primary",
                                "title": "Required primary report",
                                "relative_path": ".",
                                "roles": ["primary_report"],
                                "criticality": "required",
                                "classification": {
                                    "authority": "folder_position",
                                    "cues": ["no top-level PDF"],
                                    "classifier_version": "1",
                                },
                                "availability": "unavailable",
                                "processing": "not_attempted",
                                "coverage": [],
                            }
                        ],
                    },
                    "failure": {
                        "outcome": "trial_failed",
                        "trial_id": "trial:failed",
                        "reason": "required_primary_unrecoverable",
                        "detail": "No top-level primary-report candidate was supplied",
                    },
                },
            ],
            "acquisition_receipts": [],
            "review_findings": [],
        },
        "preparation_plans": [
            {
                "scope": "preparation:ready",
                "trial_id": "trial:ready",
                "steps": [
                    {
                        "step_id": "step:source-classification",
                        "operation": "operation:submit-source-classification",
                        "checkpoint": "checkpoint:source-classification",
                        "submission_kind": "source_classification",
                    },
                    {
                        "step_id": "step:result-resolution",
                        "operation": "operation:submit-result-resolution",
                        "checkpoint": "checkpoint:result-resolution",
                        "submission_kind": "result_resolution",
                    },
                ],
            }
        ],
    }
    review.ledger.commit(
        Transition(
            scope="project:critical-care",
            operation="operation:initialize-project",
            operation_key="idempotency:initialize-critical-care",
            actor=reviewer(),
            observed_at=NOW,
            entity_id="authorization:critical-care",
            revision_id="revision:critical-care-authorization",
            artifact=json.dumps(initialization).encode(),
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        review.lease,
        now=NOW,
    )
    config = ReviewWebConfig(
        project_root=tmp_path.resolve(),
        session_lifetime=timedelta(minutes=30),
        allowed_origin="http://testserver",
    )
    app, token = create_review_app(review, config)
    return TestClient(app), token


def enter_review(browser: TestClient, token: str) -> str:
    exchange = browser.get(f"/review?token={token}", follow_redirects=False)
    assert exchange.status_code == 303
    assert "HttpOnly" in exchange.headers["set-cookie"]
    assert "SameSite=strict" in exchange.headers["set-cookie"]
    assert "token=" not in exchange.headers["location"]
    page = browser.get(exchange.headers["location"])
    assert page.status_code == 200
    return page.text


def csrf_from(page: str) -> str:
    marker = 'name="csrf_token" value="'
    return page.split(marker, 1)[1].split('"', 1)[0]


def declared_result(result_id: str, outcome: str, time_point: str) -> dict[str, object]:
    return {
        "result": {
            "result_id": result_id,
            "trial_id": "trial:trial-a",
            "randomization_id": "randomization:trial-a",
            "comparison": {
                "experimental_arm_id": "arm:treatment",
                "comparator_arm_id": "arm:control",
            },
            "effect_of_interest": "assignment",
            "outcome_construct": outcome,
            "measurement_instrument": "Hospital record",
            "time_point": time_point,
            "analysis_population": "Intention to treat",
            "analysis_model": "Risk ratio, unadjusted",
            "effect_measure": "RR",
            "source_locator": f"report.pdf {outcome} table",
        },
        "estimate": {"value": "0.82"},
        "provenance_note": "Declared before autonomous preparation.",
    }


class AccessibilityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.label_depth = 0
        self.html_language: str | None = None
        self.landmarks: set[str] = set()
        self.live_regions = 0
        self.alerts = 0
        self.unlabelled_controls: list[str] = []
        self.buttons_without_text = 0
        self._button_text: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "html":
            self.html_language = attributes.get("lang")
        if tag in {"header", "main"}:
            self.landmarks.add(tag)
        if attributes.get("aria-live"):
            self.live_regions += 1
        if attributes.get("role") == "alert":
            self.alerts += 1
        if tag == "label":
            self.label_depth += 1
        if (
            tag in {"input", "textarea"}
            and attributes.get("type") != "hidden"
            and not self.label_depth
            and not attributes.get("aria-label")
        ):
            self.unlabelled_controls.append(attributes.get("name", tag))
        if tag == "button":
            self._button_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self.label_depth -= 1
        if tag == "button" and self._button_text is not None:
            if not "".join(self._button_text).strip():
                self.buttons_without_text += 1
            self._button_text = None

    def handle_data(self, data: str) -> None:
        if self._button_text is not None:
            self._button_text.append(data)


def test_one_time_token_exchanges_for_secured_session_and_cannot_be_reused(
    tmp_path: Path,
) -> None:
    browser, token = client(tmp_path)

    enter_review(browser, token)
    reused = TestClient(browser.app).get(f"/review?token={token}", follow_redirects=False)

    assert reused.status_code == 401


def test_evidence_is_inert_and_answer_stays_hidden_until_confirmation(
    tmp_path: Path,
) -> None:
    browser, token = client(tmp_path)

    page = enter_review(browser, token)

    assert "&lt;script&gt;alert(&#39;source&#39;)&lt;/script&gt;" in page
    assert "<script>alert('source')</script>" not in page
    assert "Probably yes" not in page
    assert 'href="javascript:' not in page
    assert "default-src 'none'" in browser.get("/review").headers[
        "content-security-policy"
    ]
    assert 'class="review-layout"' in page
    assert "Mortality at 30 days" in page
    assert "Draft-only hands-on preview" in page
    assert "Only a human reviewer can sign off" in page


def test_ready_workspace_shows_exact_result_sources_and_copyable_prompt(
    tmp_path: Path,
) -> None:
    browser, token = companion_client(tmp_path)

    page = enter_review(browser, token)

    assert "Ready" in page
    assert "trial:ready · Result identity pending" in page
    assert "primary-report.pdf" in page
    assert "primary report" in page
    assert "2 pages" in page
    assert "acquired" in page
    assert "usable" in page
    assert "First-page preview of primary-report.pdf" in page
    assert "Start uninterrupted autonomous preparation" in page
    assert "Queue" in page
    assert "No top-level primary-report candidate was supplied" in page
    assert "Repair or replace the required source or Result information" in page
    assert "Required primary report</strong>" not in page
    preview = browser.get("/review/sources/source:ready-primary")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.content.startswith(b"%PDF-1.4")


def test_real_initialized_project_shows_every_declared_exact_result_in_ready(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "results": [
                    declared_result(
                        "result:trial-a-mortality-30d",
                        "Mortality",
                        "30 days",
                    ),
                    declared_result(
                        "result:trial-a-readmission-90d",
                        "Readmission",
                        "90 days",
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    gateway = ApplicationGateway(
        parser=StubParser({"report": (page(1, "Trial report"),)})
    )
    initialized = gateway.initialize_project(tmp_path, authorized=True)
    ledger = WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3",
        ArtifactStore(tmp_path / ".rob2" / "artifacts"),
    )
    app, token = create_review_app(
        None,
        ReviewWebConfig(
            project_root=tmp_path.resolve(),
            session_lifetime=timedelta(minutes=30),
            allowed_origin="http://testserver",
        ),
        ledger=ledger,
    )

    browser = TestClient(app)
    page_text = enter_review(browser, token)

    assert "trial:trial-a · Mortality · 30 days" in page_text
    assert "trial:trial-a · Readmission · 90 days" in page_text
    assert "Result identity pending" not in page_text
    assert page_text.count("1 secured source") == 2
    assert page_text.count("Waiting for autonomous preparation to begin") == 2

    first_work = initialized.payload["work_item"]
    gateway.call(
        "submit_source_classification",
        initialized.payload["project_id"],
        arguments={
            "classifications": [
                {"source_id": "source:trial-a-1", "roles": ["primary_report"]}
            ]
        },
        mutation_context={
            "idempotency_key": "idempotency:classify-first-result",
            "work_item_id": first_work["work_item_id"],
            "contract_version": "1.0.0",
            "expected_dependency_fingerprint": first_work["dependency_fingerprint"],
        },
    )
    prepared = browser.get("/review").text

    assert prepared.count("Waiting for autonomous preparation to begin") == 1
    assert prepared.count("No judgment has been committed") == 1


def test_prepare_workspace_uses_durable_state_and_never_implies_an_early_judgment(
    tmp_path: Path,
) -> None:
    browser, token = companion_client(tmp_path)
    review = browser.app.state.review_service
    review.ledger.commit(
        Transition(
            scope="preparation:ready",
            operation="operation:submit-source-classification",
            operation_key="idempotency:interrupted-ready",
            actor=reviewer(),
            observed_at=NOW,
            entity_id="source-classification:ready",
            revision_id="revision:source-classification-ready",
            artifact=b'{"status":"interrupted"}',
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            outcome=WorkflowEventOutcome.RETRYABLE_INTERRUPTION,
        ),
        review.lease,
        now=NOW,
    )

    page = enter_review(browser, token)
    refreshed = browser.get("/review").text
    resumed = ReviewService(review.ledger, review.lease, case())
    resumed_app, resumed_token = create_review_app(
        resumed,
        ReviewWebConfig(
            project_root=tmp_path.resolve(),
            session_lifetime=timedelta(minutes=30),
            allowed_origin="http://testserver",
        ),
    )
    reconnected = enter_review(TestClient(resumed_app), resumed_token)

    assert "Processing" in page
    assert "No judgment has been committed" in page
    assert "Assessment committed" not in page
    assert "Preparation was interrupted safely" in page
    assert "Human review locked" in page
    assert "Resume uninterrupted autonomous preparation" in page
    assert refreshed.count("Preparation was interrupted safely") == 1
    assert reconnected.count("Preparation was interrupted safely") == 1


def test_prepare_workspace_keeps_incomplete_result_reason_and_recovery_visible(
    tmp_path: Path,
) -> None:
    browser, token = companion_client(tmp_path)
    review = browser.app.state.review_service
    review.ledger.commit(
        Transition(
            scope="preparation:ready",
            operation="operation:derive-assessment",
            operation_key="idempotency:incomplete-ready",
            actor=reviewer(),
            observed_at=NOW,
            entity_id="preparation-outcome:ready",
            revision_id="revision:preparation-incomplete-ready",
            artifact=json.dumps(
                {
                    "outcome": "preparation_incomplete",
                    "reason": "material_evidence_gap",
                    "detail": "The analysis population could not be resolved.",
                }
            ).encode(),
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            checkpoint="checkpoint:preparation-outcome",
            outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
        ),
        review.lease,
        now=NOW,
    )

    page_text = enter_review(browser, token)

    assert "preparation incomplete" in page_text
    assert "The analysis population could not be resolved." in page_text
    assert "Resolve the material preparation gap, then resume preparation." in page_text


def test_ready_selection_uses_the_committed_exact_result_identity(tmp_path: Path) -> None:
    browser, token = companion_client(tmp_path)
    review = browser.app.state.review_service
    result_spec = {
        "entity_id": "result-spec:ready",
        "revision_id": "revision:result-spec-ready",
        "actor": reviewer().model_dump(mode="json"),
        "observed_at": NOW.isoformat(),
        "dependencies": [],
        "result": {
            "result_id": "result:ready",
            "trial_id": "trial:ready",
            "randomization_id": "randomization:ready",
            "comparison": {
                "experimental_arm_id": "arm:intervention",
                "comparator_arm_id": "arm:control",
            },
            "effect_of_interest": "assignment",
            "outcome_construct": "Mortality",
            "measurement_instrument": "All-cause death",
            "time_point": "30 days",
            "analysis_population": "Intention to treat",
            "analysis_model": "Risk ratio",
            "effect_measure": "RR",
            "source_locator": "primary-report.pdf p. 8 table 2",
        },
        "estimate": {"value": "0.82"},
        "provenance_note": "Resolved from the primary report.",
    }
    review.ledger.commit(
        Transition(
            scope="preparation:ready",
            operation="operation:submit-result-resolution",
            operation_key="idempotency:result-ready",
            actor=reviewer(),
            observed_at=NOW,
            entity_id="result-spec:ready",
            revision_id="revision:result-spec-ready",
            artifact=json.dumps(result_spec).encode(),
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            checkpoint="checkpoint:result-resolution",
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        review.lease,
        now=NOW,
    )

    page = enter_review(browser, token)

    assert "trial:ready · Mortality · 30 days" in page
    assert "arm:intervention vs arm:control" in page
    assert "randomization:ready" in page
    assert "All-cause death" in page
    assert "Intention to treat" in page
    assert "Risk ratio" in page
    assert "primary-report.pdf p. 8 table 2" in page
    assert "Last durable checkpoint:" in page
    assert "checkpoint:result-resolution" in page


def test_rendered_critical_flow_has_accessible_controls_and_status(
    tmp_path: Path,
) -> None:
    browser, token = client(tmp_path)
    parser = AccessibilityParser()
    parser.feed(enter_review(browser, token))

    assert parser.html_language == "en"
    assert parser.landmarks == {"header", "main"}
    assert parser.live_regions >= 1
    assert parser.alerts == 0
    assert parser.unlabelled_controls == []
    assert parser.buttons_without_text == 0


def test_csrf_origin_and_stale_forms_are_rejected_without_a_commit(tmp_path: Path) -> None:
    browser, token = client(tmp_path)
    page = enter_review(browser, token)
    csrf = csrf_from(page)
    action = {
        "csrf_token": csrf,
        "action_id": "review-action:finding-1",
        "kind": "verify_evidence",
        "expected_assessment_revision_id": "revision:assessment-1",
        "idempotency_key": "idempotency:web-evidence",
        "value": "accepted",
        "rationale": "Checked source.",
    }

    bad_origin = browser.post("/review/actions", data=action, headers={"Origin": "https://evil.test"})
    bad_csrf = browser.post(
        "/review/actions",
        data={**action, "csrf_token": "wrong"},
        headers={"Origin": "http://testserver"},
    )
    stale = browser.post(
        "/review/actions",
        data={**action, "expected_assessment_revision_id": "revision:old"},
        headers={"Origin": "http://testserver"},
    )

    assert bad_origin.status_code == 403
    assert bad_csrf.status_code == 403
    assert stale.status_code == 409
    assert "read-only" in stale.text


def test_double_click_is_idempotent_and_reopen_reveals_staged_answer(
    tmp_path: Path,
) -> None:
    browser, token = client(tmp_path)
    page = enter_review(browser, token)
    action = {
        "csrf_token": csrf_from(page),
        "action_id": "review-action:finding-1",
        "kind": "verify_evidence",
        "expected_assessment_revision_id": "revision:assessment-1",
        "idempotency_key": "idempotency:web-evidence",
        "value": "accepted",
        "rationale": "Checked source.",
    }

    first = browser.post(
        "/review/actions",
        data=action,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    second = browser.post(
        "/review/actions",
        data=action,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    reopened = browser.get("/review")

    assert first.status_code == second.status_code == 303
    assert "Probably yes" in reopened.text
    review_events = [
        event
        for event in browser.app.state.review_service.ledger.events()
        if event.operation.startswith("review:")
    ]
    assert len(review_events) == 1
