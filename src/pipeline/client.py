from __future__ import annotations
import time
import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: float = 10,
                 max_retries: int = 4, backoff_seconds: float = 0.2,
                 requests_per_second: float = 20):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_request = 0.0
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self):
        self.client.close()

    def get_page(self, page: int, page_size: int) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            try:
                response = self.client.get(
                    f"{self.base_url}/v1/orders",
                    params={"page": page, "page_size": page_size},
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                self._last_request = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after else self.backoff_seconds * (2 ** attempt)
                        logger.warning("Retryable HTTP %s for page %s; attempt %s; sleep %.2fs",
                                       response.status_code, page, attempt + 1, delay)
                        time.sleep(min(delay, 10))
                        continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("Unexpected API response shape: expected object with data list")
                return payload
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                retryable = status is None or status == 429 or status >= 500
                if not retryable or attempt >= self.max_retries:
                    raise
                delay = self.backoff_seconds * (2 ** attempt)
                logger.warning("Retryable API error for page %s: %s; sleep %.2fs", page, exc, delay)
                time.sleep(min(delay, 10))
        if last_error:
            raise last_error
        raise RuntimeError(f"Could not fetch page {page}")
