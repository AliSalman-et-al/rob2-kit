from datetime import timedelta
from pathlib import Path
from threading import Event

from rob2_kit.review.handoff import ReviewHandoff, ReviewWaitOutcome
from rob2_kit.review.service import ActionKind, ReviewService
from rob2_kit.review.web import ReviewWebConfig
from tests.test_review_service import case, command, service


def config(tmp_path: Path) -> ReviewWebConfig:
    return ReviewWebConfig(
        project_root=tmp_path.resolve(),
        session_lifetime=timedelta(minutes=30),
        allowed_origin="http://127.0.0.1:0",
    )


def test_browser_launch_failure_returns_loopback_fallback_url(tmp_path: Path) -> None:
    review = service(tmp_path, case())
    handoff = ReviewHandoff(
        review,
        config(tmp_path),
        browser_open=lambda _url: False,
    )

    opened = handoff.open_review(start_server=False)
    reconnected = handoff.open_review(start_server=False)

    assert opened.url.startswith("http://127.0.0.1:")
    assert reconnected.url != opened.url
    assert opened.browser_opened is False
    assert opened.connection_state == "reconnect needed"
    assert opened.project_root == tmp_path.resolve()


def test_disconnect_is_informational_and_committed_review_survives_recreation(
    tmp_path: Path,
) -> None:
    original = service(tmp_path, case())
    original.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:durable-evidence",
        )
    )
    original.mark_disconnected()
    resumed = ReviewService(original.ledger, original.lease, case())

    assert original.connection_state().value == "not connected—review saved"
    assert resumed.latest_receipt().review_action_id == "review-action:finding-1"
    assert next(
        item
        for item in resumed.queue()
        if item.action_id == "review-action:finding-1"
    ).answer_visible


def test_wait_for_review_is_cancellable_and_returns_pending_without_model_work(
    tmp_path: Path,
) -> None:
    review = service(tmp_path, case())
    handoff = ReviewHandoff(review, config(tmp_path), browser_open=lambda _url: True)
    cancelled = Event()
    cancelled.set()

    result = handoff.wait_for_review(
        after_sequence=0,
        inactivity_timeout=timedelta(seconds=1),
        cancelled=cancelled,
    )

    assert result.outcome is ReviewWaitOutcome.REVIEW_PENDING
    assert result.receipt is None
