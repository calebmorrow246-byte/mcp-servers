# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
"""XenServer JSON-RPC 2.0 client."""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class XenServerError(Exception):
    def __init__(self, error_description: list[str]):
        self.error_description = error_description
        super().__init__(" | ".join(str(x) for x in error_description))


class XenServerClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: float = 60.0,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.base_url = f"https://{host}/jsonrpc"
        self.session_ref: Optional[str] = None
        self._request_id = 0
        self._http = httpx.Client(verify=verify_ssl, timeout=timeout)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _rpc(self, method: str, params: list) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._next_id(),
        }
        resp = self._http.post(self.base_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            err = data["error"]
            # Keep the error code (e.g. HOST_IS_SLAVE) ahead of its parameters (e.g. the master's address)
            message = err.get("message", "Unknown error")
            detail = err.get("data") or []
            raise XenServerError([message] + (detail if isinstance(detail, list) else [detail]))

        result = data.get("result", {})
        if isinstance(result, dict):
            status = result.get("Status")
            if status == "Failure":
                raise XenServerError(
                    result.get("ErrorDescription", ["Unknown failure"])
                )
            if status == "Success":
                return result.get("Value")
        return result

    def connect(self) -> str:
        login = [self.username, self.password, "1.3", "xenserver-mcp"]
        try:
            self.session_ref = self._rpc("session.login_with_password", login)
        except XenServerError as exc:
            # Pool master moved: the host we tried answers HOST_IS_SLAVE with the current master's address
            desc = exc.error_description
            if len(desc) >= 2 and desc[0] == "HOST_IS_SLAVE":
                logger.info("%s is not the pool master; switching to %s", self.host, desc[1])
                self.host = str(desc[1])
                self.base_url = f"https://{self.host}/jsonrpc"
                self.session_ref = self._rpc("session.login_with_password", login)
            else:
                raise
        logger.info("Connected to %s", self.host)
        return self.session_ref

    def disconnect(self) -> None:
        if self.session_ref:
            try:
                self._rpc("session.logout", [self.session_ref])
            except Exception:
                pass
            self.session_ref = None
            logger.info("Disconnected from %s", self.host)

    def _ensure_connected(self) -> None:
        if not self.session_ref:
            self.connect()

    def call(self, method: str, *args: Any) -> Any:
        """Make an authenticated API call, reconnecting if session is stale."""
        self._ensure_connected()
        try:
            return self._rpc(method, [self.session_ref] + list(args))
        except XenServerError as exc:
            if exc.error_description and any(
                "SESSION_INVALID" in str(e) or "SESSION_EXPIRED" in str(e)
                for e in exc.error_description
            ):
                logger.info("Session stale, reconnecting…")
                self.session_ref = None
                self._ensure_connected()
                return self._rpc(method, [self.session_ref] + list(args))
            raise

    def resolve_vm(self, name_or_ref: str) -> str:
        """Return a VM ref from a UUID, opaque ref, or name label."""
        if name_or_ref.startswith("OpaqueRef:"):
            return name_or_ref
        # Try UUID first
        try:
            return self.call("VM.get_by_uuid", name_or_ref)
        except XenServerError:
            pass
        # Fall back to name label
        refs = self.call("VM.get_by_name_label", name_or_ref)
        if not refs:
            raise XenServerError([f"No VM found with name/uuid '{name_or_ref}'"])
        if len(refs) > 1:
            raise XenServerError(
                [f"Multiple VMs match '{name_or_ref}'; use UUID or OpaqueRef"]
            )
        return refs[0]

    def resolve_host(self, name_or_ref: str) -> str:
        if name_or_ref.startswith("OpaqueRef:"):
            return name_or_ref
        try:
            return self.call("host.get_by_uuid", name_or_ref)
        except XenServerError:
            pass
        refs = self.call("host.get_by_name_label", name_or_ref)
        if not refs:
            raise XenServerError([f"No host found with name/uuid '{name_or_ref}'"])
        if len(refs) > 1:
            raise XenServerError(
                [f"Multiple hosts match '{name_or_ref}'; use UUID or OpaqueRef"]
            )
        return refs[0]

    def resolve_sr(self, name_or_ref: str) -> str:
        if name_or_ref.startswith("OpaqueRef:"):
            return name_or_ref
        try:
            return self.call("SR.get_by_uuid", name_or_ref)
        except XenServerError:
            pass
        refs = self.call("SR.get_by_name_label", name_or_ref)
        if not refs:
            raise XenServerError([f"No SR found with name/uuid '{name_or_ref}'"])
        if len(refs) > 1:
            raise XenServerError(
                [f"Multiple SRs match '{name_or_ref}'; use UUID or OpaqueRef"]
            )
        return refs[0]

    def resolve_network(self, name_or_ref: str) -> str:
        if name_or_ref.startswith("OpaqueRef:"):
            return name_or_ref
        try:
            return self.call("network.get_by_uuid", name_or_ref)
        except XenServerError:
            pass
        refs = self.call("network.get_by_name_label", name_or_ref)
        if not refs:
            raise XenServerError(
                [f"No network found with name/uuid '{name_or_ref}'"]
            )
        if len(refs) > 1:
            raise XenServerError(
                [f"Multiple networks match '{name_or_ref}'; use UUID or OpaqueRef"]
            )
        return refs[0]

    def resolve_vdi(self, name_or_ref: str) -> str:
        if name_or_ref.startswith("OpaqueRef:"):
            return name_or_ref
        try:
            return self.call("VDI.get_by_uuid", name_or_ref)
        except XenServerError:
            pass
        refs = self.call("VDI.get_by_name_label", name_or_ref)
        if not refs:
            raise XenServerError([f"No VDI found with name/uuid '{name_or_ref}'"])
        if len(refs) > 1:
            raise XenServerError(
                [f"Multiple VDIs match '{name_or_ref}'; use UUID or OpaqueRef"]
            )
        return refs[0]

    def close(self) -> None:
        self.disconnect()
        self._http.close()
