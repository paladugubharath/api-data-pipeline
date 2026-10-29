from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv

load_dotenv()


def load_config(path: str | Path = "config/config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    api = config.setdefault("api", {})
    paths = config.setdefault("paths", {})
    api["base_url"] = os.getenv("API_BASE_URL", api.get("base_url", "http://127.0.0.1:8000"))
    api["token"] = os.getenv("API_TOKEN", "local-demo-token")
    for key, env, cast in [
        ("timeout_seconds", "API_TIMEOUT_SECONDS", float),
        ("max_retries", "API_MAX_RETRIES", int),
        ("backoff_seconds", "API_BACKOFF_SECONDS", float),
        ("requests_per_second", "API_REQUESTS_PER_SECOND", float),
    ]:
        if os.getenv(env):
            api[key] = cast(os.environ[env])
    for key in ("database", "raw_dir", "quarantine_dir", "parquet_dir", "reports_dir"):
        paths[key] = str(Path(paths.get(key, f"data/output/{key}")))
    return config
