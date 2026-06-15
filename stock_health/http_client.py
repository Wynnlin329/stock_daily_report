from __future__ import annotations

import logging
import time
from http.client import IncompleteRead
from dataclasses import dataclass
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import HTTP_BACKOFF_SECONDS, HTTP_RETRIES, HTTP_TIMEOUT_SECONDS, USER_AGENT

LOGGER = logging.getLogger(__name__)


@dataclass
class HttpResponse:
    url: str
    status: int | None
    body: bytes
    elapsed_ms: int
    error: str = ""

    @property
    def text(self) -> str:
        for encoding in ("utf-8-sig", "utf-8", "big5", "cp950"):
            try:
                return self.body.decode(encoding)
            except UnicodeDecodeError:
                continue
        return self.body.decode("utf-8", errors="replace")


class HttpClient:
    def __init__(
        self,
        timeout: int = HTTP_TIMEOUT_SECONDS,
        retries: int = HTTP_RETRIES,
        backoff_seconds: float = HTTP_BACKOFF_SECONDS,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.user_agent = user_agent

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> HttpResponse:
        request_headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if headers:
            request_headers.update(headers)

        last_response = HttpResponse(url=url, status=None, body=b"", elapsed_ms=0, error="not attempted")
        for attempt in range(self.retries + 1):
            started = time.perf_counter()
            try:
                request = Request(url, headers=request_headers, method="GET")
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    return HttpResponse(url=url, status=response.status, body=body, elapsed_ms=elapsed_ms)
            except HTTPError as exc:
                body = exc.read() if hasattr(exc, "read") else b""
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                last_response = HttpResponse(url=url, status=exc.code, body=body, elapsed_ms=elapsed_ms, error=f"HTTP {exc.code}: {exc.reason}")
                if exc.code in {403, 404, 429}:
                    return last_response
            except (IncompleteRead, TimeoutError, URLError, OSError) as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                last_response = HttpResponse(url=url, status=None, body=b"", elapsed_ms=elapsed_ms, error=f"{type(exc).__name__}: {exc}")

            if attempt < self.retries:
                sleep_seconds = self.backoff_seconds * (attempt + 1)
                LOGGER.debug("Retrying %s in %.1fs after %s", url, sleep_seconds, last_response.error)
                time.sleep(sleep_seconds)

        return last_response
