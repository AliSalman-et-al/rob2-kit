"""Resumable loopback server lifecycle and activity-aware review waiting."""

from __future__ import annotations

import secrets
import socket
import webbrowser
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from threading import Event, Thread
from time import monotonic

import uvicorn
from pydantic import BaseModel, ConfigDict

from rob2_kit.review.service import DurableReviewReceipt, ReviewService
from rob2_kit.review.web import ReviewWebConfig, create_review_app

LOOPBACK_HOST = "127.0.0.1"


class OpenReviewResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    browser_opened: bool
    connection_state: str
    project_root: Path


class ReviewWaitOutcome(StrEnum):
    RECEIPT_AVAILABLE = "receipt_available"
    REVIEW_PENDING = "review_pending"


class ReviewWaitResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: ReviewWaitOutcome
    receipt: DurableReviewReceipt | None = None


class ReviewHandoff:
    """Open, reconnect to, and wait on a review process without model inference."""

    def __init__(
        self,
        review_service: ReviewService,
        web_config: ReviewWebConfig,
        *,
        browser_open: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        self.review_service = review_service
        self.web_config = web_config
        self.browser_open = browser_open
        self._server: uvicorn.Server | None = None
        self._thread: Thread | None = None
        self._url: str | None = None
        self._app = None
        self._origin: str | None = None

    def open_review(self, *, start_server: bool = True) -> OpenReviewResult:
        if self._url is None:
            listener = _loopback_listener()
            port = listener.getsockname()[1]
            origin = f"http://{LOOPBACK_HOST}:{port}"
            config = self.web_config.model_copy(update={"allowed_origin": origin})
            app, token = create_review_app(self.review_service, config)
            self._app = app
            self._origin = origin
            self._url = f"{origin}/review?token={token}"
            if start_server:
                server_config = uvicorn.Config(
                    app,
                    host=LOOPBACK_HOST,
                    port=port,
                    log_level="warning",
                    access_log=False,
                )
                self._server = uvicorn.Server(server_config)
                self._thread = Thread(
                    target=self._server.run,
                    kwargs={"sockets": [listener]},
                    daemon=True,
                    name="rob2-review-server",
                )
                self._thread.start()
            else:
                listener.close()
        elif self._app is not None and self._origin is not None:
            token = secrets.token_urlsafe(32)
            self._app.state.bootstrap_token = token
            self._url = f"{self._origin}/review?token={token}"
        try:
            opened = bool(self.browser_open(self._url))
        except OSError:
            opened = False
        if not opened:
            self.review_service.mark_reconnect_needed()
        return OpenReviewResult(
            url=self._url,
            browser_opened=opened,
            connection_state=self.review_service.connection_state().value,
            project_root=self.web_config.project_root,
        )

    def wait_for_review(
        self,
        *,
        after_sequence: int,
        inactivity_timeout: timedelta,
        cancelled: Event | None = None,
    ) -> ReviewWaitResult:
        inactivity_seconds = max(0.0, inactivity_timeout.total_seconds())
        poll_interval = min(0.1, max(0.01, inactivity_seconds / 4))
        last_contact = self.review_service.last_contact()
        deadline = monotonic() + inactivity_seconds
        cancel_event = cancelled or Event()
        while not cancel_event.is_set() and monotonic() < deadline:
            receipt = self.review_service.latest_receipt(after_sequence=after_sequence)
            if receipt is not None:
                return ReviewWaitResult(
                    outcome=ReviewWaitOutcome.RECEIPT_AVAILABLE,
                    receipt=receipt,
                )
            current_contact = self.review_service.last_contact()
            if current_contact > last_contact:
                last_contact = current_contact
                deadline = monotonic() + inactivity_seconds
            cancel_event.wait(
                min(poll_interval, max(0.0, deadline - monotonic()))
            )
        return ReviewWaitResult(outcome=ReviewWaitOutcome.REVIEW_PENDING)

    def close(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.review_service.mark_disconnected()


def _loopback_listener() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((LOOPBACK_HOST, 0))
    listener.listen()
    return listener
