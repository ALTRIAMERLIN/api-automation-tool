"""Command line interface (SPEC 15 and 18)."""

import argparse
import logging
import os
import sys
from pathlib import Path

from apitool import __version__
from apitool.demo.jobs import setup_demo_jobs
from apitool.errors import AppError, JobNotFoundError
from apitool.redact import install_filter
from apitool.runner import run_job, utc_now
from apitool.storage import Storage

DATA_DIR_ENV = "APITOOL_DATA_DIR"
DEFAULT_DATA_DIR = "data"
DEFAULT_PORT = 8000
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOGGER_NAME = "apitool"


class _StderrHandler(logging.Handler):
    """Writes to whatever sys.stderr is at emit time, so tests that swap it see the output."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            # Logging must never crash the command.
            self.handleError(record)


def _configure_logging() -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    if not any(isinstance(h, _StderrHandler) for h in logger.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    install_filter()


def _port(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be a whole number") from None
    if not 1024 <= value <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apitool",
        description="Connect REST APIs, handle pagination, flatten JSON and export CSV or Excel.",
    )
    parser.add_argument("--version", action="version", version=f"apitool {__version__}")
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        help=f"data folder (default: ${DATA_DIR_ENV}, then ./{DEFAULT_DATA_DIR})",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="start the web UI on 127.0.0.1")
    serve.add_argument("--port", type=_port, default=DEFAULT_PORT, help="1024-65535, default 8000")

    run = commands.add_parser("run", help="run one job and write its export")
    run.add_argument("--job", required=True, metavar="NAME", help="job name (any letter case)")

    commands.add_parser("list-jobs", help="list jobs")
    commands.add_parser("demo-setup", help="create the five demo jobs")
    return parser


def _data_dir(option: str | None) -> Path:
    if option:
        return Path(option)
    env_value = os.environ.get(DATA_DIR_ENV)
    if env_value:
        return Path(env_value)
    return Path(DEFAULT_DATA_DIR)


def _serve(data_dir: Path, port: int) -> int:
    import uvicorn

    from apitool.web.app import create_app

    print(f"Open http://127.0.0.1:{port} in your browser")
    uvicorn.run(create_app(data_dir), host="127.0.0.1", port=port, log_level="info")
    return 0


def _run(storage: Storage, job_name: str) -> int:
    job = storage.get_job_by_name(job_name)
    if job is None:
        raise JobNotFoundError(f"no job named '{job_name}'")
    result = run_job(storage, job.id, "cli")
    if result.status == "success":
        print(f"Run {result.run_id} success: {result.message}")
        for warning in result.warnings:
            print(f"warning: {warning}")
        return 0
    print(
        f"Run {result.run_id} failed: {result.error_type}: {result.error_message}",
        file=sys.stderr,
    )
    return result.exit_code


def _list_jobs(storage: Storage) -> int:
    for job in storage.list_jobs():
        print(f"{job.name}\t{job.config.pagination_type}\t{job.config.export_format}")
    return 0


def _demo_setup(storage: Storage) -> int:
    created, existed = setup_demo_jobs(storage, utc_now())
    print(f"Demo jobs ready: {created} created, {existed} already existed")
    return 0


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 0


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _exit_code(exc.code)

    try:
        data_dir = _data_dir(args.data_dir)
        if args.command == "serve":
            return _serve(data_dir, args.port)
        storage = Storage(data_dir)
        if args.command == "run":
            return _run(storage, args.job)
        if args.command == "list-jobs":
            return _list_jobs(storage)
        return _demo_setup(storage)
    except AppError as err:
        print(str(err), file=sys.stderr)
        return err.exit_code
    except Exception as exc:
        print(f"internal error: {type(exc).__name__}", file=sys.stderr)
        return 3
