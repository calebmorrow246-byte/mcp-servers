"""Device42 REST API v1.0 client."""

import logging
import ssl
from typing import Any, Optional

import httpx
import truststore

logger = logging.getLogger(__name__)


class Device42Error(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class Device42Client:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ):
        self.host = host
        self.base_url = f"https://{host}"
        # Verify against the Windows certificate store: d42.example.com sends only its leaf
        # certificate, and Windows fetches the missing Let's Encrypt intermediates (AIA) where
        # Python's own bundle can't.
        verify: Any = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if verify_ssl else False
        self._http = httpx.Client(
            auth=(username, password) if password else None,
            verify=verify,
            timeout=timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def set_token(self, token: str) -> None:
        """Switch to API token auth (overrides Basic auth)."""
        self._http.auth = None
        self._http.headers["Authorization"] = f"Token {token}"

    def get(self, path: str, params: Optional[dict] = None, auth: Optional[tuple] = None) -> Any:
        """GET; `auth` is an optional (username, password) used for this request only instead of the shared account."""
        url = f"{self.base_url}{path}"
        kwargs: dict = {"auth": auth} if auth else {}
        resp = self._http.get(url, params=params or {}, **kwargs)
        self._raise_for_error(resp)
        return resp.json()

    def post_form(self, path: str, data: dict, auth: tuple) -> Any:
        """POST form-encoded data (Device42's write API) as the given (username, password) for this request only."""
        url = f"{self.base_url}{path}"
        resp = self._http.post(url, data=data, auth=auth,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        self._raise_for_error(resp)
        return resp.json()

    def get_all(self, path: str, params: Optional[dict] = None, page_size: int = 500) -> list:
        """Paginate through all records using Device42's limit/offset scheme."""
        params = dict(params or {})
        params["limit"] = page_size
        params["offset"] = 0
        records: list = []
        while True:
            data = self.get(path, params)
            # Device42 wraps results in a key matching the resource name;
            # find the list value (not total_count / limit / offset)
            batch: list = []
            for val in data.values():
                if isinstance(val, list):
                    batch = val
                    break
            records.extend(batch)
            total = data.get("total_count", len(records))
            params["offset"] += page_size
            if params["offset"] >= total or not batch:
                break
        return records

    def _raise_for_error(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise Device42Error("401", "Authentication failed — check username and password")
        if resp.status_code == 403:
            raise Device42Error("403", "Not authorized — account lacks required permissions")
        try:
            data = resp.json()
            # Device42 also answers a successful write with a msg list and code 0, so only a nonzero code is an error
            if isinstance(data, dict) and data.get("msg") and data.get("code") not in (0, "0"):
                msg = data["msg"]
                if isinstance(msg, list):
                    raise Device42Error(data.get("code", "error"), " ".join(str(m) for m in msg))
        except (ValueError, KeyError):
            pass
        resp.raise_for_status()

    def close(self) -> None:
        self._http.close()
