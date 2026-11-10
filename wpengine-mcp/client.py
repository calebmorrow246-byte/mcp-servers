"""WP Engine Hosting Platform API client (v1).

Path templates confirmed against https://developers.wpengine.com/docs/managed-hosting-platform/api/reference
(2026-09-30). WP Engine's account-level API user/password has no read-only scope of its own — this
client is a thin pass-through, and the read-only guarantee for this MCP server comes entirely from
which tool functions in server.py are wired up to call it, not from the credential.
"""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class WPEngineError(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class WPEngineClient:
    def __init__(
        self,
        username: str,
        password: str,
        timeout: float = 30.0,
    ):
        self.base_url = "https://api.wpengineapi.com/v1"
        self._http = httpx.Client(
            auth=(username, password),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        resp = self._http.get(f"{self.base_url}{path}", params=params or {})
        self._raise_for_error(resp)
        return resp.json()

    def post(self, path: str, json_body: Optional[dict] = None) -> Any:
        resp = self._http.post(f"{self.base_url}{path}", json=json_body or {})
        self._raise_for_error(resp)
        if resp.status_code == 204 or not resp.content:
            return {"status": "ok"}
        return resp.json()

    def _raise_for_error(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise WPEngineError(401, "Authentication failed — check the WPEngine API user/password")
        if resp.status_code == 403:
            raise WPEngineError(403, "Not authorized for this operation")
        if resp.status_code == 404:
            raise WPEngineError(404, "Not found")
        if resp.status_code >= 400:
            try:
                data = resp.json()
                msg = data.get("message") or data.get("error") or str(data)
            except ValueError:
                msg = resp.text or resp.reason_phrase
            raise WPEngineError(resp.status_code, msg)

    def close(self) -> None:
        self._http.close()
