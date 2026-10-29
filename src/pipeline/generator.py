from __future__ import annotations
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def generate_records(count: int = 1000, seed: int = 42, include_edge_cases: bool = True) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    statuses = ["created", "paid", "cancelled", "refunded"]
    for i in range(count):
        event = base + timedelta(minutes=rng.randint(0, max(1, count * 4)))
        row = {
            "order_id": f"ord_{i + 1:08d}",
            "customer_id": f"cust_{rng.randint(1, max(2, count // 10)):06d}",
            "amount": round(rng.uniform(0, 5000), 2),
            "currency": "USD",
            "status": rng.choice(statuses),
            "event_time": event.isoformat(),
            "updated_at": (event + timedelta(minutes=rng.randint(0, 1440))).isoformat(),
        }
        rows.append(row)
    if include_edge_cases and count >= 10:
        rows[1]["amount"] = 0.0  # valid boundary
        rows[2]["customer_id"] = "cust_missing_ref"  # invalid reference
        rows[3]["amount"] = -12.5  # invalid domain value
        rows[4].pop("currency")  # missing required field
        rows[5]["extra_surprise"] = "unexpected schema field"
        rows[6] = dict(rows[0])  # duplicate primary key
        rows[7]["event_time"] = "not-a-timestamp"
        rows[8]["status"] = "in_transit"  # unsupported status
        rows[9]["updated_at"] = (base - timedelta(days=1)).isoformat()  # late/out of order
    return rows


def write_dataset(path: str | Path, count: int = 1000, seed: int = 42,
                  include_edge_cases: bool = True) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(generate_records(count, seed, include_edge_cases), indent=2),
                           encoding="utf-8")
    return destination
