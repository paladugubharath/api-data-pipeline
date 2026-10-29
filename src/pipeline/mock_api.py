from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Local Mock Orders API", version="1.0.0")
DATA_FILE = Path(os.getenv("MOCK_DATA_FILE", "data/sample/orders.json"))
STATE: dict[str, Any] = {"requests": 0, "fail_once_pages": set(), "always_fail_pages": set(),
                         "rate_limit_every": 0, "schema_change_page": None}

# Parsed-data cache. Re-parsing the whole data file on every request was the dominant cost
# in the 100,000-record run, so the file is parsed once and reused until its path, mtime
# or size changes (tests rewrite the file and reassign DATA_FILE, so they still get fresh data).
_CACHE: dict[str, Any] = {"key": None, "records": []}


def load_records() -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        return []
    stat = DATA_FILE.stat()
    key = (str(DATA_FILE), stat.st_mtime_ns, stat.st_size)
    if _CACHE["key"] != key:
        _CACHE["records"] = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        _CACHE["key"] = key
    return _CACHE["records"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/__control/reset")
def reset():
    STATE.update(requests=0, fail_once_pages=set(), always_fail_pages=set(),
                 rate_limit_every=0, schema_change_page=None)
    return {"status": "reset"}


@app.post("/__control/fail-once/{page}")
def fail_once(page: int):
    STATE["fail_once_pages"].add(page)
    return {"page": page, "mode": "fail_once"}


@app.post("/__control/fail-always/{page}")
def fail_always(page: int):
    STATE["always_fail_pages"].add(page)
    return {"page": page, "mode": "fail_always"}


@app.post("/__control/rate-limit-every/{n}")
def rate_limit_every(n: int):
    STATE["rate_limit_every"] = max(0, n)
    return {"every": n}


@app.post("/__control/schema-change/{page}")
def schema_change(page: int):
    STATE["schema_change_page"] = page
    return {"page": page, "mode": "unexpected_schema"}


@app.get("/v1/orders")
async def get_orders(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=250, ge=1, le=5000),
    authorization: str | None = Header(default=None),
):
    expected = f"Bearer {os.getenv('MOCK_API_TOKEN', 'local-demo-token')}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    STATE["requests"] += 1
    if page in STATE["always_fail_pages"]:
        raise HTTPException(status_code=503, detail="Configured persistent failure")
    if page in STATE["fail_once_pages"]:
        STATE["fail_once_pages"].remove(page)
        raise HTTPException(status_code=503, detail="Configured one-time failure")
    limit_every = STATE["rate_limit_every"]
    if limit_every and STATE["requests"] % limit_every == 0:
        return JSONResponse(status_code=429, content={"detail": "Rate limit simulated"},
                            headers={"Retry-After": "0.05"})
    records = load_records()
    start = (page - 1) * page_size
    rows = records[start:start + page_size]
    result: dict[str, Any] = {
        "page": page, "page_size": page_size, "total": len(records),
        "total_pages": (len(records) + page_size - 1) // page_size,
        "has_more": start + page_size < len(records), "data": rows,
    }
    if STATE["schema_change_page"] == page:
        result["unexpected_field"] = "deliberate schema change"
    return result