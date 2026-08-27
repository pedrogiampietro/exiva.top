"""Cliente HTTP com headers de navegador, retry e delay educado."""
from __future__ import annotations

import time

import httpx

from . import config


class DeusoldClient:
    """Wrapper fino sobre httpx.Client com retry/backoff e rate-limit simples."""

    def __init__(self, delay: float = config.REQUEST_DELAY) -> None:
        self.delay = delay
        self._client = httpx.Client(
            base_url=config.BASE_URL,
            headers=config.HEADERS,
            timeout=config.REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        self._last_request = 0.0

    def get(self, path: str, params: dict | None = None) -> str:
        """GET com retry. Retorna o HTML como texto."""
        last_exc: Exception | None = None
        for attempt in range(1, config.MAX_RETRIES + 1):
            self._throttle()
            try:
                resp = self._client.get(path, params=params)
                resp.raise_for_status()
                return resp.text
            except (httpx.HTTPError, httpx.TransportError) as exc:
                last_exc = exc
                backoff = min(2**attempt, 15)
                print(f"  [retry {attempt}/{config.MAX_RETRIES}] {path} falhou: {exc}. "
                      f"aguardando {backoff}s")
                time.sleep(backoff)
        raise RuntimeError(f"GET {path} falhou após {config.MAX_RETRIES} tentativas") from last_exc

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DeusoldClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
