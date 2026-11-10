"""
WinRM / JEA client for the read-only ReadOnly endpoint.

Every call opens a short-lived PowerShell remoting runspace against the JEA configuration
"ReadOnly" on one allow-listed server and invokes exactly one Get-Ro* function. The endpoint
itself only exposes those functions (NoLanguage mode, no shell), so nothing here can write.
"""

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from pypsrp.powershell import PowerShell, RunspacePool
from pypsrp.wsman import WSMan

CONFIGURATION_NAME = "ReadOnly"
HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}(\.[a-z0-9\-]{1,63})+$")
# Remoting bookkeeping properties that add noise to every object
_NOISE = {"PSComputerName", "RunspaceId", "PSShowComputerName"}


class WinRmError(Exception):
    pass


PROFILE_PATTERN = re.compile(r"^[a-z0-9]{1,20}$")


def load_allowed_servers(path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Return ({name: note}, {name: {"address": ..., "credential": ...}}) from servers.json.

    "address" (optional) is what the client connects to when the name is not in DNS (the DMZ
    servers); "credential" (optional) names a credential profile loaded from WINRM_CRED_<NAME>_*
    environment variables, for servers outside the default CORP domain.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    servers: dict[str, str] = {}
    options: dict[str, dict[str, str]] = {}
    for entry in data.get("servers", []):
        name = str(entry["name"]).strip().lower()
        if not HOST_PATTERN.match(name):
            raise WinRmError(f"Invalid server name in {path.name}: {name!r}")
        servers[name] = str(entry.get("note", ""))
        opts: dict[str, str] = {}
        address = str(entry.get("address", "")).strip().lower()
        if address:
            if not HOST_PATTERN.match(address):
                raise WinRmError(f"Invalid address for {name} in {path.name}: {address!r}")
            opts["address"] = address
        profile = str(entry.get("credential", "")).strip().lower()
        if profile:
            if not PROFILE_PATTERN.match(profile):
                raise WinRmError(f"Invalid credential profile for {name} in {path.name}: {profile!r}")
            opts["credential"] = profile
        if opts:
            options[name] = opts
    return servers, options


def _convert(value: Any) -> Any:
    """Turn pypsrp deserialized objects into plain JSON-able values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_convert(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _convert(v) for k, v in value.items()}
    ext = getattr(value, "extended_properties", None)
    adapted = getattr(value, "adapted_properties", None)
    if ext is not None or adapted is not None:
        merged = {**(dict(adapted) if adapted else {}), **(dict(ext) if ext else {})}
        if merged:
            return {k: _convert(v) for k, v in merged.items() if k not in _NOISE}
    return str(value)


class WinRmClient:
    def __init__(self, username: str, password: str, servers: dict[str, str],
                 port: int = 5985, timeout: int = 120,
                 server_options: Optional[dict[str, dict[str, str]]] = None,
                 profiles: Optional[dict[str, tuple[str, str]]] = None):
        if not username or not password:
            raise WinRmError("WINRM_USERNAME and WINRM_PASSWORD are required")
        self._username = username
        self._password = password
        self.servers = servers
        self._port = port
        self._timeout = timeout
        self._options = server_options or {}
        self._profiles = profiles or {}

    def _check_server(self, server: str) -> str:
        name = (server or "").strip().lower()
        if name not in self.servers:
            allowed = ", ".join(sorted(self.servers)) or "(none)"
            raise WinRmError(f"Server {server!r} is not in the allow-list. Allowed: {allowed}")
        return name

    def invoke(self, server: str, function: str, parameters: Optional[dict[str, Any]] = None) -> list[Any]:
        """Run one Get-Ro* function on the server's ReadOnly endpoint and return plain objects."""
        host = self._check_server(server)
        if not re.fullmatch(r"Get-Ro[A-Za-z]{2,40}", function):
            raise WinRmError(f"Refusing to run {function!r}")
        opts = self._options.get(host, {})
        username, password = self._username, self._password
        if "credential" in opts:
            if opts["credential"] not in self._profiles:
                raise WinRmError(f"{host}: credential profile {opts['credential']!r} is not loaded")
            username, password = self._profiles[opts["credential"]]
        wsman = WSMan(
            opts.get("address", host), ssl=False, port=self._port, auth="negotiate",
            username=username, password=password,
            operation_timeout=self._timeout, read_timeout=self._timeout + 30,
            connection_timeout=30,
        )
        try:
            with RunspacePool(wsman, configuration_name=CONFIGURATION_NAME) as pool:
                ps = PowerShell(pool)
                ps.add_cmdlet(function)
                for key, value in (parameters or {}).items():
                    if value is not None:
                        ps.add_parameter(key, value)
                output = ps.invoke()
                errors = [str(e) for e in ps.streams.error]
        except Exception as exc:  # connection/auth failures: never echo the password
            raise WinRmError(f"{host}: {type(exc).__name__}: {str(exc)[:300]}") from None
        if errors and not output:
            raise WinRmError(f"{host}: {errors[0][:500]}")
        return [_convert(o) for o in output]


def hours_ago(hours: int) -> str:
    """UTC ISO timestamp. pypsrp can't serialize datetime parameters, and PowerShell converts the
    string to [datetime] (as local time) when it binds the parameter on the server."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_env(base: Path) -> WinRmClient:
    servers_file = Path(os.environ.get("WINRM_SERVERS_FILE", base / "servers.json"))
    servers, options = load_allowed_servers(servers_file)
    # Extra credential profiles: WINRM_CRED_<NAME>_USERNAME / WINRM_CRED_<NAME>_PASSWORD
    profiles: dict[str, tuple[str, str]] = {}
    for key, value in os.environ.items():
        m = re.fullmatch(r"WINRM_CRED_([A-Z0-9]{1,20})_USERNAME", key)
        if m and value.strip() and os.environ.get(f"WINRM_CRED_{m.group(1)}_PASSWORD"):
            profiles[m.group(1).lower()] = (value.strip(), os.environ[f"WINRM_CRED_{m.group(1)}_PASSWORD"])
    return WinRmClient(
        username=os.environ.get("WINRM_USERNAME", "").strip(),
        password=os.environ.get("WINRM_PASSWORD", ""),
        servers=servers,
        port=int(os.environ.get("WINRM_PORT", "5985")),
        timeout=int(os.environ.get("WINRM_TIMEOUT", "120")),
        server_options=options,
        profiles=profiles,
    )
