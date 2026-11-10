"""NetApp ONTAP REST API client."""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class OntapError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class OntapClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ):
        self.host = host
        self.base_url = f"https://{host}/api"
        self._http = httpx.Client(
            auth=(username, password),
            verify=verify_ssl,
            timeout=timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        """Make an authenticated GET request; returns the parsed JSON body."""
        url = f"{self.base_url}{path}"
        resp = self._http.get(url, params=params or {})
        self._raise_for_ontap_error(resp)
        return resp.json()

    def get_all(
        self, path: str, params: Optional[dict] = None, max_records: int = 1000
    ) -> list:
        """Paginate through all records for a collection endpoint."""
        params = dict(params or {})
        params.setdefault("max_records", max_records)
        records: list = []
        url = f"{self.base_url}{path}"
        while url:
            resp = self._http.get(url, params=params)
            self._raise_for_ontap_error(resp)
            data = resp.json()
            records.extend(data.get("records", []))
            next_href = data.get("_links", {}).get("next", {}).get("href")
            url = f"https://{self.host}{next_href}" if next_href else None
            params = {}  # pagination params are embedded in next_href
        return records

    def _raise_for_ontap_error(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise OntapError("401", "Authentication failed — check username and password")
        if resp.status_code == 403:
            raise OntapError("403", "Not authorized — user lacks required role")
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            return
        if "error" in data:
            err = data["error"]
            raise OntapError(
                str(err.get("code", "unknown")),
                err.get("message", "Unknown ONTAP error"),
            )
        resp.raise_for_status()

    def close(self) -> None:
        self._http.close()
