"""Client for the customer's ticketing API (OAuth2 client credentials).

Written the way enterprise integrations fail in practice:
  * tokens are cached and refreshed shortly before expiry
  * a 401 forces one token refresh and a single retry (tokens get revoked)
  * 429 and 5xx are retried with exponential backoff, honoring Retry-After
  * every request carries a correlation id so failures can be matched to
    the customer's API gateway logs
"""
from __future__ import annotations

import logging
import time
import uuid

import httpx

log = logging.getLogger(__name__)


class TicketAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, correlation_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.correlation_id = correlation_id


class TicketClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        sleep=time.sleep,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=10.0, transport=transport)
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expiry = 0.0
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep

    # OAuth --------------------------------------------------------------
    def _fetch_token(self) -> None:
        resp = self._http.post(
            "/oauth/token",
            data={"grant_type": "client_credentials", "scope": "tickets:read"},
            auth=(self._client_id, self._client_secret),
        )
        if resp.status_code != 200:
            raise TicketAPIError(f"token request failed: {resp.status_code} {resp.text}", resp.status_code)
        body = resp.json()
        self._token = body["access_token"]
        # Refresh 30s early to avoid racing expiry on slow requests.
        self._token_expiry = time.monotonic() + int(body.get("expires_in", 300)) - 30

    def _auth_header(self) -> dict[str, str]:
        if not self._token or time.monotonic() >= self._token_expiry:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    # Requests -----------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict:
        correlation_id = str(uuid.uuid4())
        refreshed = False
        attempt = 0
        while True:
            headers = {**self._auth_header(), "X-Correlation-ID": correlation_id}
            try:
                resp = self._http.get(path, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise TicketAPIError(f"network error: {exc}", None, correlation_id) from exc
                self._backoff(attempt, None)
                attempt += 1
                continue

            if resp.status_code == 401 and not refreshed:
                log.info("401 from ticket API, refreshing token (cid=%s)", correlation_id)
                self._token = None
                refreshed = True
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self._max_retries:
                self._backoff(attempt, resp.headers.get("Retry-After"))
                attempt += 1
                continue
            if resp.status_code == 404:
                return {"error": "not_found"}
            if resp.status_code >= 400:
                raise TicketAPIError(
                    f"{path} returned {resp.status_code}: {resp.text[:200]}", resp.status_code, correlation_id
                )
            return resp.json()

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = float(retry_after) if retry_after and retry_after.isdigit() else self._backoff_base * 2**attempt
        self._sleep(delay)

    # Public API ---------------------------------------------------------
    def get_ticket(self, ticket_id: str) -> dict:
        return self._get(f"/api/tickets/{ticket_id}")

    def list_tickets(self, status: str | None = None, service: str | None = None, limit: int = 10) -> dict:
        params = {k: v for k, v in {"status": status, "service": service, "limit": limit}.items() if v}
        return self._get("/api/tickets", params=params)
