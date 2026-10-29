from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: str
    event_time: datetime
    updated_at: datetime

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        if not value.isalpha() or value.upper() != value:
            raise ValueError("currency must be a 3-letter uppercase code")
        return value

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"created", "paid", "cancelled", "refunded"}:
            raise ValueError("status must be created, paid, cancelled, or refunded")
        return value


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value
