"""Cisco UCS Manager XML API client (read-only).

Only the session methods (aaaLogin / aaaLogout) and read methods (configResolveClass,
configResolveDn) are implemented. Nothing that changes configuration (configConfMo and similar)
exists here, so this client can't modify UCS even with a write-capable account.
"""

import logging
import ssl
import threading
import xml.etree.ElementTree as ET
from typing import Any, Optional
from xml.sax.saxutils import quoteattr

import httpx
import truststore

logger = logging.getLogger(__name__)

# UCSM error codes that mean the session cookie is no longer valid
SESSION_ERRORS = {"552", "555"}


class UcsError(Exception):
    def __init__(self, code: Any, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class UcsClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: float = 60.0,
    ):
        self.url = f"https://{host}/nuova"
        self._username = username
        self._password = password
        self._cookie: Optional[str] = None
        self._lock = threading.Lock()
        # Verify against the Windows certificate store (ucs-manager has a public GoDaddy certificate)
        verify: Any = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if verify_ssl else False
        self._http = httpx.Client(verify=verify, timeout=timeout, headers={"Content-Type": "application/xml"})

    def _post(self, body: str) -> ET.Element:
        resp = self._http.post(self.url, content=body.encode("utf-8"))
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        code = root.get("errorCode")
        if code:
            raise UcsError(code, root.get("errorDescr") or "UCS Manager error")
        return root

    def _login(self) -> None:
        # quoteattr XML-escapes the password (UCS rejects unescaped & < > " in inPassword)
        root = self._post(f"<aaaLogin inName={quoteattr(self._username)} inPassword={quoteattr(self._password)}/>")
        cookie = root.get("outCookie")
        if not cookie:
            raise UcsError("auth", "Login succeeded but no session cookie was returned")
        self._cookie = cookie

    def _session_cookie(self) -> str:
        # One shared session: UCSM caps concurrent sessions per user, so don't log in per call
        with self._lock:
            if not self._cookie:
                self._login()
            return self._cookie  # type: ignore[return-value]

    def _query(self, template: str) -> ET.Element:
        """Run a read query; log in again once if the session has expired."""
        for attempt in (1, 2):
            cookie = self._session_cookie()
            try:
                return self._post(template.replace("{cookie}", quoteattr(cookie)))
            except UcsError as exc:
                if str(exc.code) in SESSION_ERRORS and attempt == 1:
                    with self._lock:
                        if self._cookie == cookie:
                            self._cookie = None
                    continue
                raise
        raise UcsError("session", "Could not establish a UCS Manager session")

    @staticmethod
    def _objects(root: ET.Element) -> list:
        """Flatten outConfigs/outConfig children into a list of {class, ...attributes}."""
        container = root.find("outConfigs")
        if container is None:
            container = root.find("outConfig")
        if container is None:
            return []
        return [dict(el.attrib, _class=el.tag) for el in container]

    def resolve_class(self, class_id: str, hierarchical: bool = False) -> list:
        """All managed objects of one class (configResolveClass)."""
        template = (
            f"<configResolveClass cookie={{cookie}} inHierarchical={quoteattr(str(hierarchical).lower())} "
            f"classId={quoteattr(class_id)}/>"
        )
        return self._objects(self._query(template))

    def resolve_dn(self, dn: str, hierarchical: bool = False) -> list:
        """One managed object by DN, optionally with all its children (configResolveDn)."""
        template = (
            f"<configResolveDn cookie={{cookie}} inHierarchical={quoteattr(str(hierarchical).lower())} "
            f"dn={quoteattr(dn)}/>"
        )
        root = self._query(template)
        container = root.find("outConfig")
        if container is None:
            return []
        out: list = []

        def walk(el: ET.Element) -> None:
            out.append(dict(el.attrib, _class=el.tag))
            for child in el:
                walk(child)

        for el in container:
            walk(el)
        return out

    def close(self) -> None:
        with self._lock:
            if self._cookie:
                try:
                    self._post(f"<aaaLogout inCookie={quoteattr(self._cookie)}/>")
                except Exception:
                    pass
                self._cookie = None
        self._http.close()
