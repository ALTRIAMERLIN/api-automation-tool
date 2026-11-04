"""Dotted-path lookup into decoded JSON (SPEC section 7)."""

from typing import Any


class _Missing:
    """Sentinel for a path that does not exist. A JSON null is None, not MISSING."""

    _instance: "_Missing | None" = None

    def __new__(cls) -> "_Missing":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


def get_path(obj: Any, path: str) -> Any:
    """Return the value at a dotted path, or MISSING.

    Dict segments match keys. List segments must be all digits and an index in range.
    An empty path returns obj itself.
    """
    if path == "":
        return obj
    current = obj
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return MISSING
            current = current[segment]
        elif isinstance(current, list) and segment.isascii() and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current
