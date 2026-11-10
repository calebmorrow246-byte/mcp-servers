# Authored by Caleb A. Morrow
"""
Read-only Mend REST API 3.0 client.

Authenticates as the shared service account (userKey login, then refresh-token to JWT exchange),
renews the JWT before it expires, and issues only GET requests to paths that appear in
endpoints.json (the GET operations of Mend's published OpenAPI description). There is no write path.
"""

import json
import os
import re
import threading
import time
from typing import Any, Optional

import httpx
import truststore

truststore.inject_into_ssl()

API_BASE = "https://api-saas.whitesourcesoftware.com/api/v3.0"
RENEW_MARGIN_SECONDS = 120
DEFAULT_TTL_SECONDS = 1800  # Mend JWTs last 30 minutes
MAX_RESPONSE_CHARS = 400_000


class MendError(Exception):
    def __init__(self, code: Any, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _load_templates() -> list[tuple[re.Pattern, dict]]:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endpoints.json")
    with open(path, encoding="utf-8") as f:
        endpoints = json.load(f)
    templates = []
    for endpoint in endpoints:
        pattern = "^" + re.sub(r"\\\{[^/]+?\\\}", "[0-9A-Za-z_.-]+", re.escape(endpoint["path"])) + "$"
        templates.append((re.compile(pattern), endpoint))
    return templates


TEMPLATES = _load_templates()


def endpoint_for(path: str) -> Optional[dict]:
    """The allow-listed GET endpoint matching a concrete path, or None."""
    if "//" in path or ".." in path or "%" in path or "?" in path or not path.startswith("/"):
        return None
    for pattern, endpoint in TEMPLATES:
        if pattern.match(path):
            return endpoint
    return None


class MendClient:
    def __init__(self, user_key: str, email: str, org_uuid: str, timeout: float = 60.0):
        self.user_key = user_key
        self.email = email
        self.org_uuid = org_uuid
        self._http = httpx.Client(timeout=timeout)
        self._lock = threading.Lock()
        self._jwt: Optional[str] = None
        self._expires = 0.0

    def _login(self) -> None:
        login = self._http.post(f"{API_BASE}/login", json={
            "email": self.email, "orgUuid": self.org_uuid, "userKey": self.user_key})
        if login.status_code != 200:
            raise MendError(login.status_code, "Mend login failed (check the Mend API credential)")
        refresh = login.json()["response"]["refreshToken"]
        access = self._http.post(f"{API_BASE}/login/accessToken", json={},
                                 headers={"wss-refresh-token": refresh})
        if access.status_code != 200:
            raise MendError(access.status_code, "Mend access token exchange failed")
        body = access.json()["response"]
        self._jwt = body["jwtToken"]
        ttl = body.get("tokenTTL") or body.get("jwtTTL") or DEFAULT_TTL_SECONDS
        try:
            ttl = float(ttl)
            ttl = ttl / 1000 if ttl > 100_000 else ttl  # tolerate milliseconds
        except (TypeError, ValueError):
            ttl = DEFAULT_TTL_SECONDS
        self._expires = time.time() + ttl

    def _bearer(self, force: bool = False) -> str:
        with self._lock:
            if force or not self._jwt or time.time() > self._expires - RENEW_MARGIN_SECONDS:
                self._login()
            return self._jwt  # type: ignore[return-value]

    def token_status(self) -> dict:
        self._bearer()
        return {"authenticated": True, "org": self.org_uuid, "user": self.email,
                "seconds_until_renewal": max(0, int(self._expires - RENEW_MARGIN_SECONDS - time.time()))}

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        path = path.replace("{orgUuid}", self.org_uuid)
        if endpoint_for(path) is None:
            raise MendError("not_allowed", "Path is not an allow-listed Mend GET endpoint (see list_endpoints)")
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        for attempt in (1, 2):
            response = self._http.get(f"{API_BASE}{path}", params=clean,
                                      headers={"Authorization": f"Bearer {self._bearer(force=attempt == 2)}"})
            if response.status_code != 401 or attempt == 2:
                break
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                detail = str(body.get("response") or body.get("message") or body.get("error") or "")[:300]
            except ValueError:
                pass
            raise MendError(response.status_code, f"Mend API returned HTTP {response.status_code}. {detail}".strip())
        ctype = response.headers.get("content-type", "")
        if "json" in ctype:
            return response.json()
        text = response.text
        return {"content_type": ctype, "text": text[:MAX_RESPONSE_CHARS], "truncated": len(text) > MAX_RESPONSE_CHARS}


def upstream_tools_call(url: str, headers: dict, name: str, arguments: dict, timeout: float = 120.0) -> Any:
    """Call a tool on Mend's hosted MCP endpoint (stateless Streamable HTTP) and return its text content."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    response = httpx.post(url, json=payload, timeout=timeout,
                          headers={**headers, "Accept": "application/json, text/event-stream"})
    if response.status_code != 200:
        raise MendError(response.status_code, f"Mend MCP returned HTTP {response.status_code}")
    text = response.text
    if "text/event-stream" in response.headers.get("content-type", ""):
        datas = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = datas[-1] if datas else "{}"
    message = json.loads(text)
    if "error" in message:
        raise MendError(message["error"].get("code"), str(message["error"].get("message", "upstream error"))[:300])
    result = message.get("result", {})
    parts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    return {"isError": bool(result.get("isError")), "text": "\n".join(parts)}

# Authored by Caleb A. Morrow
