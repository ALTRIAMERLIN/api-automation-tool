"""FastAPI application factory: routes, middleware, CSRF helper, error pages (SPEC 14)."""

import hmac
import secrets
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from apitool.demo.jobs import setup_demo_jobs
from apitool.runner import utc_now
from apitool.storage import RunRecord, Storage

WEB_DIR = Path(__file__).parent
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

CSRF_MESSAGE = "Invalid or missing form token. Reload the page and try again."
DEFAULT_MESSAGES = {
    400: "Bad request.",
    403: CSRF_MESSAGE,
    404: "Not found.",
    409: "Conflict.",
}

# Notices are fixed texts. Unknown codes are ignored, and the parameter text is never shown.
NOTICES = {
    "job_created": "Job created.",
    "job_updated": "Job saved.",
    "job_deleted": "Job deleted.",
    "demo_loaded": "Demo jobs are ready.",
    "state_reset": "Sync state cleared. The next run exports all records again.",
    "state_reset_auto": (
        "Job saved. Sync state was cleared because the connection or key settings changed."
    ),
    "dataset_v1": "Demo API now serves dataset v1.",
    "dataset_v2": "Demo API now serves dataset v2 (3 new orders).",
}

STATUS_LABELS = {"success": "Success", "failed": "Failed", "running": "Running"}


def _message_for(status: int, detail: object) -> str:
    """Use the detail given by the code, or the default text when it is only the HTTP phrase."""
    phrase = HTTPStatus(status).phrase if status in {s.value for s in HTTPStatus} else ""
    if isinstance(detail, str) and detail and detail != phrase:
        return detail
    return DEFAULT_MESSAGES.get(status, phrase or "Error.")


def _host_allowed(host_header: str) -> bool:
    try:
        hostname = urlsplit("//" + host_header).hostname
    except ValueError:
        return False
    return hostname in ALLOWED_HOSTS


def _job_rows(storage: Storage) -> list[dict]:
    rows = []
    for job in storage.list_jobs():
        last: RunRecord | None = storage.last_run_for_job(job.id)
        rows.append(
            {
                "job": job,
                "host": urlsplit(job.config.url).hostname or "",
                "last": last,
                "last_label": STATUS_LABELS.get(last.status, last.status) if last else "",
            }
        )
    return rows


def create_app(data_dir: Path) -> FastAPI:
    app = FastAPI(
        title="API Automation Tool",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    storage = Storage(Path(data_dir))
    app.state.storage = storage
    app.state.csrf_token = secrets.token_urlsafe(32)
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    def check_csrf(request_token: str | None) -> None:
        """Raise 403 unless the submitted token equals this process's token (SPEC 14.3)."""
        if not request_token or not hmac.compare_digest(
            request_token.encode("utf-8"), app.state.csrf_token.encode("ascii")
        ):
            raise HTTPException(status_code=403, detail=CSRF_MESSAGE)

    app.state.check_csrf = check_csrf

    def render(request: Request, name: str, **context: object) -> HTMLResponse:
        context.setdefault("csrf_token", app.state.csrf_token)
        return templates.TemplateResponse(request, name, context)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Host check first, then security headers on every response (SPEC 14.2)."""
        if _host_allowed(request.headers.get("host", "")):
            response = await call_next(request)
        else:
            response = PlainTextResponse("invalid host", status_code=400)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        message = _message_for(exc.status_code, exc.detail)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"status": exc.status_code, "message": message},
            status_code=exc.status_code,
        )

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/", response_class=HTMLResponse)
    def jobs_page(request: Request) -> HTMLResponse:
        notice = NOTICES.get(request.query_params.get("notice", ""))
        return render(
            request,
            "jobs.html",
            rows=_job_rows(storage),
            notice=notice,
            dataset_version=storage.get_setting("demo_dataset_version", "1"),
        )

    @app.post("/demo/setup")
    def demo_setup(csrf_token: str = Form("")) -> RedirectResponse:
        check_csrf(csrf_token)
        setup_demo_jobs(storage, utc_now())
        return RedirectResponse("/?notice=demo_loaded", status_code=303)

    @app.post("/demo/dataset")
    def demo_dataset(csrf_token: str = Form(""), version: str = Form("")) -> RedirectResponse:
        check_csrf(csrf_token)
        if version not in ("1", "2"):
            raise HTTPException(status_code=400, detail="Dataset version must be 1 or 2.")
        storage.set_setting("demo_dataset_version", version)
        return RedirectResponse(f"/?notice=dataset_v{version}", status_code=303)

    return app
