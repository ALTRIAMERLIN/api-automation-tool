"""FastAPI application factory: routes, middleware, CSRF helper, error pages (SPEC 14)."""

import hmac
import secrets
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from apitool.config import JobConfig, job_config_from_form, job_config_to_form
from apitool.demo.jobs import setup_demo_jobs
from apitool.errors import ConfigError, JobBusyError
from apitool.export import safe_export_path
from apitool.runner import preview_job, run_job, utc_now
from apitool.storage import JobRecord, RunRecord, Storage

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
TRIGGER_LABELS = {"ui": "Web page", "cli": "Command line"}
COUNTER_LABELS = [
    ("pages_fetched", "Pages fetched"),
    ("records_fetched", "Records fetched"),
    ("retries", "Retries"),
    ("duplicates_removed", "Duplicates removed"),
    ("records_missing_key", "Skipped: key missing or empty"),
    ("already_seen_skipped", "Skipped: already exported"),
    ("records_exported", "Records exported"),
]
CREDENTIAL_REQUIRED_MESSAGE = "required for this authentication type"


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


def _job_rows(storage: Storage) -> list[dict[str, Any]]:
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


def _form_values(form: Any) -> dict[str, str]:
    """Plain string values from a submitted form. File uploads are not used by any form."""
    return {key: value for key, value in form.items() if isinstance(value, str)}


def _errors_by_field(errors: list[tuple[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for field, message in errors:
        grouped.setdefault(field, []).append(message)
    return grouped


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

    def run_or_404(run_id: int) -> RunRecord:
        run = storage.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Not found.")
        return run

    def job_or_404(job_id: int) -> JobRecord:
        job = storage.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Not found.")
        return job

    def job_form(
        request: Request,
        *,
        mode: str,
        job_id: int | None,
        values: dict[str, str],
        errors: dict[str, list[str]],
        status_code: int = 200,
    ) -> HTMLResponse:
        has_secret = job_id is not None and storage.get_secret(job_id) is not None
        action = "/jobs" if job_id is None else f"/jobs/{job_id}"
        response = render(
            request,
            "job_form.html",
            mode=mode,
            job_id=job_id,
            action=action,
            values=values,
            errors=errors,
            has_secret=has_secret,
        )
        response.status_code = status_code
        return response

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

    # Jobs page and demo data

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

    @app.post("/jobs/{job_id}/preview", response_class=HTMLResponse)
    def preview_page(request: Request, job_id: int, csrf_token: str = Form("")) -> HTMLResponse:
        check_csrf(csrf_token)
        job = job_or_404(job_id)
        result = preview_job(storage, job_id)
        return render(request, "preview.html", job=job, result=result)

    @app.post("/jobs/{job_id}/run")
    def run_now(job_id: int, csrf_token: str = Form("")) -> RedirectResponse:
        check_csrf(csrf_token)
        job_or_404(job_id)
        try:
            result = run_job(storage, job_id, "ui")
        except JobBusyError:
            raise HTTPException(status_code=409, detail="This job is already running.") from None
        return RedirectResponse(f"/runs/{result.run_id}", status_code=303)

    @app.get("/runs", response_class=HTMLResponse)
    def runs_page(request: Request) -> HTMLResponse:
        runs = [
            {
                "id": run.id,
                "job_name": run.job_name,
                "status": run.status,
                "label": STATUS_LABELS.get(run.status, run.status),
                "started_at": run.started_at,
                "records_exported": run.records_exported,
            }
            for run in storage.list_runs(limit=100)
        ]
        return render(request, "runs.html", runs=runs)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: int) -> HTMLResponse:
        run = run_or_404(run_id)
        can_run_again = run.job_id is not None and storage.get_job(run.job_id) is not None
        return render(
            request,
            "run.html",
            run=run,
            status_label=STATUS_LABELS.get(run.status, run.status),
            trigger_label=TRIGGER_LABELS.get(run.trigger, run.trigger),
            counters=[(label, getattr(run, field)) for field, label in COUNTER_LABELS],
            can_run_again=can_run_again,
        )

    @app.get("/runs/{run_id}/download")
    def download_export(run_id: int) -> FileResponse:
        run = run_or_404(run_id)
        path = safe_export_path(storage.exports_dir, run.output_file) if run.output_file else None
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Not found.")
        return FileResponse(path, filename=run.output_file)

    # Job create, edit, delete and sync-state reset

    @app.get("/jobs/new", response_class=HTMLResponse)
    def new_job_page(request: Request) -> HTMLResponse:
        blank = JobConfig.model_construct(name="", url="")
        return job_form(
            request, mode="create", job_id=None, values=job_config_to_form(blank), errors={}
        )

    @app.post("/jobs")
    async def create_job(request: Request) -> Response:
        form = _form_values(await request.form())
        check_csrf(form.get("csrf_token"))
        secret = form.get("secret", "")
        try:
            cfg = job_config_from_form(form)
            if cfg.auth_type != "none" and not secret:
                raise ConfigError([("secret", CREDENTIAL_REQUIRED_MESSAGE)])
            job_id = storage.create_job(cfg, utc_now())
        except ConfigError as err:
            return job_form(
                request,
                mode="create",
                job_id=None,
                values=_entered(form),
                errors=_errors_by_field(err.errors),
                status_code=400,
            )
        if cfg.auth_type != "none":
            storage.set_secret(job_id, secret)
        return RedirectResponse("/?notice=job_created", status_code=303)

    @app.get("/jobs/{job_id}/edit", response_class=HTMLResponse)
    def edit_job_page(request: Request, job_id: int) -> HTMLResponse:
        job = job_or_404(job_id)
        return job_form(
            request,
            mode="edit",
            job_id=job_id,
            values=job_config_to_form(job.config),
            errors={},
        )

    @app.post("/jobs/{job_id}")
    async def update_job(request: Request, job_id: int) -> Response:
        job_or_404(job_id)
        form = _form_values(await request.form())
        check_csrf(form.get("csrf_token"))
        new_secret = form.get("secret", "")
        clear_secret = form.get("clear_secret") == "on"
        try:
            cfg = job_config_from_form(form)
            if cfg.auth_type != "none":
                kept = None if clear_secret else storage.get_secret(job_id)
                if not (new_secret or kept):
                    raise ConfigError([("secret", CREDENTIAL_REQUIRED_MESSAGE)])
            state_reset = storage.update_job(job_id, cfg, utc_now())
        except ConfigError as err:
            return job_form(
                request,
                mode="edit",
                job_id=job_id,
                values=_entered(form),
                errors=_errors_by_field(err.errors),
                status_code=400,
            )
        if cfg.auth_type == "none" or clear_secret:
            storage.delete_secret(job_id)
        if cfg.auth_type != "none" and new_secret:
            storage.set_secret(job_id, new_secret)
        notice = "state_reset_auto" if state_reset else "job_updated"
        return RedirectResponse(f"/?notice={notice}", status_code=303)

    @app.post("/jobs/{job_id}/delete")
    def delete_job(job_id: int, csrf_token: str = Form("")) -> RedirectResponse:
        check_csrf(csrf_token)
        job_or_404(job_id)
        storage.delete_job(job_id)
        return RedirectResponse("/?notice=job_deleted", status_code=303)

    @app.post("/jobs/{job_id}/reset-state")
    def reset_job_state(job_id: int, csrf_token: str = Form("")) -> RedirectResponse:
        check_csrf(csrf_token)
        job_or_404(job_id)
        storage.reset_state(job_id)
        return RedirectResponse("/?notice=state_reset", status_code=303)

    return app


def _entered(form: dict[str, str]) -> dict[str, str]:
    """Values to show again after a failed save. The secret is never echoed back."""
    values = dict(form)
    values.pop("secret", None)
    values.pop("csrf_token", None)
    return values
