"""FastAPI application factory: middleware, CSRF helper, error pages and static files (SPEC 14)."""

import hmac
import secrets
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from apitool.storage import Storage

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


def create_app(data_dir: Path) -> FastAPI:
    app = FastAPI(
        title="API Automation Tool",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.storage = Storage(Path(data_dir))
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

    return app
