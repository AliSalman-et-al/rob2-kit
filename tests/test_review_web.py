from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from rob2_kit.review.web import ReviewWebConfig, create_review_app
from tests.test_review_service import case, service


def client(tmp_path: Path) -> tuple[TestClient, str]:
    review = service(tmp_path, case())
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
