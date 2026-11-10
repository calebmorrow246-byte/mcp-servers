"""CommVault Metallic (Command Center API, tenant-scoped) client using an API access token.

Metallic logins go through SSO, so the server authenticates with an access token created in the
Metallic console for the read-only user (MetallicRO, role RO: Global View). The access token lasts
two hours and must be renewed with its refresh token; every renewal returns a NEW pair, which is
written back to Credential Manager straight away (the old refresh token stops working). A token can be
renewed only until its 'renewable until' date (about 90 days after creation); after that, someone
has to create a new token in the console and store it again.

Only GET requests are made to the API, except the token renewal POST.
"""

import logging
import ssl
import threading
import time
from typing import Any, Callable, Optional, Tuple

import httpx
import truststore

logger = logging.getLogger(__name__)

ACCESS_TARGET = "Metallic Access Token"
REFRESH_TARGET = "Metallic Refresh Token"
RENEW_MARGIN = 600          # renew when less than 10 minutes remain
ASSUMED_LIFETIME = 7200     # used when a renewal response carries no expiry
STORE_HINT = (
    "Create a new access token for MetallicRO in the Metallic console and store it on mcp-host with "
    "Server\\MCP-Hosting\\Set-McpServiceCredentials.ps1 -Target 'Metallic Access Token','Metallic Refresh Token' -Force"
)


class MetallicError(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class MetallicClient:
    def __init__(
        self,
        host: str,
        load_tokens: Callable[[], Tuple[str, str]],
        save_tokens: Callable[[str, str], None],
        timeout: float = 60.0,
        api_path: str = "/commandcenter/api",
    ):
        self.host = host
        self.base_url = f"https://{host}{api_path}"
        self._load_tokens = load_tokens
        self._save_tokens = save_tokens
        self._access: Optional[str] = None
        self._refresh: Optional[str] = None
        self._expires_at = 0.0  # 0 = unknown: renew before first use
        self._lock = threading.Lock()
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._http = httpx.Client(verify=ctx, timeout=timeout, headers={"Accept": "application/json"})

    # ------------------------------------------------------------------ tokens

    def _renew_locked(self) -> None:
        """Swap the current pair for a new one and persist it before using it. Caller holds the lock."""
        if self._access is None or self._refresh is None:
            self._access, self._refresh = self._load_tokens()
        resp = self._http.post(
            f"{self.base_url}/V4/AccessToken/Renew",
            json={"accessToken": self._access, "refreshToken": self._refresh},
            headers={"Content-Type": "application/json"},
        )
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        access = data.get("accessToken") if isinstance(data, dict) else None
        refresh = data.get("refreshToken") if isinstance(data, dict) else None
        if resp.status_code >= 400 or not access or not refresh:
            detail = (data.get("errorMessage") if isinstance(data, dict) else None) or f"HTTP {resp.status_code}"
            # Another process (e.g. an admin test) may have renewed the pair already: reload once
            stored = self._load_tokens()
            if stored != (self._access, self._refresh):
                self._access, self._refresh = stored
                self._expires_at = 0.0
                raise MetallicError("renew-retry", f"Token pair changed in Credential Manager; reloaded ({detail})")
            raise MetallicError("renew", f"Token renewal failed: {detail}. {STORE_HINT}")
        # Persist first: once renewed, the old refresh token is dead
        self._save_tokens(access, refresh)
        self._access, self._refresh = access, refresh
        expiry = data.get("tokenExpiryTimestamp") or data.get("expiryTimestamp")
        self._expires_at = float(expiry) if expiry else time.time() + ASSUMED_LIFETIME
        logger.warning("Metallic access token renewed; valid until %s", time.strftime("%Y-%m-%d %H:%M", time.localtime(self._expires_at)))

    def _token(self, force_renew: bool = False) -> str:
        with self._lock:
            if force_renew or self._expires_at - time.time() < RENEW_MARGIN:
                try:
                    self._renew_locked()
                except MetallicError as exc:
                    if exc.code != "renew-retry":
                        raise
                    self._renew_locked()
            return self._access  # type: ignore[return-value]

    # ------------------------------------------------------------------ requests

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        """Authenticated GET; renews the token once on 401."""
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        resp = self._http.get(url, params=params or {}, headers={"Authtoken": self._token()})
        if resp.status_code == 401:
            resp = self._http.get(url, params=params or {}, headers={"Authtoken": self._token(force_renew=True)})
        self._raise_for_error(resp)
        # Some endpoints (e.g. /Alert with nothing triggered) return a JSON null
        return resp.json() if resp.content else None

    def _raise_for_error(self, resp: httpx.Response) -> None:
        if resp.status_code == 403:
            raise MetallicError("403", "Not authorized: the RO role doesn't cover this (tenant users can't see CommCell-level pages)")
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            return
        if isinstance(data, dict):
            err_list = data.get("errorList") or []
            if err_list:
                e = err_list[0]
                raise MetallicError(e.get("errorCode", "unknown"), e.get("errLogMessage") or e.get("errorMessage", "Unknown error"))
            if data.get("errorCode") not in (None, 0) and data.get("errorMessage"):
                raise MetallicError(data.get("errorCode"), data.get("errorMessage"))
        resp.raise_for_status()

    def close(self) -> None:
        self._http.close()
