"""Demo datasets, loaded from the JSON files packaged next to this module (SPEC 19.2)."""

import json
from importlib.resources import files
from typing import Any


def _load(file_name: str) -> Any:
    text = files("apitool.demo").joinpath(f"datasets/{file_name}").read_text(encoding="utf-8")
    return json.loads(text)


ORDERS_V1: list[dict[str, Any]] = _load("orders_v1.json")
ORDERS_V2: list[dict[str, Any]] = ORDERS_V1 + _load("orders_v2_extra.json")
CUSTOMERS: list[dict[str, Any]] = _load("customers.json")
EVENTS_PAGES: list[dict[str, Any]] = _load("events_pages.json")
PRODUCTS_PAGES: list[dict[str, Any]] = _load("products_pages.json")
