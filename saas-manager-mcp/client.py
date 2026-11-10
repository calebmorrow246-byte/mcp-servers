"""1Password SaaS Manager (formerly Trelica) REST API client (read-only).

Uses the OAuth2 client credentials flow and requests ONLY read scopes, so every token it holds is
read-only regardless of what the API client itself is allowed to do. Only GET requests to /api/...
paths are implemented.
"""

import logging
import ssl
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import truststore

logger = logging.getLogger(__name__)

READ_SCOPES = " ".join([
    "Apps.Read", "Apps.Users.Read", "People.Read", "Assets.Read", "Contracts.Read",
    "AuditLog.Read", "Users.Read", "Workflows.Read", "Workflows.Runs.Read",
])

MAX_PAGE = 1000  # API maximum for 'limit'


class SaasManagerError(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class SaasManagerClient:
    def __init__(self, host: str, client_id: str, client_secret: str, timeout: float = 60.0):
        self.host = host
        self.base_url = f"https://{host}"
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self._lock = threading.Lock()
        # Windows certificate store, so any the company TLS inspection CA is trusted too
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._http = httpx.Client(timeout=timeout, verify=ctx, headers={"Accept": "application/json"})

    def _bearer(self) -> str:
        """Cached access token, renewed a minute before its one-hour lifetime runs out."""
        with self._lock:
            if not self._token or time.time() > self._expires_at - 60:
                resp = self._http.post(
                    f"{self.base_url}/connect/token",
                    auth=(self._client_id, self._client_secret),
                    data={"grant_type": "client_credentials", "scope": READ_SCOPES},
                )
                if resp.status_code != 200:
                    raise SaasManagerError(resp.status_code, f"Token request failed: {resp.text[:200]}")
                data = resp.json()
                self._token = data["access_token"]
                self._expires_at = time.time() + int(data.get("expires_in", 3600))
            return self._token

    def _request(self, url: str, params: Optional[dict] = None) -> Any:
        for attempt in (1, 2):
            resp = self._http.get(url, params=params, headers={"Authorization": f"Bearer {self._bearer()}"})
            if resp.status_code == 401 and attempt == 1:
                with self._lock:
                    self._token = None  # token revoked or expired early: get a new one once
                continue
            if resp.status_code >= 400:
                raise SaasManagerError(resp.status_code, resp.text[:300] or resp.reason_phrase)
            return resp.json() if resp.content else None
        raise SaasManagerError(401, "Unauthorized")

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        """GET one API path (must start with /api/)."""
        if not path.startswith("/api/"):
            raise SaasManagerError("path", "Only /api/... paths are allowed")
        return self._request(f"{self.base_url}{path}", params)

    def get_all(self, path: str, params: Optional[dict] = None, max_items: int = 1000) -> tuple:
        """Follow 'next' links until max_items results or the last page. Returns (results, more)."""
        params = dict(params or {})
        params["limit"] = min(MAX_PAGE, max(1, max_items))
        data = self.get(path, params) or {}
        results = list(data.get("results") or [])
        next_url = data.get("next")
        while next_url and len(results) < max_items:
            # 'next' is a full URL on the same host; refuse anything else
            if urlparse(next_url).netloc != self.host:
                raise SaasManagerError("next", "Unexpected host in pagination link")
            data = self._request(next_url) or {}
            batch = data.get("results") or []
            if not batch:
                next_url = None
                break
            results.extend(batch)
            next_url = data.get("next")
        return results[:max_items], bool(next_url) or len(results) > max_items

    def close(self) -> None:
        self._http.close()
