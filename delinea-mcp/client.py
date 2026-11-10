# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
"""Delinea Platform / Secret Server Discovery REST client (read-only).

Authenticates to the Delinea Platform with the OAuth2 client credentials flow (service user), finds the
Secret Server instance through the Vault Broker API, and calls the Secret Server REST API with the same
Platform bearer token. Only GET requests to /v1/discovery... paths are implemented, and any field that
can carry a credential is redacted from every response.
"""

import logging
import re
import ssl
import threading
import time
from typing import Any, Optional

import httpx
import truststore

logger = logging.getLogger(__name__)

# Read-only metadata areas: Discovery, secret names, roles, report definitions, the unlimited-admin audit.
# Excluded on purpose: site-connector credentials, secret detail (/v1/secrets/{id}), report execution.
# Discovery is a prefix (its GET tree is read-only metadata); everything else is an exact, anchored endpoint.
ALLOWED_PATH = re.compile(
    r"^/v1/(discovery|discovery-source)(/|$)"
    r"|^/v1/(secrets/lookup|roles|reports|configuration/unlimited-admin/audit)/?$"
    r"|^/v1/(roles/\d+/permissions|reports/\d+)/?$",
    re.IGNORECASE)
# Paths inside the allowed areas that would still leak secrets or run something
DENIED_PATH = re.compile(r"/(credentials|download[^/]*|execute|export|email)(/|$)", re.IGNORECASE)

# Keys that can hold a credential (the Discovery rule detail model carries current/new passwords and keys).
# Matched case-insensitively against the key name; redaction applies recursively to every response.
SECRET_KEY = re.compile(r"(?i)^(current|new)?(password|passphrase|privatekey|private_key|secretvalue|itemvalue)$|^currentPrivateKey$")


class DelineaError(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def redact(node: Any) -> Any:
    """Return a copy of a JSON value with credential-bearing keys replaced by '[redacted]'."""
    if isinstance(node, dict):
        return {k: ("[redacted]" if SECRET_KEY.match(k) and v not in (None, "") else redact(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [redact(i) for i in node]
    return node


class DelineaClient:
    def __init__(self, tenant_host: str, client_id: str, client_secret: str,
                 secret_server_url: Optional[str] = None, timeout: float = 60.0):
        self.tenant_url = f"https://{tenant_host}"
        self._client_id = client_id
        self._client_secret = client_secret
        self._override_url = secret_server_url.rstrip("/") if secret_server_url else None
        self._ss_url: Optional[str] = None
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self._lock = threading.Lock()
        # Windows certificate store, so any the company TLS inspection CA is trusted too
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._http = httpx.Client(timeout=timeout, verify=ctx, headers={"Accept": "application/json"})

    def _bearer(self) -> str:
        """Cached Platform access token, renewed a minute before it expires (about an hour)."""
        with self._lock:
            if not self._token or time.time() > self._expires_at - 60:
                resp = self._http.post(
                    f"{self.tenant_url}/identity/api/oauth2/token/xpmplatform",
                    data={"grant_type": "client_credentials", "scope": "xpmheadless",
                          "client_id": self._client_id, "client_secret": self._client_secret},
                )
                if resp.status_code != 200:
                    # The error body names the problem (e.g. access_denied) and never echoes the secret
                    raise DelineaError(resp.status_code, f"Token request failed: {resp.text[:200]}")
                data = resp.json()
                self._token = data["access_token"]
                self._expires_at = time.time() + int(data.get("expires_in", 3600))
            return self._token

    def token_status(self) -> dict:
        """Fetch a token if needed and report its state; never returns the token itself."""
        self._bearer()
        return {"authenticated": True, "tenant": self.tenant_url,
                "seconds_until_renewal": max(0, int(self._expires_at - 60 - time.time()))}

    def secret_server_url(self) -> str:
        """Secret Server instance URL: DELINEA_SECRET_SERVER_URL if set, else the Vault Broker default vault."""
        if self._override_url:
            return self._override_url
        if self._ss_url is None:
            resp = self._http.get(f"{self.tenant_url}/vaultbroker/api/vaults",
                                  headers={"Authorization": f"Bearer {self._bearer()}"})
            if resp.status_code != 200:
                raise DelineaError(resp.status_code, f"Vault Broker lookup failed: {resp.text[:200]}")
            vaults = [v for v in resp.json().get("vaults", []) if v.get("isActive", True)]
            vault = next((v for v in vaults if v.get("isDefault")), vaults[0] if vaults else None)
            url = (vault or {}).get("connection", {}).get("url")
            if not url:
                raise DelineaError("vault", "No active Secret Server vault found in the Vault Broker")
            self._ss_url = url.rstrip("/")
        return self._ss_url

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        """GET one allow-listed Secret Server API path."""
        # Reject non-canonical input before matching so encoding or separators cannot dodge the checks
        if (any(ch in path for ch in "%\\?#") or ".." in path
                or not ALLOWED_PATH.match(path) or DENIED_PATH.search(path)):
            raise DelineaError("path", "Path is not in the read-only allow-list")
        url = f"{self.secret_server_url()}/api{path}"
        for attempt in (1, 2):
            resp = self._http.get(url, params=params, headers={"Authorization": f"Bearer {self._bearer()}"})
            if resp.status_code == 401 and attempt == 1:
                with self._lock:
                    self._token = None  # revoked or expired early: get a new one once
                continue
            if resp.status_code >= 400:
                raise DelineaError(resp.status_code, resp.text[:300] or resp.reason_phrase)
            return redact(resp.json()) if resp.content else None
        raise DelineaError(401, "Unauthorized")

# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
