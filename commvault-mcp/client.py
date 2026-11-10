"""Commvault REST API client with session-based auth (classic /Login; verified on CommServe 11.40)."""

import base64
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class CommvaultError(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class CommvaultClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: float = 30.0,
        api_path: str = "/commandcenter/api",
    ):
        self.host = host
        self.base_url = f"https://{host}{api_path}"
        self._username = username
        self._password = password
        self._token: Optional[str] = None
        self._http = httpx.Client(
            verify=verify_ssl,
            timeout=timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def _login(self) -> None:
        # The classic /Login endpoint takes the password Base64-encoded. On 11.40, /v4/user/login
        # returns 403. A failed login still returns HTTP 200 with errList, e.g. the two-factor prompt.
        url = f"{self.base_url}/Login"
        encoded = base64.b64encode(self._password.encode("utf-8")).decode("ascii")
        resp = self._http.post(url, json={"username": self._username, "password": encoded})
        if resp.status_code not in (200, 201):
            raise CommvaultError(resp.status_code, f"Login failed: HTTP {resp.status_code}")
        data = resp.json()
        token = data.get("token") or data.get("authToken") or data.get("Authtoken")
        if not token:
            errors = data.get("errList") or []
            detail = errors[0].get("errLogMessage") if errors else "no token in login response"
            raise CommvaultError("auth", f"Login failed: {detail}")
        self._token = token
        self._http.headers["Authtoken"] = token

    def _ensure_auth(self) -> None:
        if not self._token:
            self._login()

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        """Authenticated GET; re-logs in on 401."""
        self._ensure_auth()
        url = f"{self.base_url}{path}"
        resp = self._http.get(url, params=params or {})
        if resp.status_code == 401:
            self._token = None
            self._login()
            resp = self._http.get(url, params=params or {})
        self._raise_for_error(resp)
        # Some endpoints (e.g. /Alert with nothing triggered) return a JSON null
        return resp.json() if resp.content else None

    def get_paged(self, path: str, params: Optional[dict] = None, limit: int = 200) -> list:
        """Fetch all records from a paginated endpoint using limit/offset."""
        params = dict(params or {})
        params["limit"] = limit
        params["offset"] = 0
        records: list = []
        while True:
            data = self.get(path, params)
            # Commvault wraps results under different keys depending on endpoint
            batch = (
                data.get("jobs")
                or data.get("clientProperties")
                or data.get("clients")
                or data.get("eventList")
                or data.get("alertList")
                or data.get("storagePoolList")
                or data.get("subClientProperties")
                or data.get("backupsetProperties")
                or data.get("plans")
                or data.get("records")
                or []
            )
            if isinstance(batch, list):
                records.extend(batch)
            else:
                # Single-object response (not a collection)
                return [data]
            if len(batch) < limit:
                break
            params["offset"] += limit
        return records

    def _raise_for_error(self, resp: httpx.Response) -> None:
        if resp.status_code == 403:
            raise CommvaultError("403", "Not authorized — check account permissions")
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            return
        # Commvault error envelope (bodies can also be a list or JSON null)
        err_list = (data.get("errorList") or []) if isinstance(data, dict) else []
        if err_list:
            e = err_list[0]
            raise CommvaultError(e.get("errorCode", "unknown"), e.get("errLogMessage") or e.get("errorMessage", "Unknown error"))
        resp.raise_for_status()

    def close(self) -> None:
        if self._token:
            try:
                self._http.post(f"{self.base_url}/Logout")
            except Exception:
                pass
        self._http.close()
