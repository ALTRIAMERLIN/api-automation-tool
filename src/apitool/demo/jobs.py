"""The five demo jobs created by `apitool demo-setup` (SPEC 19.3)."""

from datetime import datetime

from apitool.config import build_job_config
from apitool.storage import Storage

DEMO_BASE = "https://demo.api-automation-tool.local"

# Public demo credential for the built-in fake API. Not a secret.
# Each entry is (job config data, secret). The secret is stored in the secrets table.
DEMO_JOBS: list[tuple[dict, str]] = [
    (
        {
            "name": "Demo Orders",
            "url": f"{DEMO_BASE}/v1/orders",
            "auth_type": "api_key_header",
            "auth_key_name": "X-API-Key",
            "pagination_type": "page",
            "page_param": "page",
            "page_size_param": "per_page",
            "page_size": 4,
            "records_path": "data",
            "dedup_key": "id",
            "incremental": True,
            "export_format": "csv",
        },
        "demo-key-123",
    ),
    (
        {
            "name": "Demo Customers",
            "url": f"{DEMO_BASE}/v1/customers",
            "auth_type": "bearer",
            "pagination_type": "offset",
            "offset_param": "offset",
            "limit_param": "limit",
            "page_size": 3,
            "records_path": "customers",
            "export_format": "xlsx",
        },
        "demo-token-456",
    ),
    (
        {
            "name": "Demo Events",
            "url": f"{DEMO_BASE}/v1/events",
            "auth_type": "api_key_query",
            "auth_key_name": "api_key",
            "pagination_type": "cursor",
            "cursor_param": "cursor",
            "cursor_path": "next_cursor",
            "page_size_param": "limit",
            "page_size": 2,
            "records_path": "results",
            "dedup_key": "event_id",
            "export_format": "csv",
        },
        "demo-key-123",
    ),
    (
        {
            "name": "Demo Products",
            "url": f"{DEMO_BASE}/v1/products",
            "auth_type": "basic",
            "auth_username": "demo",
            "pagination_type": "next_url",
            "next_url_path": "links.next",
            "records_path": "items",
            "fields": ["sku", "title", "price.amount", "price.currency", "stock"],
            "renames": [["price.amount", "price"], ["price.currency", "currency"]],
            "export_format": "xlsx",
        },
        "demo-pass",
    ),
    (
        {
            "name": "Demo Flaky Orders",
            "url": f"{DEMO_BASE}/v1/flaky-orders",
            "auth_type": "api_key_header",
            "auth_key_name": "X-API-Key",
            "pagination_type": "page",
            "page_param": "page",
            "page_size_param": "per_page",
            "page_size": 4,
            "records_path": "data",
            "dedup_key": "id",
            "export_format": "csv",
        },
        "demo-key-123",
    ),
]


def setup_demo_jobs(storage: Storage, now: datetime) -> tuple[int, int]:
    """Create each missing demo job and its secret. Returns (created, already_existed)."""
    created = 0
    existed = 0
    for data, secret in DEMO_JOBS:
        if storage.get_job_by_name(data["name"]) is not None:
            existed += 1
            continue
        job_id = storage.create_job(build_job_config(data), now)
        storage.set_secret(job_id, secret)
        created += 1
    return created, existed
