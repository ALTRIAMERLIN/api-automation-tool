"""Job configuration: the JobConfig model, validation rules and text-field parsers (SPEC 5)."""

import re
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from apitool.errors import ConfigError

AuthType = Literal["none", "api_key_header", "api_key_query", "bearer", "basic"]
PaginationType = Literal["none", "page", "offset", "cursor", "next_url"]
ExportFormat = Literal["csv", "xlsx"]

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]*")
_HEADER_NAME_RE = re.compile(r"[A-Za-z0-9-]+")
_WHITESPACE_RE = re.compile(r"\s")
_VALUE_ERROR_PREFIX = "Value error, "
_MAX_URL_LENGTH = 2000


class JobConfig(BaseModel):
    """Everything about a job except its secret (SPEC 5.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    url: str
    query_params: list[tuple[str, str]] = Field(default_factory=list)
    headers: list[tuple[str, str]] = Field(default_factory=list)
    auth_type: AuthType = "none"
    auth_key_name: str = ""
    auth_username: str = ""
    pagination_type: PaginationType = "none"
    page_param: str = "page"
    page_size_param: str = "per_page"
    start_page: int = Field(default=1, ge=0, le=1_000_000)
    offset_param: str = "offset"
    limit_param: str = "limit"
    cursor_param: str = "cursor"
    cursor_path: str = ""
    next_url_path: str = ""
    page_size: int = Field(default=100, ge=1, le=1000)
    records_path: str = ""
    max_pages: int = Field(default=50, ge=1, le=1000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    fields: list[str] = Field(default_factory=list)
    renames: list[tuple[str, str]] = Field(default_factory=list)
    dedup_key: str = ""
    incremental: bool = False
    export_format: ExportFormat = "csv"

    @field_validator("name", mode="after")
    @classmethod
    def _check_name(cls, value: str) -> str:
        name = value.strip()
        if not 1 <= len(name) <= 60:
            raise ValueError("must be 1 to 60 characters")
        if not _NAME_RE.fullmatch(name):
            raise ValueError(
                "may contain only letters, digits, spaces, '_' and '-', "
                "and must start with a letter or digit"
            )
        return name

    @field_validator("url", mode="after")
    @classmethod
    def _check_url(cls, value: str) -> str:
        url = value.strip()
        if len(url) > _MAX_URL_LENGTH:
            raise ValueError(f"must be at most {_MAX_URL_LENGTH} characters")
        try:
            parts = urlsplit(url)
        except ValueError:
            raise ValueError("is not a valid URL") from None
        if parts.scheme not in ("http", "https"):
            raise ValueError("must start with http:// or https://")
        if not parts.hostname:
            raise ValueError("must include a host name")
        if "@" in parts.netloc:
            raise ValueError("must not contain a user name or password")
        if "#" in url:
            raise ValueError("must not contain a fragment (#)")
        return url

    @field_validator("headers", mode="after")
    @classmethod
    def _check_header_names(cls, value: list[tuple[str, str]]) -> list[tuple[str, str]]:
        for name, _ in value:
            if not _HEADER_NAME_RE.fullmatch(name):
                raise ValueError(f"invalid header name '{name}'")
        return value

    @field_validator("records_path", mode="after")
    @classmethod
    def _check_records_path(cls, value: str) -> str:
        if value and "" in value.split("."):
            raise ValueError("must not contain empty segments (for example 'a..b')")
        return value


# Text-field parsers (SPEC 5.2). Each formatter is the exact inverse of its parser.


def parse_query_params(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise ConfigError([("query_params", f"line {number}: expected key=value")])
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            raise ConfigError([("query_params", f"line {number}: key must not be blank")])
        pairs.append((key, value.strip()))
    return pairs


def format_query_params(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{key}={value}" for key, value in pairs)


def parse_headers(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            raise ConfigError([("headers", f"line {number}: expected Name: value")])
        name, _, value = line.partition(":")
        name = name.strip()
        if not name:
            raise ConfigError([("headers", f"line {number}: expected Name: value")])
        pairs.append((name, value.strip()))
    return pairs


def format_headers(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{name}: {value}" for name, value in pairs)


def parse_fields(text: str) -> list[str]:
    items = [item.strip() for item in text.split(",")]
    items = [item for item in items if item]
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise ConfigError([("fields", f"duplicate field '{item}'")])
        seen.add(item)
    return items


def format_fields(items: list[str]) -> str:
    return ", ".join(items)


def parse_renames(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise ConfigError([("renames", f"line {number}: expected old=new")])
        old, _, new = line.partition("=")
        old = old.strip()
        new = new.strip()
        if not old:
            raise ConfigError([("renames", f"line {number}: old name must not be blank")])
        if not new:
            raise ConfigError([("renames", f"line {number}: new name must not be blank")])
        if old in seen:
            raise ConfigError([("renames", f"duplicate rename for '{old}'")])
        seen.add(old)
        pairs.append((old, new))
    return pairs


def format_renames(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{old}={new}" for old, new in pairs)


# Building a validated config


def _pydantic_pairs(exc: ValidationError) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for err in exc.errors():
        loc = err["loc"]
        field = str(loc[0]) if loc else "job"
        message = err["msg"]
        if message.startswith(_VALUE_ERROR_PREFIX):
            message = message[len(_VALUE_ERROR_PREFIX) :]
        pairs.append((field, message))
    return pairs


def _require(errors: list[tuple[str, str]], field: str, value: str) -> None:
    if not value.strip():
        errors.append((field, "is required for this pagination or authentication type"))


def _cross_field_errors(cfg: JobConfig) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []

    key = cfg.auth_key_name
    if cfg.auth_type == "api_key_header":
        _require(errors, "auth_key_name", key)
        if key.strip() and not _HEADER_NAME_RE.fullmatch(key):
            errors.append(("auth_key_name", "must be a valid header name"))
    elif cfg.auth_type == "api_key_query":
        _require(errors, "auth_key_name", key)
        if key.strip() and _WHITESPACE_RE.search(key):
            errors.append(("auth_key_name", "must not contain spaces"))
    elif cfg.auth_type == "basic":
        _require(errors, "auth_username", cfg.auth_username)
        if ":" in cfg.auth_username:
            errors.append(("auth_username", "must not contain ':'"))

    if cfg.pagination_type == "page":
        _require(errors, "page_param", cfg.page_param)
        _require(errors, "page_size_param", cfg.page_size_param)
    elif cfg.pagination_type == "offset":
        _require(errors, "offset_param", cfg.offset_param)
        _require(errors, "limit_param", cfg.limit_param)
    elif cfg.pagination_type == "cursor":
        _require(errors, "cursor_param", cfg.cursor_param)
        _require(errors, "cursor_path", cfg.cursor_path)
    elif cfg.pagination_type == "next_url":
        _require(errors, "next_url_path", cfg.next_url_path)

    if cfg.incremental and not cfg.dedup_key.strip():
        errors.append(("incremental", "requires a dedup key"))
    return errors


def build_job_config(data: Mapping[str, Any]) -> JobConfig:
    """Validate raw data (a form dict or the stored JSON form) into a JobConfig.

    Raises ConfigError with (field, message) pairs for every failed rule.
    """
    try:
        cfg = JobConfig.model_validate(dict(data))
    except ValidationError as exc:
        raise ConfigError(_pydantic_pairs(exc)) from None
    errors = _cross_field_errors(cfg)
    if errors:
        raise ConfigError(errors)
    return cfg


_INT_FIELDS = ("start_page", "page_size", "max_pages", "timeout_seconds")
_LIST_PARSERS = {
    "query_params": parse_query_params,
    "headers": parse_headers,
    "fields": parse_fields,
    "renames": parse_renames,
}


def job_config_from_form(form: Mapping[str, str]) -> JobConfig:
    """Build a JobConfig from submitted form fields. Missing keys use the model defaults."""
    data: dict[str, Any] = {}
    errors: list[tuple[str, str]] = []

    for field_name in JobConfig.model_fields:
        if field_name == "incremental":
            data[field_name] = form.get("incremental") == "on"
            continue
        if field_name not in form:
            continue
        raw = form[field_name]
        if field_name in _LIST_PARSERS:
            try:
                data[field_name] = _LIST_PARSERS[field_name](raw)
            except ConfigError as exc:
                errors.extend(exc.errors)
        elif field_name in _INT_FIELDS:
            try:
                data[field_name] = int(raw.strip())
            except ValueError:
                errors.append((field_name, "must be a whole number"))
        else:
            data[field_name] = raw

    if errors:
        raise ConfigError(errors)
    return build_job_config(data)


def job_config_to_form(cfg: JobConfig) -> dict[str, str]:
    """Render a JobConfig as form values. Inverse of job_config_from_form for valid input."""
    form: dict[str, str] = {}
    for field_name in JobConfig.model_fields:
        value = getattr(cfg, field_name)
        if field_name == "query_params":
            form[field_name] = format_query_params(value)
        elif field_name == "headers":
            form[field_name] = format_headers(value)
        elif field_name == "fields":
            form[field_name] = format_fields(value)
        elif field_name == "renames":
            form[field_name] = format_renames(value)
        elif isinstance(value, bool):
            form[field_name] = "on" if value else ""
        else:
            form[field_name] = str(value)
    return form
