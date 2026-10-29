from __future__ import annotations
from typing import Any


def transform(record: dict[str, Any]) -> dict[str, Any]:
    """Deterministic target projection; no business values are inferred."""
    result = dict(record)
    result["currency"] = result["currency"].upper()
    return result
