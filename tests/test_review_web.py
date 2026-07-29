from datetime import timedelta
from html.parser import HTMLParser
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
