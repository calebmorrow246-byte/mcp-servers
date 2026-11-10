"""
Device42 MCP Server

Exposes Device42 REST API v1.0 operations as MCP tools. Everything is read-only with the shared service
account, except update_devices, which only writes when the caller sends their OWN Device42 login in the
X-Device42-User / X-Device42-Password headers (Get-McpHeaders.ps1 sends them from the 'D42 API' credential),
so Device42 attributes the change to that person. It defaults to a dry run, only touches an allowlist of
fields, takes at most 25 devices per call, has no delete, and appends every write to a change log.

Configuration via environment variables:
  D42_HOST       - Device42 hostname or IP (required)
  D42_USERNAME   - Service account username (required)
  D42_PASSWORD   - Service account password (required)
  D42_VERIFY_SSL - Verify TLS certificate: true/false (default: false)
  D42_TIMEOUT    - Request timeout in seconds (default: 30)
  D42_CHANGE_LOG - Change log for update_devices writes
                   (default: C:\\ProgramData\\MCP\\logs\\MCP-device42-changes.log)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from mcp.server.mcpserver import MCPServer

from client import Device42Client, Device42Error
from mcp_transport import request_credential, run_server

# Per-user login headers (captured by the transport; values are never logged)
USER_HEADER = "x-device42-user"
PASSWORD_HEADER = "x-device42-password"

# update_devices limits
WRITE_FIELDS = {"notes", "virtual_subtype", "in_service", "service_level"}
MAX_BATCH = 25
CHANGE_LOG = Path(os.environ.get("D42_CHANGE_LOG", r"C:\ProgramData\MCP\logs\MCP-device42-changes.log"))

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("Device42")

_client: Optional[Device42Client] = None


def get_client() -> Device42Client:
    global _client
    if _client is None:
        host = os.environ.get("D42_HOST", "").strip()
        token = os.environ.get("D42_TOKEN", "").strip()
        username = os.environ.get("D42_USERNAME", "").strip()
        password = os.environ.get("D42_PASSWORD", "").strip()
        verify_ssl = os.environ.get("D42_VERIFY_SSL", "false").lower() == "true"
        timeout = float(os.environ.get("D42_TIMEOUT", "30"))
        if not host:
            raise RuntimeError("D42_HOST environment variable is required")
        if not token and (not username or not password):
            raise RuntimeError("Either D42_TOKEN or both D42_USERNAME and D42_PASSWORD are required")
        _client = Device42Client(host, username or "", password or "", verify_ssl, timeout)
        if token:
            _client.set_token(token)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, Device42Error):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


@mcp.tool()
def list_devices(
    name: Optional[str] = None,
    device_type: Optional[str] = None,
    os_name: Optional[str] = None,
    service_level: Optional[str] = None,
    building: Optional[str] = None,
    room: Optional[str] = None,
    rack: Optional[str] = None,
    in_service: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List devices (servers, VMs, network gear, etc.) from Device42.

    Args:
        name:          Filter by device name (partial match supported).
        device_type:   Filter by type — 'physical', 'virtual', 'blade',
                       'cluster', 'other' (optional).
        os_name:       Filter by OS name (optional).
        service_level: Filter by service level — 'production', 'dev', 'qa', etc. (optional).
        building:      Filter by building name (optional).
        room:          Filter by room name (optional).
        rack:          Filter by rack name (optional).
        in_service:    Filter by in-service status — True or False (optional).
        limit:         Records to return (default 100, max 500).
        offset:        Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if name:
            params["name"] = name
        if device_type:
            params["type"] = device_type
        if os_name:
            params["os"] = os_name
        if service_level:
            params["service_level"] = service_level
        if building:
            params["building"] = building
        if room:
            params["room"] = room
        if rack:
            params["rack"] = rack
        if in_service is not None:
            params["in_service"] = "yes" if in_service else "no"
        data = c.get("/api/1.0/devices/", params)
        devices = data.get("Devices", [])
        return _ok({"total_count": data.get("total_count", len(devices)), "Devices": devices})
    except Exception as exc:
        return _err(exc)


DEFAULT_FIND_FIELDS = [
    "name", "device_id", "type", "virtual_subtype", "virtual_host_name",
    "in_service", "os", "service_level", "ip_addresses", "notes",
]


def _compact_device(dev: dict, fields: list) -> dict:
    """Trim a /devices/all/ record to the requested fields; IP address objects become plain strings."""
    out: dict = {}
    for f in fields:
        val = dev.get(f)
        if f == "ip_addresses" and isinstance(val, list):
            val = [ip.get("ip") if isinstance(ip, dict) else ip for ip in val]
        out[f] = val
    return out


@mcp.tool()
def find_devices(
    virtual_subtype: Optional[str] = None,
    virtual_host: Optional[str] = None,
    device_type: Optional[str] = None,
    name_contains: Optional[str] = None,
    os_contains: Optional[str] = None,
    in_service: Optional[bool] = None,
    fields: Optional[str] = None,
    limit: int = 500,
) -> str:
    """
    Find devices by attributes Device42's list API cannot filter on, and return a compact table.
    Pages through every matching device server-side and filters here (case-insensitive), so
    results are complete and small. Use it for questions like "everything with subtype VMWare".

    Args:
        virtual_subtype: Exact virtual subtype, e.g. 'VMWare', 'Xen', 'Citrix/Xen', 'Azure Virtual Machine'.
        virtual_host:    Substring of the virtual host name, e.g. 'xen05' or 'vm0'.
        device_type:     'physical', 'virtual', 'blade', 'cluster', 'other'. Defaults to 'virtual'
                         when virtual_subtype or virtual_host is given, otherwise all types (slow).
        name_contains:   Substring of the device name.
        os_contains:     Substring of the OS name.
        in_service:      True/False to filter on the in-service flag.
        fields:          Comma-separated /devices/all/ fields to return. Default:
                         name, device_id, type, virtual_subtype, virtual_host_name, in_service, os,
                         service_level, ip_addresses, notes.
        limit:           Max devices returned (default 500); total_matches always reports the full count.
    """
    try:
        c = get_client()
        if device_type is None and (virtual_subtype or virtual_host):
            device_type = "virtual"
        params: dict = {}
        if device_type:
            params["type"] = device_type
        devices = c.get_all("/api/1.0/devices/all/", params)

        def has(val: Any, needle: str) -> bool:
            return needle.lower() in str(val or "").lower()

        matches = []
        for d in devices:
            if virtual_subtype and str(d.get("virtual_subtype") or "").lower() != virtual_subtype.lower():
                continue
            if virtual_host and not has(d.get("virtual_host_name"), virtual_host):
                continue
            if name_contains and not has(d.get("name"), name_contains):
                continue
            if os_contains and not has(d.get("os"), os_contains):
                continue
            if in_service is not None and bool(d.get("in_service")) != in_service:
                continue
            matches.append(d)

        wanted = [f.strip() for f in fields.split(",") if f.strip()] if fields else DEFAULT_FIND_FIELDS
        matches.sort(key=lambda d: str(d.get("name") or "").lower())
        shown = matches[:limit]
        return _ok({
            "total_matches": len(matches),
            "returned": len(shown),
            "scanned": len(devices),
            "Devices": [_compact_device(d, wanted) for d in shown],
        })
    except Exception as exc:
        return _err(exc)


def _enrich_with_end_user(c: Device42Client, data: dict) -> dict:
    """Fetch the end user (Intune/MDM user assignment) for a device and merge it in."""
    device_name = data.get("name")
    if not device_name:
        return data
    try:
        eu_data = c.get("/api/1.0/endusers/", {"device": device_name, "limit": 1})
        end_users = eu_data.get("endusers", [])
        if end_users:
            eu = end_users[0]
            data["assigned_user"] = {
                "display_name": eu.get("fullname") or f"{eu.get('first_name', '')} {eu.get('last_name', '')}".strip(),
                "username": eu.get("name"),
                "email": eu.get("email"),
                "end_user_id": eu.get("id"),
            }
    except Exception:
        pass  # End user data is supplemental; don't fail the whole call
    return data


@mcp.tool()
def get_device(device_id: int) -> str:
    """
    Get full details for a specific device by its Device42 ID.
    Includes assigned end user (Intune/MDM user) when available.

    Args:
        device_id: Device42 numeric device ID (from list_devices).
    """
    try:
        c = get_client()
        data = c.get(f"/api/1.0/devices/id/{device_id}/")
        data = _enrich_with_end_user(c, data)
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_device_by_name(name: str) -> str:
    """
    Look up a device by exact name.
    Includes assigned end user (Intune/MDM user) when available.

    Args:
        name: Exact device name (case-insensitive).
    """
    try:
        c = get_client()
        data = c.get(f"/api/1.0/devices/name/{name}/")
        data = _enrich_with_end_user(c, data)
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# IP Addresses
# ---------------------------------------------------------------------------


@mcp.tool()
def list_ips(
    ip_address: Optional[str] = None,
    device: Optional[str] = None,
    subnet: Optional[str] = None,
    available: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List IP address records from Device42 IPAM.

    Args:
        ip_address: Filter by IP address (exact or partial).
        device:     Filter by device name (optional).
        subnet:     Filter by subnet network (e.g. '192.0.2.0') (optional).
        available:  Filter to available (unassigned) IPs only (optional).
        limit:      Records to return (default 100).
        offset:     Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if ip_address:
            params["ip_address"] = ip_address
        if device:
            params["device"] = device
        if subnet:
            params["subnet"] = subnet
        if available is not None:
            params["available"] = "yes" if available else "no"
        data = c.get("/api/1.0/ips/", params)
        ips = data.get("ips", [])
        return _ok({"total_count": data.get("total_count", len(ips)), "ips": ips})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------


@mcp.tool()
def list_subnets(
    network: Optional[str] = None,
    vlan: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List subnets from Device42 IPAM.

    Args:
        network: Filter by network address (e.g. '10.0.0.0') (optional).
        vlan:    Filter by VLAN name or number (optional).
        limit:   Records to return (default 100).
        offset:  Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if network:
            params["network"] = network
        if vlan:
            params["vlan"] = vlan
        data = c.get("/api/1.0/subnets/", params)
        subnets = data.get("subnets", [])
        return _ok({"total_count": data.get("total_count", len(subnets)), "subnets": subnets})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# VLANs
# ---------------------------------------------------------------------------


@mcp.tool()
def list_vlans(
    number: Optional[int] = None,
    name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List VLANs from Device42.

    Args:
        number: Filter by VLAN number (optional).
        name:   Filter by VLAN name (optional).
        limit:  Records to return (default 100).
        offset: Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if number is not None:
            params["number"] = number
        if name:
            params["name"] = name
        data = c.get("/api/1.0/vlans/", params)
        vlans = data.get("vlans", [])
        return _ok({"total_count": data.get("total_count", len(vlans)), "vlans": vlans})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Data Center — Buildings / Rooms / Racks
# ---------------------------------------------------------------------------


@mcp.tool()
def list_buildings() -> str:
    """List all buildings in Device42."""
    try:
        c = get_client()
        records = c.get_all("/api/1.0/buildings/")
        return _ok({"total": len(records), "buildings": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_rooms(building: Optional[str] = None) -> str:
    """
    List data center rooms.

    Args:
        building: Filter by building name (optional).
    """
    try:
        c = get_client()
        params: dict = {}
        if building:
            params["building"] = building
        records = c.get_all("/api/1.0/rooms/", params)
        return _ok({"total": len(records), "rooms": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_racks(
    room: Optional[str] = None,
    building: Optional[str] = None,
) -> str:
    """
    List racks in Device42.

    Args:
        room:     Filter by room name (optional).
        building: Filter by building name (optional).
    """
    try:
        c = get_client()
        params: dict = {}
        if room:
            params["room"] = room
        if building:
            params["building"] = building
        records = c.get_all("/api/1.0/racks/", params)
        return _ok({"total": len(records), "racks": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_rack(rack_id: int) -> str:
    """
    Get a rack's full layout — all devices mounted with U positions and sizes.

    Args:
        rack_id: Device42 numeric rack ID (from list_racks).
    """
    try:
        c = get_client()
        data = c.get(f"/api/1.0/racks/{rack_id}/")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Hardware & Assets
# ---------------------------------------------------------------------------


@mcp.tool()
def list_hardware_models(
    name: Optional[str] = None,
    manufacturer: Optional[str] = None,
) -> str:
    """
    List hardware models (make/model definitions).

    Args:
        name:         Filter by model name (optional).
        manufacturer: Filter by manufacturer name (optional).
    """
    try:
        c = get_client()
        params: dict = {}
        if name:
            params["name"] = name
        if manufacturer:
            params["manufacturer"] = manufacturer
        records = c.get_all("/api/1.0/hardwares/", params)
        return _ok({"total": len(records), "hardware_models": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_assets(
    name: Optional[str] = None,
    building: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List non-device assets (PDUs, KVMs, patch panels, etc.).

    Args:
        name:     Filter by asset name (optional).
        building: Filter by building (optional).
        limit:    Records to return (default 100).
        offset:   Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if name:
            params["name"] = name
        if building:
            params["building"] = building
        data = c.get("/api/1.0/assets/", params)
        assets = data.get("assets", [])
        return _ok({"total_count": data.get("total_count", len(assets)), "assets": assets})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Network Interfaces
# ---------------------------------------------------------------------------


@mcp.tool()
def list_network_interfaces(
    device: Optional[str] = None,
    mac_address: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List network interfaces (NICs) with MAC addresses.

    Args:
        device:      Filter by device name (optional).
        mac_address: Filter by MAC address (optional).
        limit:       Records to return (default 100).
        offset:      Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if device:
            params["device"] = device
        if mac_address:
            params["macaddress"] = mac_address
        data = c.get("/api/1.0/macs/", params)
        interfaces = data.get("macs", [])
        return _ok({"total_count": data.get("total_count", len(interfaces)), "macs": interfaces})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Services & Application Components
# ---------------------------------------------------------------------------


@mcp.tool()
def list_services(
    device: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List running services discovered on devices.

    Args:
        device: Filter by device name (optional).
        name:   Filter by service name (optional).
        limit:  Records to return (default 100).
        offset: Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if device:
            params["device"] = device
        if name:
            params["name"] = name
        data = c.get("/api/1.0/services/", params)
        services = data.get("services", [])
        return _ok({"total_count": data.get("total_count", len(services)), "services": services})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_appcomps(name: Optional[str] = None) -> str:
    """
    List application components (business application inventory).

    Args:
        name: Filter by application component name (optional).
    """
    try:
        c = get_client()
        params: dict = {}
        if name:
            params["name"] = name
        records = c.get_all("/api/1.0/appcomps/", params)
        return _ok({"total": len(records), "appcomps": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


@mcp.tool()
def list_certificates(
    name: Optional[str] = None,
    device: Optional[str] = None,
) -> str:
    """
    List SSL/TLS certificates tracked in Device42.

    Args:
        name:   Filter by certificate name/CN (optional).
        device: Filter by associated device name (optional).
    """
    try:
        c = get_client()
        params: dict = {}
        if name:
            params["name"] = name
        if device:
            params["device"] = device
        records = c.get_all("/api/1.0/certificates/", params)
        return _ok({"total": len(records), "certificates": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------


@mcp.tool()
def list_dns_records(
    name: Optional[str] = None,
    record_type: Optional[str] = None,
    zone: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List DNS records tracked in Device42.

    Args:
        name:        Filter by record name (optional).
        record_type: Filter by type — 'A', 'CNAME', 'MX', 'PTR', etc. (optional).
        zone:        Filter by DNS zone name (optional).
        limit:       Records to return (default 100).
        offset:      Pagination offset (default 0).
    """
    try:
        c = get_client()
        params: dict = {"limit": limit, "offset": offset}
        if name:
            params["name"] = name
        if record_type:
            params["type"] = record_type
        if zone:
            params["zone"] = zone
        data = c.get("/api/1.0/dns/records/", params)
        records = data.get("dns_records", data.get("records", []))
        return _ok({"total_count": data.get("total_count", len(records)), "dns_records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_dns_zones() -> str:
    """List all DNS zones tracked in Device42."""
    try:
        c = get_client()
        records = c.get_all("/api/1.0/dns/zones/")
        return _ok({"total": len(records), "dns_zones": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Writes (personal login only)
# ---------------------------------------------------------------------------


def _personal_auth() -> Optional[tuple]:
    """The caller's own Device42 (username, password) from this request's headers, or None."""
    user, password = request_credential(USER_HEADER), request_credential(PASSWORD_HEADER)
    return (user, password) if user and password else None


def _log_change(entry: dict) -> None:
    """Append one JSON line to the change log (never contains a password)."""
    try:
        CHANGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CHANGE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        logging.warning("could not write the change log: %s", exc)


def _current_state(device: dict) -> dict:
    return {
        "notes": device.get("notes") or "",
        "virtual_subtype": device.get("virtual_subtype"),
        "in_service": bool(device.get("in_service")),
        "service_level": device.get("service_level"),
        "tags": sorted(device.get("tags") or []),
    }


def _plan_device(item: dict, device: dict) -> dict:
    """Work out the field-by-field changes for one device (no writes)."""
    cur = _current_state(device)
    wanted = dict(item.get("set") or {})
    changes = []
    for field, new in wanted.items():
        if cur.get(field) != new:
            changes.append({"field": field, "old": cur.get(field), "new": new})
    adds, removes = item.get("add_tags") or [], item.get("remove_tags") or []
    new_tags = sorted((set(cur["tags"]) | set(adds)) - set(removes))
    if new_tags != cur["tags"]:
        changes.append({"field": "tags", "old": cur["tags"], "new": new_tags})
    return {"device": device.get("name"), "device_id": device.get("device_id"), "changes": changes}


def _form_data(name: str, changes: list) -> dict:
    data: dict = {"name": name}
    for ch in changes:
        if ch["field"] == "tags":
            data["tags"] = ",".join(ch["new"])
        elif ch["field"] == "in_service":
            data["in_service"] = "yes" if ch["new"] else "no"
        else:
            data[ch["field"]] = ch["new"]
    return data


@mcp.tool()
def update_devices(changes: str, dry_run: bool = True) -> str:
    """
    Change Device42 devices. DRY RUN BY DEFAULT: it only shows the before/after diff and writes nothing.
    A real write (dry_run=false) works only when you are connected with your own Device42 login
    (the 'D42 API' credential on your workstation); otherwise it refuses. Device42 then records the
    change under your account, and your Device42 role still applies. There is no delete.

    Args:
        changes: JSON list of at most 25 items, e.g.
                 [{"name": "admin02", "set": {"in_service": false, "service_level": "Retired"}},
                  {"device_id": 628, "set": {"notes": "SQM-Ignore"}, "add_tags": ["x"], "remove_tags": ["y"]}]
                 Identify each device by exact "name" or numeric "device_id" (use device_id for names the
                 name route cannot match, such as ones with parentheses; if both are given they must agree).
                 "set" may contain only: notes, virtual_subtype, in_service (true/false), service_level.
                 Note: Device42's API currently accepts but ignores virtual_subtype writes (tested 2026-10-22),
                 so the result reports "written but NOT fully applied"; change subtypes in the Device42 UI.
                 Tags are changed with add_tags / remove_tags.
        dry_run: True (default) previews only. Send false to write after you have reviewed the preview.
    """
    try:
        try:
            items = json.loads(changes)
        except ValueError:
            return _err(ValueError("changes must be a JSON list"))
        if not isinstance(items, list) or not items:
            return _err(ValueError("changes must be a non-empty JSON list"))
        if len(items) > MAX_BATCH:
            return _err(ValueError(f"at most {MAX_BATCH} devices per call (got {len(items)})"))
        for item in items:
            if not isinstance(item, dict):
                return _err(ValueError("every item must be an object with a device name or device_id"))
            has_name = isinstance(item.get("name"), str) and item["name"].strip()
            has_id = isinstance(item.get("device_id"), int) and not isinstance(item.get("device_id"), bool)
            if not (has_name or has_id):
                return _err(ValueError("every item needs a device name or a numeric device_id"))
            label = item["name"] if has_name else f"device_id {item['device_id']}"
            extra = set(item) - {"name", "device_id", "set", "add_tags", "remove_tags"}
            if extra:
                return _err(ValueError(f"{label}: unknown keys {sorted(extra)}"))
            bad = set(item.get("set") or {}) - WRITE_FIELDS
            if bad:
                return _err(ValueError(f"{label}: fields not allowed {sorted(bad)}; allowed: {sorted(WRITE_FIELDS)}"))
            sets = item.get("set") or {}
            if "in_service" in sets and not isinstance(sets["in_service"], bool):
                return _err(ValueError(f"{label}: in_service must be true or false"))
            for f in ("notes", "virtual_subtype", "service_level"):
                if f in sets and not isinstance(sets[f], str):
                    return _err(ValueError(f"{label}: {f} must be text"))
            if not (sets or item.get("add_tags") or item.get("remove_tags")):
                return _err(ValueError(f"{label}: nothing to change"))

        auth = _personal_auth()
        if not dry_run and auth is None:
            return json.dumps({"error": "Writes need your own Device42 login. Store it as 'D42 API' in your Credential Manager "
                                        "(Get-McpHeaders.ps1 sends it) and reconnect, or run with dry_run=true to preview only.",
                               "code": "personal-login-required"})
        c = get_client()
        plans, written = [], 0
        for item in items:
            # A device_id lookup also works for names the name route cannot match, e.g. ones with parentheses
            if isinstance(item.get("device_id"), int):
                name = f"device_id {item['device_id']}"
                read_path = f"/api/1.0/devices/id/{item['device_id']}/"
            else:
                name = item["name"].strip()
                read_path = f"/api/1.0/devices/name/{name}/"
            try:
                device = c.get(read_path, auth=auth)
            except Exception as exc:
                plans.append({"device": name, "error": f"could not read the device: {exc}"})
                continue
            if item.get("name") and device.get("name", "").lower() != item["name"].strip().lower():
                plans.append({"device": name, "error": f"device_id {device.get('device_id')} is named '{device.get('name')}', "
                                                       f"not '{item['name'].strip()}'; nothing changed"})
                continue
            plan = _plan_device(item, device)
            if not plan["changes"]:
                plan["status"] = "no change needed"
                plans.append(plan)
                continue
            if dry_run:
                plan["status"] = "would change"
                plans.append(plan)
                continue
            try:
                result = c.post_form("/api/1.0/device/", _form_data(device.get("name") or name, plan["changes"]), auth)
                code = result.get("code") if isinstance(result, dict) else None
                if code not in (0, "0", None):
                    plan["status"] = f"Device42 rejected the change: {result.get('msg')}"
                else:
                    after = _plan_device(item, c.get(f"/api/1.0/devices/id/{device.get('device_id')}/", auth=auth))
                    plan["status"] = "written and verified" if not after["changes"] else "written but NOT fully applied"
                    if after["changes"]:
                        plan["still_different"] = after["changes"]
                        if any(ch["field"] == "virtual_subtype" for ch in after["changes"]):
                            plan["hint"] = ("Device42's API accepted the write but left virtual_subtype unchanged "
                                            "(tested 2026-10-22); change it in the Device42 UI.")
                    written += 1
            except Exception as exc:
                plan["status"] = f"write failed: {exc}"
            _log_change({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "d42_user": auth[0],
                         "device": plan["device"], "changes": plan["changes"], "status": plan["status"]})
            plans.append(plan)
        return _ok({"dry_run": dry_run, "wrote": written, "using": "personal login" if auth else "shared read-only account",
                    "devices": plans,
                    "next": "Nothing was written. Review the diff, then send the same list with dry_run=false."
                    if dry_run else "Check each status; 'written and verified' means Device42 now shows the new value."})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


@mcp.tool()
def api_call(
    path: str,
    query_params: Optional[Union[str, dict]] = None,
) -> str:
    """
    Call any Device42 REST API GET endpoint not covered by a dedicated tool.

    Args:
        path:         API path (e.g. '/api/1.0/pdus/'). A query string in the path is also accepted.
        query_params: Query parameters as a JSON object or JSON object string
                      (e.g. {"limit": 50, "offset": 0}).
    """
    try:
        c = get_client()
        params: dict = {}
        if isinstance(query_params, dict):
            params = query_params
        elif query_params:
            params = json.loads(query_params)
        data = c.get(path, params)
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp, credential_headers=(USER_HEADER, PASSWORD_HEADER))
