"""Secured loopback HTTP boundary for direct human review."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import BaseModel, ConfigDict

from rob2_kit.domain.revisions import Actor, ActorKind, RecordReference
from rob2_kit.review.service import (
    ActionKind,
    ReviewCommand,
    ReviewError,
    ReviewService,
    SignOffBlockedError,
    StaleReviewError,
)

SESSION_COOKIE = "rob2_review_session"
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


class ReviewWebConfig(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    project_root: Path
    session_lifetime: timedelta = timedelta(hours=8)
    allowed_origin: str
    reviewer: Actor = Actor(
        kind=ActorKind.HUMAN,
        actor_id="actor:local-reviewer",
        display_name="Local reviewer",
    )
    reviewer_profile: RecordReference = RecordReference(
        entity_id="reviewer-profile:local",
        revision_id="revision:reviewer-profile-local",
        content_hash="sha256:" + ("0" * 64),
    )


class _Session(BaseModel):
    model_config = ConfigDict(frozen=True)

    csrf_token: str
    expires_at: datetime


def create_review_app(
    review_service: ReviewService,
    config: ReviewWebConfig,
) -> tuple[FastAPI, str]:
    """Create an app and a single-use bootstrap token for a fixed project root."""
    root = config.project_root.resolve()
    if not root.is_dir() or root != config.project_root:
        raise ValueError("project_root must be an existing, resolved directory")
    if not config.allowed_origin.startswith(("http://127.0.0.1:", "http://localhost:", "http://testserver")):
        raise ValueError("allowed_origin must be loopback")

    environment = Environment(
        loader=PackageLoader("rob2_kit.review", "templates"),
        autoescape=select_autoescape(("html", "xml"), default=True),
    )
    if not environment.autoescape:
        raise RuntimeError("review templates require autoescaping")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.review_service = review_service
    app.state.project_root = root
    app.state.bootstrap_token = secrets.token_urlsafe(32)
    app.state.sessions = {}
    static_root = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/review", response_class=HTMLResponse)
    async def review_page(request: Request, token: str | None = None):
        if token is not None:
            if not secrets.compare_digest(token, app.state.bootstrap_token):
                return HTMLResponse("Invalid or expired review link", status_code=401)
            app.state.bootstrap_token = secrets.token_urlsafe(32)
            session_id = secrets.token_urlsafe(32)
            app.state.sessions[session_id] = _Session(
                csrf_token=secrets.token_urlsafe(32),
                expires_at=datetime.now(UTC) + config.session_lifetime,
            )
            response = RedirectResponse("/review", status_code=303)
            response.set_cookie(
                SESSION_COOKIE,
                session_id,
                httponly=True,
                samesite="strict",
                secure=False,
                max_age=int(config.session_lifetime.total_seconds()),
            )
            return response
        session = _authenticated_session(request, app.state.sessions)
        if session is None:
            return HTMLResponse("Review session expired", status_code=401)
        template = environment.get_template("review.html")
        return HTMLResponse(
            template.render(
                review=review_service.review_case,
                queue=review_service.queue(),
                csrf_token=session.csrf_token,
                connection_state=review_service.connection_state().value,
                last_contact=review_service.last_contact(),
                reviewer=config.reviewer,
                stale=review_service.is_stale(),
            )
        )

    @app.post("/review/actions")
    async def review_action(request: Request):
        session = _authenticated_session(request, app.state.sessions)
        if session is None:
            return HTMLResponse("Review session expired", status_code=401)
        if request.headers.get("origin") != config.allowed_origin:
            return HTMLResponse("Origin rejected", status_code=403)
        form = await _urlencoded_form(request)
        if not secrets.compare_digest(form.get("csrf_token", ""), session.csrf_token):
            return HTMLResponse("CSRF validation failed", status_code=403)
        try:
            review_service.commit(
                ReviewCommand(
                    idempotency_key=form.get("idempotency_key", ""),
                    action_id=form.get("action_id", ""),
                    kind=ActionKind(form.get("kind", "")),
                    expected_assessment_revision_id=form.get(
                        "expected_assessment_revision_id", ""
                    ),
                    actor=config.reviewer,
                    value=form.get("value", ""),
                    rationale=form.get("rationale") or None,
                    confirmed_display_name=form.get("confirmed_display_name") or None,
                    reviewer_profile=config.reviewer_profile,
                    review_session_id=f"review-session:{request.cookies[SESSION_COOKIE][:24]}",
                    observed_at=datetime.now(UTC),
                )
            )
        except StaleReviewError as error:
            return HTMLResponse(f"Read-only: {error}", status_code=409)
        except SignOffBlockedError as error:
            return HTMLResponse(f"Sign-off unavailable: {error}", status_code=409)
        except (ReviewError, ValueError) as error:
            return HTMLResponse(f"Invalid review action: {error}", status_code=422)
        return RedirectResponse("/review", status_code=303)

    return app, app.state.bootstrap_token


def _authenticated_session(request: Request, sessions: dict[str, _Session]) -> _Session | None:
    session_id = request.cookies.get(SESSION_COOKIE)
    session = sessions.get(session_id) if session_id else None
    if session is None or session.expires_at <= datetime.now(UTC):
        if session_id:
            sessions.pop(session_id, None)
        return None
    return session


async def _urlencoded_form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        return {}
    parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}
