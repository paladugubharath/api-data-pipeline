from __future__ import annotations
import json
import re
from typing import Any
from pydantic import ValidationError
from .models import OrderRecord, to_jsonable


def validate_record(raw: Any, known_customers: set[str] | None = None) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "record must be a JSON object"
    try:
        model = OrderRecord.model_validate(raw)
    except ValidationError as exc:
        return None, "; ".join(
            f"{'.'.join(str(p) for p in item['loc'])}: {item['msg']}" for item in exc.errors()
        )
    # The synthetic source contract uses stable customer IDs of the form cust_000001.
    # An optional authoritative key set can enforce existence beyond this format check.
    if not re.fullmatch(r"cust_\d{6}", model.customer_id):
        return None, f"invalid customer_id reference format: {model.customer_id}"
    if known_customers is not None and model.customer_id not in known_customers:
        return None, f"unknown customer_id reference: {model.customer_id}"
    return to_jsonable(model.model_dump()), None


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
