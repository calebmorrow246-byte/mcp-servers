# Authored by Caleb A. Morrow
"""Box REST client (read-only), acting as one Box user through a Client Credentials Grant app.

Requests a user access token with the OAuth2 client_credentials grant (box_subject_type=user,
box_subject_id=<user id>), caches it in memory until a minute before it expires, and calls the Box
API v2. Only GET requests to an allow-listed set of paths are implemented. There is no write call
and no Box AI call (/ai/...) anywhere in this module.
"""

import logging
import re
import ssl
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import truststore

logger = logging.getLogger(__name__)

API_BASE = "https://api.box.com/2.0"
TOKEN_URL = "https://api.box.com/oauth2/token"

# Read-only metadata and content endpoints. Everything is an exact, anchored pattern.
_LISTS = ("users|groups|events|collaborations|collaboration_whitelist_entries"
          "|collaboration_whitelist_exempt_targets|legal_hold_policies|legal_hold_policy_assignments"
          "|retention_policies|retention_policy_assignments|webhooks|storage_policies|terms_of_services"
          "|terms_of_service_user_statuses|sign_requests|folder_locks|hub_collaborations")
_ITEMS = ("users|groups|collaborations|collaboration_whitelist_entries|collaboration_whitelist_exempt_targets"
          "|legal_hold_policies|legal_hold_policy_assignments|retention_policies|retention_policy_assignments"
          "|webhooks|storage_policies|terms_of_services|sign_requests|web_links")
ALLOWED_PATH = re.compile(
    r"^/(users/me|search|metadata_templates/enterprise|hubs|hub_items)/?$"
    rf"|^/({_LISTS})/?$"
    rf"|^/({_ITEMS})/\d+/?$"
    r"|^/(files|folders)/\d+/?$"
    r"|^/(files|folders)/\d+/(comments|collaborations)/?$"
    r"|^/folders/\d+/items/?$"
    r"|^/hubs/\d+/?$"
    r"|^/users/\d+/(memberships|email_aliases)/?$"
    r"|^/groups/\d+/(memberships|collaborations)/?$"
    r"|^/retention_policies/\d+/assignments/?$"
    r"|^/retention_policy_assignments/\d+/files_under_retention/?$"
    r"|^/legal_hold_policy_assignments/\d+/files_on_hold/?$"
    r"|^/files/\d+/(versions|tasks)/?$"
    r"|^/(files|folders)/\d+/metadata/?$"
    r"|^/(files|folders)/\d+/metadata/(global/properties|enterprise/[A-Za-z0-9_-]+)/?$"
    r"|^/folders/trash/items/?$",
    re.IGNORECASE)

# The Hubs API needs this version header; other endpoints must not get it
HUB_PATH = re.compile(r"^/(hubs|hub_items|hub_collaborations)(/|$)", re.IGNORECASE)
HUB_VERSION = "2025.0"

# Redirect and representation URLs must stay on Box hosts
BOX_HOST = re.compile(r"^(api\.box\.com|([a-z0-9-]+\.)*boxcloud\.com)$", re.IGNORECASE)


class BoxError(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _canonical(path: str) -> bool:
    """True when a path has no encoding, separators or traversal that could dodge the allow-list."""
    return not (any(ch in path for ch in "%\\?#") or ".." in path)


class BoxClient:
    def __init__(self, client_id: str, client_secret: str, subject_id: str,
                 subject_type: str = "user", timeout: float = 60.0):
        if subject_type not in ("user", "enterprise"):
            raise ValueError("subject_type must be 'user' or 'enterprise'")
        self._client_id = client_id
        self._client_secret = client_secret
        self._subject_id = subject_id
        self._subject_type = subject_type
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self._lock = threading.Lock()
        # Windows certificate store, so any the company TLS inspection CA is trusted too
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._http = httpx.Client(timeout=timeout, verify=ctx, headers={"Accept": "application/json"})

    def _bearer(self) -> str:
        """Cached access token, renewed a minute before it expires."""
        with self._lock:
            if not self._token or time.time() > self._expires_at - 60:
                resp = self._http.post(
                    TOKEN_URL,
                    data={"grant_type": "client_credentials",
                          "client_id": self._client_id, "client_secret": self._client_secret,
                          "box_subject_type": self._subject_type, "box_subject_id": self._subject_id},
                )
                if resp.status_code != 200:
                    # The error body names the problem and never echoes the secret
                    raise BoxError(resp.status_code, f"Token request failed: {resp.text[:200]}")
                data = resp.json()
                self._token = data["access_token"]
                self._expires_at = time.time() + int(data.get("expires_in", 3600))
            return self._token

    def _drop_token(self) -> None:
        with self._lock:
            self._token = None

    def token_status(self) -> dict:
        """Fetch a token if needed and report its state; never returns the token itself."""
        self._bearer()
        return {"authenticated": True, "subject_type": self._subject_type, "subject_id": self._subject_id,
                "seconds_until_renewal": max(0, int(self._expires_at - 60 - time.time()))}

    def _headers(self, path: str, extra: Optional[dict] = None) -> dict:
        headers = {"Authorization": f"Bearer {self._bearer()}"}
        if HUB_PATH.match(path):
            headers["box-version"] = HUB_VERSION
        if extra:
            headers.update(extra)
        return headers

    def get(self, path: str, params: Optional[dict] = None, extra_headers: Optional[dict] = None) -> Any:
        """GET one allow-listed Box API path and return the parsed JSON."""
        if not _canonical(path) or not ALLOWED_PATH.match(path):
            raise BoxError("path", "Path is not in the read-only allow-list")
        for attempt in (1, 2):
            resp = self._http.get(f"{API_BASE}{path}", params=params,
                                  headers=self._headers(path, extra_headers))
            if resp.status_code == 401 and attempt == 1:
                self._drop_token()  # revoked or expired early: get a new one once
                continue
            if resp.status_code >= 400:
                raise BoxError(resp.status_code, resp.text[:300] or resp.reason_phrase)
            return resp.json() if resp.content else None
        raise BoxError(401, "Unauthorized")

    def download(self, file_id: str, max_bytes: int) -> tuple[bytes, bool]:
        """Download a file's content, stopping at max_bytes. Returns (bytes, truncated)."""
        if not re.fullmatch(r"\d+", file_id):
            raise BoxError("path", "file_id must be numeric")
        path = f"/files/{file_id}/content"
        for attempt in (1, 2):
            with self._http.stream("GET", f"{API_BASE}{path}", follow_redirects=True,
                                   headers=self._headers(path)) as resp:
                if resp.status_code == 401 and attempt == 1:
                    self._drop_token()
                    continue
                if resp.status_code >= 400:
                    resp.read()
                    raise BoxError(resp.status_code, resp.text[:300] or resp.reason_phrase)
                host = urlparse(str(resp.url)).hostname or ""
                if not BOX_HOST.match(host):
                    raise BoxError("redirect", "Download redirected to a non-Box host")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        return b"".join(chunks)[:max_bytes], True
                return b"".join(chunks), False
        raise BoxError(401, "Unauthorized")

    def extracted_text(self, file_id: str, max_bytes: int) -> tuple[Optional[str], str]:
        """Box's extracted-text representation of a file (Word, PDF and so on).

        Returns (text, note). text is None with an explanatory note when no text is available yet.
        """
        if not re.fullmatch(r"\d+", file_id):
            raise BoxError("path", "file_id must be numeric")
        info = self.get(f"/files/{file_id}", {"fields": "representations"},
                        {"x-rep-hints": "[extracted_text]"})
        entries = ((info or {}).get("representations") or {}).get("entries") or []
        rep = next((e for e in entries if e.get("representation") == "extracted_text"), None)
        if not rep:
            return None, "Box has no extracted-text representation for this file type"
        state = (rep.get("status") or {}).get("state")
        template = (rep.get("content") or {}).get("url_template", "")
        if state != "success" or not template:
            return None, f"Extracted text is not ready (state: {state}); try again shortly"
        url = template.replace("{+asset_path}", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not BOX_HOST.match(parsed.hostname or ""):
            raise BoxError("redirect", "Representation URL is not on a Box host")
        for attempt in (1, 2):
            with self._http.stream("GET", url, follow_redirects=True,
                                   headers={"Authorization": f"Bearer {self._bearer()}"}) as resp:
                if resp.status_code == 401 and attempt == 1:
                    self._drop_token()
                    continue
                if resp.status_code >= 400:
                    resp.read()
                    raise BoxError(resp.status_code, resp.text[:300] or resp.reason_phrase)
                data, size = [], 0
                for chunk in resp.iter_bytes():
                    data.append(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        break
                return b"".join(data)[:max_bytes].decode("utf-8", errors="replace"), ""
        raise BoxError(401, "Unauthorized")

# Authored by Caleb A. Morrow
