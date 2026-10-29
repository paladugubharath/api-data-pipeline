import json
import os
import subprocess
import sys
import time
from pathlib import Path
import pytest
import httpx
import uvicorn
from pipeline.generator import write_dataset
from pipeline.config import load_config

@pytest.fixture
def local_env(tmp_path, monkeypatch):
    data = tmp_path / "orders.json"
    write_dataset(data, 30, seed=42, include_edge_cases=False)
    monkeypatch.setenv("MOCK_DATA_FILE", str(data))
    monkeypatch.setenv("MOCK_API_TOKEN", "test-token")
    monkeypatch.setenv("API_TOKEN", "test-token")
    import pipeline.mock_api as mock
    mock.DATA_FILE = data
    mock.STATE.update(requests=0, fail_once_pages=set(), always_fail_pages=set(),
                      rate_limit_every=0, schema_change_page=None)
    config = {
        "api": {"base_url": "http://127.0.0.1:8765", "token": "test-token",
                "timeout_seconds": 2, "max_retries": 2, "backoff_seconds": 0.01,
                "requests_per_second": 100, "page_size": 10},
        "paths": {"database": str(tmp_path / "out.db"), "raw_dir": str(tmp_path / "raw"),
                  "quarantine_dir": str(tmp_path / "quarantine"), "parquet_dir": str(tmp_path / "parquet"),
                  "reports_dir": str(tmp_path / "reports"), "checkpoint_name": "orders"},
    }
    server = uvicorn.Server(uvicorn.Config(mock.app, host="127.0.0.1", port=8765, log_level="error"))
    import threading
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            httpx.get("http://127.0.0.1:8765/health", timeout=0.1)
            break
        except Exception:
            time.sleep(0.02)
    yield config
    server.should_exit = True
    thread.join(timeout=2)
