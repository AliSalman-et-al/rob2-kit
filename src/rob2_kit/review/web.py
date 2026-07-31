"""Secured loopback HTTP boundary for direct human review."""

from __future__ import annotations

import hashlib
import io
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import pymupdf
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from PIL import Image, ImageDraw
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
from rob2_kit.review.workspace import (
    project_workspace,
    secured_source_pdf,
    signaling_question_audit,
)
from rob2_kit.storage.ledger import WorkflowLedger

SESSION_COOKIE = "rob2_review_session"
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; frame-src 'self'; "
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
    opened_domains: frozenset[str] = frozenset()


def create_review_app(
    review_service: ReviewService | None,
    config: ReviewWebConfig,
    *,
    ledger: WorkflowLedger | None = None,
) -> tuple[FastAPI, str]:
    """Create an app and a single-use bootstrap token for a fixed project root."""
    workspace_ledger = review_service.ledger if review_service is not None else ledger
    if workspace_ledger is None:
        raise ValueError("a Review service or Workflow ledger is required")
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
    async def review_page(
        request: Request,
        token: str | None = None,
        result: str | None = None,
        domain: str | None = None,
        sq: str | None = None,
        evidence: str | None = None,
        view: str = "crop",
        mode: str | None = None,
        return_position: str | None = None,
        correction_action: str | None = None,
    ):
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
        if review_service is not None:
            review_service.heartbeat()
            if domain in review_service.review_case.domain_ids:
                session_id = request.cookies[SESSION_COOKIE]
                session = session.model_copy(
                    update={"opened_domains": session.opened_domains | {domain}}
                )
                app.state.sessions[session_id] = session
        connection_state = (
            review_service.connection_state().value
            if review_service is not None
            else "not connected—review saved"
        )
        workspace = project_workspace(
            workspace_ledger,
            connection_state=connection_state,
            selected_result_id=result,
        )
        selected_result = (
            result
            or (workspace.selected_result_id if workspace is not None else None)
            or (
                review_service.review_case.result_label
                if review_service is not None
                else "result:unknown"
            )
        )
        stale = review_service.is_stale() if review_service is not None else False
        audit = signaling_question_audit(
            workspace_ledger,
            result_id=selected_result,
            domain_id=domain,
            sq_id=sq,
            evidence_id=evidence,
            assessment_current=not stale,
            assessment=(
                review_service.review_case.assessment
                if review_service is not None
                else None
            ),
            view=view,
        )
        review_mode = mode if mode in {"guided", "full"} else ("full" if audit else "guided")
        position = {
            "result": result,
            "domain": domain,
            "sq": sq,
            "evidence": evidence,
            "return_position": return_position,
        }
        full_audit_url = "/review?" + urlencode(
            {"mode": "full", **{key: value for key, value in position.items() if value}}
        )
        guided_review_url = "/review?" + urlencode(
            {"mode": "guided", **{key: value for key, value in position.items() if value}}
        )
        template = environment.get_template("review.html")
        return HTMLResponse(
            template.render(
                workspace=workspace,
                audit=audit,
                review=review_service.review_case if review_service is not None else None,
                queue=review_service.queue() if review_service is not None else (),
                corrections=(
                    review_service.correction_receipts()
                    if review_service is not None
                    else ()
                ),
                correction_states=(
                    {
                        receipt.revision_id: review_service.correction_state(
                            receipt.revision_id
                        )
                        for receipt in review_service.correction_receipts()
                    }
                    if review_service is not None
                    else {}
                ),
                csrf_token=session.csrf_token,
                connection_state=connection_state,
                last_contact=(
                    review_service.last_contact()
                    if review_service is not None
                    else datetime.now(UTC)
                ),
                reviewer=config.reviewer,
                stale=stale,
                review_mode=review_mode,
                selected_result=result,
                selected_domain=domain,
                selected_sq=sq,
                selected_evidence=evidence,
                return_position=return_position,
                correction_action=correction_action,
                full_audit_url=full_audit_url,
                guided_review_url=guided_review_url,
            )
        )

    @app.post("/review/actions")
    async def review_action(request: Request):
        session = _authenticated_session(request, app.state.sessions)
        if session is None:
            return HTMLResponse("Review session expired", status_code=401)
        if review_service is None:
            return HTMLResponse(
                "Human review is locked until preparation is complete",
                status_code=409,
            )
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
                    domain_opened=(
                        form.get("domain", "") in session.opened_domains
                    ),
                    correction_scope=(
                        form.get("correction_scope") or None
                    ),
                )
            )
        except StaleReviewError as error:
            return HTMLResponse(f"Read-only: {error}", status_code=409)
        except SignOffBlockedError as error:
            return HTMLResponse(f"Sign-off unavailable: {error}", status_code=409)
        except (ReviewError, ValueError) as error:
            return HTMLResponse(f"Invalid review action: {error}", status_code=422)
        position = {
            key: form[key]
            for key in ("mode", "result", "domain", "sq", "evidence", "return_position")
            if form.get(key)
        }
        location = "/review" + (f"?{urlencode(position)}" if position else "")
        return RedirectResponse(location, status_code=303)

    @app.get("/review/sources/{source_id:path}")
    async def source_preview(request: Request, source_id: str):
        if _authenticated_session(request, app.state.sessions) is None:
            return HTMLResponse("Review session expired", status_code=401)
        source = secured_source_pdf(workspace_ledger, source_id)
        if source is None:
            return HTMLResponse("Secured PDF source not found", status_code=404)
        return Response(
            source,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/review/evidence-images/{source_id:path}")
    async def evidence_image(
        request: Request,
        source_id: str,
        artifact_hash: str,
        page: int,
        left: float | None = None,
        top: float | None = None,
        right: float | None = None,
        bottom: float | None = None,
        mode: str = "crop",
    ):
        if _authenticated_session(request, app.state.sessions) is None:
            return HTMLResponse("Review session expired", status_code=401)
        source = secured_source_pdf(workspace_ledger, source_id)
        if source is None:
            return HTMLResponse("Secured PDF source not found", status_code=404)
        actual_hash = f"sha256:{hashlib.sha256(source).hexdigest()}"
        if not secrets.compare_digest(actual_hash, artifact_hash):
            return HTMLResponse("Evidence source revision is stale", status_code=409)
        spatial = (
            (left, top, right, bottom)
            if left is not None
            and top is not None
            and right is not None
            and bottom is not None
            else None
        )
        try:
            rendered = _render_evidence_image(
                source,
                page=page,
                spatial=spatial,
                crop=mode != "page" and spatial is not None,
            )
        except ValueError as error:
            return HTMLResponse(f"Invalid evidence image request: {error}", status_code=422)
        return Response(
            rendered,
            media_type="image/png",
            headers={"Content-Disposition": "inline"},
        )

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


def _render_evidence_image(
    source: bytes,
    *,
    page: int,
    spatial: tuple[float, float, float, float] | None,
    crop: bool,
    dpi: int = 144,
) -> bytes:
    """Render one immutable PDF page/crop and burn in its bound evidence outline."""
    if page < 1:
        raise ValueError("page must be positive")
    if spatial is not None:
        left, top, right, bottom = spatial
        if min(spatial) < 0 or right <= left or bottom <= top:
            raise ValueError("spatial extent must be positive")
    try:
        document = pymupdf.open(stream=source, filetype="pdf")
    except Exception as error:
        raise ValueError("source is not a readable PDF") from error
    with document:
        if page > document.page_count:
            raise ValueError("page is outside the secured source")
        pdf_page = document[page - 1]
        page_rect = pdf_page.rect
        if spatial is None:
            region = page_rect
        elif max(spatial) <= 1:
            region = pymupdf.Rect(
                page_rect.x0 + left * page_rect.width,
                page_rect.y0 + top * page_rect.height,
                page_rect.x0 + right * page_rect.width,
                page_rect.y0 + bottom * page_rect.height,
            )
        else:
            region = pymupdf.Rect(left, top, right, bottom)
        region &= page_rect
        if region.is_empty:
            raise ValueError("spatial extent does not intersect the page")
        pixmap = pdf_page.get_pixmap(
            dpi=dpi,
            clip=region if crop else page_rect,
            alpha=False,
            annots=True,
        )
        image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
        draw = ImageDraw.Draw(image)
        if crop:
            outline = (2, 2, image.width - 3, image.height - 3)
        else:
            scale_x = image.width / page_rect.width
            scale_y = image.height / page_rect.height
            outline = (
                round((region.x0 - page_rect.x0) * scale_x),
                round((region.y0 - page_rect.y0) * scale_y),
                round((region.x1 - page_rect.x0) * scale_x),
                round((region.y1 - page_rect.y0) * scale_y),
            )
        draw.rectangle(outline, outline="#d18400", width=max(3, dpi // 36))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
