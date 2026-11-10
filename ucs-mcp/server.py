"""
Cisco UCS Manager MCP Server (read-only)

Exposes UCS Manager XML API queries as MCP tools. Read-only by construction: the client only
implements login/logout and the configResolve* read methods.

Configuration via environment variables:
  UCS_HOST       - UCS Manager hostname (required), e.g. ucs-manager.example.com
  UCS_USERNAME   - Read-only UCS account (required)
  UCS_PASSWORD   - Password (required)
  UCS_VERIFY_SSL - Verify TLS certificate: true/false (default: true)
  UCS_TIMEOUT    - Request timeout in seconds (default: 60)
"""

import atexit
import json
import logging
import os
import sys
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import UcsClient, UcsError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("UCS-Manager")

_client: Optional[UcsClient] = None

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "warning": 3, "condition": 4, "info": 5, "cleared": 6}


def get_client() -> UcsClient:
    global _client
    if _client is None:
        host = os.environ.get("UCS_HOST", "").strip()
        username = os.environ.get("UCS_USERNAME", "").strip()
        password = os.environ.get("UCS_PASSWORD", "")
        verify_ssl = os.environ.get("UCS_VERIFY_SSL", "true").lower() == "true"
        timeout = float(os.environ.get("UCS_TIMEOUT", "60"))
        if not host:
            raise RuntimeError("UCS_HOST environment variable is required")
        if not username or not password:
            raise RuntimeError("UCS_USERNAME and UCS_PASSWORD are required")
        _client = UcsClient(host, username, password, verify_ssl, timeout)
        atexit.register(_client.close)  # release the UCS session on shutdown
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, UcsError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


def _pick(obj: dict, *fields: str) -> dict:
    return {f: obj.get(f) for f in fields if obj.get(f) not in (None, "")}


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


SERVER_FIELDS = (
    "dn", "model", "serial", "vendor", "operState", "operability", "operPower", "presence",
    "association", "assignedToDn", "availability", "numOfCpus", "numOfCores", "numOfThreads",
    "totalMemory", "availableMemory", "usrLbl", "name",
)


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------


@mcp.tool()
def list_blades(chassis: Optional[int] = None) -> str:
    """
    List blade servers: DN, model, serial, power and operational state, association to a service
    profile (assignedToDn), CPU/core counts and total memory (MB).

    Args:
        chassis: Only blades in this chassis number (optional).
    """
    try:
        blades = get_client().resolve_class("computeBlade")
        if chassis is not None:
            blades = [b for b in blades if b.get("dn", "").startswith(f"sys/chassis-{chassis}/")]
        blades = [_pick(b, *SERVER_FIELDS, "chassisId", "slotId") for b in blades]
        blades.sort(key=lambda b: (_to_int(b.get("chassisId")), _to_int(b.get("slotId"))))
        return _ok({"total": len(blades), "blades": blades})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_rack_servers() -> str:
    """
    List UCS-managed rack servers (C-Series): DN, model, serial, state, association, CPU and memory.
    """
    try:
        racks = [_pick(r, *SERVER_FIELDS, "id") for r in get_client().resolve_class("computeRackUnit")]
        return _ok({"total": len(racks), "rack_servers": racks})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_server(dn: str) -> str:
    """
    Detail for one blade or rack server: identity and state, CPUs (model, cores, speed) and memory
    (populated DIMMs, per-DIMM size and total).

    Args:
        dn: Server DN, e.g. 'sys/chassis-2/blade-3' or 'sys/rack-unit-1' (from list_blades).
    """
    try:
        c = get_client()
        dn = dn.rstrip("/")
        server = c.resolve_dn(dn)
        if not server:
            return _ok({"error": f"No object at {dn}"})
        prefix = dn + "/"
        cpus = [
            _pick(p, "dn", "model", "cores", "coresEnabled", "threads", "speed", "operState", "presence")
            for p in c.resolve_class("processorUnit") if p.get("dn", "").startswith(prefix)
        ]
        dimms = [
            m for m in c.resolve_class("memoryUnit")
            if m.get("dn", "").startswith(prefix) and m.get("presence", "").startswith("equipped")
        ]
        sizes: dict = {}
        for m in dimms:
            sizes[m.get("capacity", "?")] = sizes.get(m.get("capacity", "?"), 0) + 1
        return _ok({
            "server": _pick(server[0], *SERVER_FIELDS, "chassisId", "slotId", "id", "uuid", "originalUuid"),
            "cpus": cpus,
            "memory": {
                "populated_dimms": len(dimms),
                "total_mb": sum(_to_int(m.get("capacity")) for m in dimms),
                "dimms_by_capacity_mb": sizes,
                "clock": sorted({m.get("clock") for m in dimms if m.get("clock")}),
            },
        })
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Service profiles
# ---------------------------------------------------------------------------


@mcp.tool()
def list_service_profiles(name: Optional[str] = None, include_templates: bool = False) -> str:
    """
    List service profiles: name, association state, the server they're bound to (pnDn), and
    operational state.

    Args:
        name:              Filter by profile name, case-insensitive substring (optional).
        include_templates: Also include service profile templates (default False).
    """
    try:
        profiles = get_client().resolve_class("lsServer")
        if not include_templates:
            profiles = [p for p in profiles if p.get("type") == "instance"]
        if name:
            profiles = [p for p in profiles if name.lower() in p.get("name", "").lower()]
        profiles = [
            _pick(p, "name", "dn", "type", "assocState", "assignState", "operState", "configState",
                  "pnDn", "srcTemplName", "descr", "usrLbl")
            for p in profiles
        ]
        profiles.sort(key=lambda p: p.get("name", ""))
        return _ok({"total": len(profiles), "service_profiles": profiles})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@mcp.tool()
def list_faults(severity: Optional[str] = None, include_cleared: bool = False, limit: int = 100) -> str:
    """
    List UCS faults, most severe first then newest.

    Args:
        severity:        Minimum severity: 'critical', 'major', 'minor', 'warning', 'info' (optional).
        include_cleared: Include faults already cleared (default False).
        limit:           Maximum faults to return (default 100).
    """
    try:
        faults = get_client().resolve_class("faultInst")
        if not include_cleared:
            faults = [f for f in faults if f.get("severity") != "cleared"]
        if severity:
            ceiling = SEVERITY_ORDER.get(severity.lower())
            if ceiling is None:
                return _ok({"error": f"Unknown severity '{severity}'", "valid": list(SEVERITY_ORDER)})
            faults = [f for f in faults if SEVERITY_ORDER.get(f.get("severity", ""), 99) <= ceiling]
        faults.sort(key=lambda f: f.get("lastTransition", ""), reverse=True)
        faults.sort(key=lambda f: SEVERITY_ORDER.get(f.get("severity", ""), 99))
        by_severity: dict = {}
        for f in faults:
            by_severity[f.get("severity")] = by_severity.get(f.get("severity"), 0) + 1
        faults = [
            _pick(f, "severity", "code", "cause", "descr", "dn", "created", "lastTransition", "occur", "ack", "type")
            for f in faults
        ]
        return _ok({"matched": len(faults), "by_severity": by_severity, "returned": min(len(faults), limit), "faults": faults[:limit]})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_chassis() -> str:
    """
    List chassis: ID, model, serial, operational, power and thermal state.
    """
    try:
        chassis = [
            _pick(c, "dn", "id", "model", "serial", "operState", "operability", "power", "thermal", "presence")
            for c in get_client().resolve_class("equipmentChassis")
        ]
        return _ok({"total": len(chassis), "chassis": chassis})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_fabric_interconnects() -> str:
    """
    List fabric interconnects (A/B): model, serial, out-of-band IP, operability and HA role,
    plus the UCS system name, mode and uptime.
    """
    try:
        c = get_client()
        fis = [
            _pick(n, "dn", "id", "model", "serial", "oobIfIp", "oobIfMask", "oobIfGw", "operability", "thermal")
            for n in c.resolve_class("networkElement")
        ]
        system = [_pick(s, "name", "mode", "address", "systemUpTime", "currentTime", "site") for s in c.resolve_class("topSystem")]
        return _ok({"system": system[0] if system else None, "fabric_interconnects": fis})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_firmware(dn_prefix: Optional[str] = None) -> str:
    """
    Summarize running firmware: count of components per (type, version). Use dn_prefix to look at
    one server or chassis.

    Args:
        dn_prefix: Only components under this DN, e.g. 'sys/chassis-2/blade-3' (optional).
    """
    try:
        running = get_client().resolve_class("firmwareRunning")
        if dn_prefix:
            running = [r for r in running if r.get("dn", "").startswith(dn_prefix.rstrip("/") + "/")]
        summary: dict = {}
        for r in running:
            key = (r.get("type") or "?", r.get("version") or r.get("packageVersion") or "?")
            summary[key] = summary.get(key, 0) + 1
        rows = [{"type": t, "version": v, "count": n} for (t, v), n in sorted(summary.items())]
        return _ok({"components": len(running), "versions": rows})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Read-only escape hatches
# ---------------------------------------------------------------------------


@mcp.tool()
def get_object(dn: str, hierarchical: bool = False) -> str:
    """
    Read one UCS managed object by DN (configResolveDn), optionally with all its children.
    Hierarchical results can be large; prefer a specific DN.

    Args:
        dn:           Managed object DN, e.g. 'sys/chassis-1' or 'org-root/ls-ai01'.
        hierarchical: Include all child objects (default False).
    """
    try:
        objects = get_client().resolve_dn(dn, hierarchical)
        return _ok({"total": len(objects), "objects": objects})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def resolve_class(class_id: str, dn_prefix: Optional[str] = None, limit: int = 200) -> str:
    """
    Read all managed objects of a UCS class (configResolveClass) for anything not covered by a
    dedicated tool, e.g. 'adaptorUnit', 'vnicEther', 'equipmentPsu', 'equipmentFan', 'storageLocalDisk',
    'fabricVlan', 'macpoolPool'.

    Args:
        class_id:  UCS class ID (case-sensitive).
        dn_prefix: Only objects whose DN starts with this (optional).
        limit:     Maximum objects to return (default 200).
    """
    try:
        objects = get_client().resolve_class(class_id)
        if dn_prefix:
            objects = [o for o in objects if o.get("dn", "").startswith(dn_prefix)]
        return _ok({"matched": len(objects), "returned": min(len(objects), limit), "objects": objects[:limit]})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
