# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
"""
XenServer MCP Server

Exposes XenServer Management API operations as MCP tools.

Configuration via environment variables:
  XENSERVER_HOST       - XenServer hostname or IP (required)
  XENSERVER_USERNAME   - Username (default: root)
  XENSERVER_PASSWORD   - Password (required)
  XENSERVER_VERIFY_SSL - Verify TLS certificate: true/false (default: false)
  XENSERVER_TIMEOUT    - Request timeout in seconds (default: 60)
"""

import json
import logging
import os
import sys
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import XenServerClient, XenServerError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("XenServer")

_client: Optional[XenServerClient] = None


def get_client() -> XenServerClient:
    global _client
    if _client is None:
        host = os.environ.get("XENSERVER_HOST", "").strip()
        username = os.environ.get("XENSERVER_USERNAME", "root").strip()
        password = os.environ.get("XENSERVER_PASSWORD", "").strip()
        verify_ssl = os.environ.get("XENSERVER_VERIFY_SSL", "false").lower() == "true"
        timeout = float(os.environ.get("XENSERVER_TIMEOUT", "60"))

        if not host:
            raise RuntimeError("XENSERVER_HOST environment variable is required")
        if not password:
            raise RuntimeError("XENSERVER_PASSWORD environment variable is required")

        _client = XenServerClient(host, username, password, verify_ssl, timeout)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, XenServerError):
        return json.dumps({"error": exc.error_description})
    return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Session / Connection
# ---------------------------------------------------------------------------


@mcp.tool()
def connect(
    host: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> str:
    """
    Connect to a XenServer host.  If arguments are omitted the values from
    XENSERVER_HOST / XENSERVER_USERNAME / XENSERVER_PASSWORD env vars are used.
    Returns the session reference on success.
    """
    global _client
    try:
        if host:
            _client = XenServerClient(
                host,
                username or "root",
                password or "",
                verify_ssl,
            )
        session = get_client().connect()
        return _ok({"status": "connected", "session_ref": session, "host": get_client().host})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def disconnect() -> str:
    """Logout and close the current XenServer session."""
    global _client
    try:
        if _client:
            _client.disconnect()
        return _ok({"status": "disconnected"})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Raw API call (escape hatch for any operation not wrapped below)
# ---------------------------------------------------------------------------


@mcp.tool()
def api_call(method: str, params: list[Any]) -> str:
    """
    Make a raw XenServer API call.
    The session reference is prepended automatically.

    Examples:
      method="VM.get_all_records", params=[]
      method="VM.start",           params=["OpaqueRef:...", false, false]
      method="host.reboot",        params=["OpaqueRef:..."]
    """
    try:
        result = get_client().call(method, *params)
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# VM Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def vm_list(include_templates: bool = False, include_control_domains: bool = False) -> str:
    """
    List all VMs with key fields: uuid, name_label, power_state, memory.

    Args:
        include_templates: Include VM templates (default false).
        include_control_domains: Include dom0 control domains (default false).
    """
    try:
        c = get_client()
        records = c.call("VM.get_all_records")
        vms = []
        for ref, rec in records.items():
            if not include_templates and rec.get("is_a_template"):
                continue
            if not include_control_domains and rec.get("is_control_domain"):
                continue
            vms.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "name_description": rec.get("name_description"),
                "power_state": rec.get("power_state"),
                "memory_static_max": rec.get("memory_static_max"),
                "memory_dynamic_max": rec.get("memory_dynamic_max"),
                "VCPUs_max": rec.get("VCPUs_max"),
                "resident_on": rec.get("resident_on"),
                "is_a_template": rec.get("is_a_template"),
                "is_control_domain": rec.get("is_control_domain"),
            })
        vms.sort(key=lambda v: v["name_label"] or "")
        return _ok(vms)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_get(vm: str) -> str:
    """
    Get full details for a VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        rec = c.call("VM.get_record", ref)
        rec["ref"] = ref
        return _ok(rec)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_start(vm: str, start_paused: bool = False, force: bool = False) -> str:
    """
    Start a VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        start_paused: Start in paused state (default false).
        force: Boot even if host is disabled (default false).
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.start", ref, start_paused, force)
        return _ok({"status": "started", "vm": vm})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_shutdown(vm: str, force: bool = False) -> str:
    """
    Shut down a VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        force: Hard shutdown (power off immediately) instead of clean shutdown.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        method = "VM.hard_shutdown" if force else "VM.clean_shutdown"
        c.call(method, ref)
        return _ok({"status": "shut_down", "vm": vm, "forced": force})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_reboot(vm: str, force: bool = False) -> str:
    """
    Reboot a VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        force: Hard reboot instead of clean reboot.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        method = "VM.hard_reboot" if force else "VM.clean_reboot"
        c.call(method, ref)
        return _ok({"status": "rebooted", "vm": vm, "forced": force})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_suspend(vm: str) -> str:
    """
    Suspend a running VM to disk.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.suspend", ref)
        return _ok({"status": "suspended", "vm": vm})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_resume(vm: str, start_paused: bool = False, force: bool = False) -> str:
    """
    Resume a suspended VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        start_paused: Resume into paused state.
        force: Force resume even on non-optimal host.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.resume", ref, start_paused, force)
        return _ok({"status": "resumed", "vm": vm})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_pause(vm: str) -> str:
    """
    Pause a running VM (keeps it in memory).

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.pause", ref)
        return _ok({"status": "paused", "vm": vm})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_unpause(vm: str) -> str:
    """
    Unpause a paused VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.unpause", ref)
        return _ok({"status": "unpaused", "vm": vm})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_clone(vm: str, new_name: str) -> str:
    """
    Clone a VM (exploits storage COW where available, fast).

    Args:
        vm: Source VM name label, UUID, or OpaqueRef.
        new_name: Name for the new VM.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        new_ref = c.call("VM.clone", ref, new_name)
        return _ok({"status": "cloned", "new_vm_ref": new_ref, "new_name": new_name})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_copy(vm: str, new_name: str, sr: Optional[str] = None) -> str:
    """
    Copy a VM (full disk copy, independent of source).

    Args:
        vm: Source VM name label, UUID, or OpaqueRef.
        new_name: Name for the new VM.
        sr: Target SR name label, UUID, or OpaqueRef (optional; uses same SR if omitted).
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        sr_ref = c.resolve_sr(sr) if sr else "OpaqueRef:NULL"
        new_ref = c.call("VM.copy", ref, new_name, sr_ref)
        return _ok({"status": "copied", "new_vm_ref": new_ref, "new_name": new_name})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_snapshot(vm: str, snapshot_name: str) -> str:
    """
    Take a snapshot of a VM (disk only, no memory).

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        snapshot_name: Name for the snapshot.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        snap_ref = c.call("VM.snapshot", ref, snapshot_name)
        return _ok({"status": "snapshot_created", "snapshot_ref": snap_ref, "snapshot_name": snapshot_name})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_checkpoint(vm: str, checkpoint_name: str) -> str:
    """
    Checkpoint a VM (snapshot with memory image).

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        checkpoint_name: Name for the checkpoint.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        snap_ref = c.call("VM.checkpoint", ref, checkpoint_name)
        return _ok({"status": "checkpoint_created", "checkpoint_ref": snap_ref})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_revert(snapshot: str) -> str:
    """
    Revert a VM to a snapshot.

    Args:
        snapshot: Snapshot VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(snapshot)
        c.call("VM.revert", ref)
        return _ok({"status": "reverted", "snapshot": snapshot})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_migrate(
    vm: str,
    host: str,
    live: bool = True,
    options: Optional[dict] = None,
) -> str:
    """
    Migrate a VM to another host in the same pool.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        host: Target host name label, UUID, or OpaqueRef.
        live: Live migration (default true).
        options: Additional migration options dict (optional).
    """
    try:
        c = get_client()
        vm_ref = c.resolve_vm(vm)
        host_ref = c.resolve_host(host)
        c.call("VM.pool_migrate", vm_ref, host_ref, options or {})
        return _ok({"status": "migrated", "vm": vm, "target_host": host})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_set_memory(
    vm: str,
    static_min: Optional[int] = None,
    static_max: Optional[int] = None,
    dynamic_min: Optional[int] = None,
    dynamic_max: Optional[int] = None,
) -> str:
    """
    Set VM memory limits (in bytes).

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        static_min: Minimum static memory in bytes.
        static_max: Maximum static memory in bytes.
        dynamic_min: Minimum dynamic memory in bytes.
        dynamic_max: Maximum dynamic memory in bytes.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        if static_min is not None:
            c.call("VM.set_memory_static_min", ref, static_min)
        if static_max is not None:
            c.call("VM.set_memory_static_max", ref, static_max)
        if dynamic_min is not None:
            c.call("VM.set_memory_dynamic_min", ref, dynamic_min)
        if dynamic_max is not None:
            c.call("VM.set_memory_dynamic_max", ref, dynamic_max)
        return _ok({"status": "memory_updated", "vm": vm})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_set_vcpus(vm: str, vcpus_max: int, vcpus_at_startup: Optional[int] = None) -> str:
    """
    Set the number of vCPUs for a VM (VM must be halted).

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        vcpus_max: Maximum number of vCPUs.
        vcpus_at_startup: Number of vCPUs at startup (defaults to vcpus_max).
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.set_VCPUs_max", ref, vcpus_max)
        c.call("VM.set_VCPUs_at_startup", ref, vcpus_at_startup or vcpus_max)
        return _ok({"status": "vcpus_updated", "vm": vm, "vcpus_max": vcpus_max})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_set_name(vm: str, name_label: str, name_description: Optional[str] = None) -> str:
    """
    Rename a VM and optionally update its description.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
        name_label: New name label.
        name_description: New description (optional).
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.set_name_label", ref, name_label)
        if name_description is not None:
            c.call("VM.set_name_description", ref, name_description)
        return _ok({"status": "renamed", "new_name": name_label})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_destroy(vm: str) -> str:
    """
    Permanently destroy a VM and remove its record.
    The VM must be halted first. Disk images (VDIs) are NOT automatically deleted.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.destroy", ref)
        return _ok({"status": "destroyed", "vm": vm})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_get_possible_hosts(vm: str) -> str:
    """
    List hosts that a VM could run on.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        host_refs = c.call("VM.get_possible_hosts", ref)
        hosts = []
        for hr in host_refs:
            rec = c.call("host.get_record", hr)
            hosts.append({"ref": hr, "uuid": rec.get("uuid"), "name_label": rec.get("name_label"), "address": rec.get("address")})
        return _ok(hosts)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_provision(vm: str) -> str:
    """
    Provision a VM from its template (creates disks described by disk_on_boot config).

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        c.call("VM.provision", ref)
        return _ok({"status": "provisioned", "vm": vm})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Host Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def host_list() -> str:
    """List all hosts in the pool with key fields."""
    try:
        c = get_client()
        records = c.call("host.get_all_records")
        hosts = []
        for ref, rec in records.items():
            hosts.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "address": rec.get("address"),
                "hostname": rec.get("hostname"),
                "enabled": rec.get("enabled"),
                "api_version_major": rec.get("api_version_major"),
                "api_version_minor": rec.get("api_version_minor"),
                "software_version": rec.get("software_version", {}).get("product_version"),
                "memory_overhead": rec.get("memory_overhead"),
                "cpu_info": {
                    "cpu_count": rec.get("cpu_info", {}).get("cpu_count"),
                    "modelname": rec.get("cpu_info", {}).get("modelname"),
                },
            })
        hosts.sort(key=lambda h: h["name_label"] or "")
        return _ok(hosts)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_get(host: str) -> str:
    """
    Get full details for a host.

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        rec = c.call("host.get_record", ref)
        rec["ref"] = ref
        return _ok(rec)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_enable(host: str) -> str:
    """
    Enable a host so it can accept new VMs.

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        c.call("host.enable", ref)
        return _ok({"status": "enabled", "host": host})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_disable(host: str) -> str:
    """
    Disable a host (prevents new VMs from starting on it).

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        c.call("host.disable", ref)
        return _ok({"status": "disabled", "host": host})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_evacuate(host: str) -> str:
    """
    Migrate all running VMs off a host (host must be disabled first).

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        c.call("host.evacuate", ref)
        return _ok({"status": "evacuated", "host": host})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_reboot(host: str) -> str:
    """
    Reboot a host.  Host should be disabled and evacuated first.

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        c.call("host.reboot", ref)
        return _ok({"status": "reboot_requested", "host": host})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_shutdown(host: str) -> str:
    """
    Shut down a host.  Host should be disabled and evacuated first.

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        c.call("host.shutdown", ref)
        return _ok({"status": "shutdown_requested", "host": host})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_get_resident_vms(host: str) -> str:
    """
    List VMs currently running on a specific host.

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        vm_refs = c.call("host.get_resident_VMs", ref)
        vms = []
        for vr in vm_refs:
            rec = c.call("VM.get_record", vr)
            if rec.get("is_control_domain"):
                continue
            vms.append({
                "ref": vr,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "power_state": rec.get("power_state"),
            })
        return _ok(vms)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_get_free_memory(host: str) -> str:
    """
    Get the amount of free memory on a host in bytes.

    Args:
        host: Host name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        free = c.call("host.compute_free_memory", ref)
        return _ok({"host": host, "free_memory_bytes": free, "free_memory_gb": round(int(free) / 1073741824, 2)})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def host_call_plugin(host: str, plugin: str, fn: str, args: Optional[dict] = None) -> str:
    """
    Call a plugin on a host.

    Args:
        host: Host name label, UUID, or OpaqueRef.
        plugin: Plugin name (e.g. 'set-hostname').
        fn: Function to call within the plugin.
        args: Key-value arguments for the plugin function.
    """
    try:
        c = get_client()
        ref = c.resolve_host(host)
        result = c.call("host.call_plugin", ref, plugin, fn, args or {})
        return _ok({"result": result})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Pool Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def pool_get() -> str:
    """Get the pool record (there is always exactly one pool)."""
    try:
        c = get_client()
        refs = c.call("pool.get_all")
        if not refs:
            return _err(Exception("No pool found"))
        rec = c.call("pool.get_record", refs[0])
        rec["ref"] = refs[0]
        return _ok(rec)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def pool_get_license_state() -> str:
    """Get the pool license state."""
    try:
        c = get_client()
        refs = c.call("pool.get_all")
        state = c.call("pool.get_license_state", refs[0])
        return _ok(state)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# SR (Storage Repository) Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def sr_list() -> str:
    """List all Storage Repositories with key fields."""
    try:
        c = get_client()
        records = c.call("SR.get_all_records")
        srs = []
        for ref, rec in records.items():
            phys = int(rec.get("physical_utilisation", 0))
            total = int(rec.get("physical_size", 0))
            srs.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "name_description": rec.get("name_description"),
                "type": rec.get("type"),
                "content_type": rec.get("content_type"),
                "shared": rec.get("shared"),
                "physical_size_bytes": total,
                "physical_size_gb": round(total / 1073741824, 2),
                "physical_utilisation_bytes": phys,
                "physical_utilisation_gb": round(phys / 1073741824, 2),
                "virtual_allocation": rec.get("virtual_allocation"),
                "is_tools_sr": rec.get("is_tools_sr"),
            })
        srs.sort(key=lambda s: s["name_label"] or "")
        return _ok(srs)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sr_get(sr: str) -> str:
    """
    Get full details for a Storage Repository.

    Args:
        sr: SR name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_sr(sr)
        rec = c.call("SR.get_record", ref)
        rec["ref"] = ref
        return _ok(rec)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sr_scan(sr: str) -> str:
    """
    Refresh the SR's VDI list from the storage backend.

    Args:
        sr: SR name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_sr(sr)
        c.call("SR.scan", ref)
        return _ok({"status": "scanned", "sr": sr})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sr_get_vdis(sr: str) -> str:
    """
    List all VDIs within a Storage Repository.

    Args:
        sr: SR name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_sr(sr)
        vdi_refs = c.call("SR.get_VDIs", ref)
        vdis = []
        for vr in vdi_refs:
            rec = c.call("VDI.get_record", vr)
            vsize = int(rec.get("virtual_size", 0))
            phys = int(rec.get("physical_utilisation", 0))
            vdis.append({
                "ref": vr,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "type": rec.get("type"),
                "virtual_size_bytes": vsize,
                "virtual_size_gb": round(vsize / 1073741824, 2),
                "physical_utilisation_bytes": phys,
                "physical_utilisation_gb": round(phys / 1073741824, 2),
                "read_only": rec.get("read_only"),
                "is_a_snapshot": rec.get("is_a_snapshot"),
            })
        vdis.sort(key=lambda v: v["name_label"] or "")
        return _ok(vdis)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sr_set_name(sr: str, name_label: str, name_description: Optional[str] = None) -> str:
    """
    Rename a Storage Repository.

    Args:
        sr: SR name label, UUID, or OpaqueRef.
        name_label: New name label.
        name_description: New description (optional).
    """
    try:
        c = get_client()
        ref = c.resolve_sr(sr)
        c.call("SR.set_name_label", ref, name_label)
        if name_description is not None:
            c.call("SR.set_name_description", ref, name_description)
        return _ok({"status": "renamed", "new_name": name_label})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sr_get_supported_types() -> str:
    """List all SR types supported by the pool."""
    try:
        c = get_client()
        types = c.call("SR.get_supported_types")
        return _ok(types)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Network Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def network_list() -> str:
    """List all networks in the pool."""
    try:
        c = get_client()
        records = c.call("network.get_all_records")
        networks = []
        for ref, rec in records.items():
            networks.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "name_description": rec.get("name_description"),
                "bridge": rec.get("bridge"),
                "MTU": rec.get("MTU"),
                "managed": rec.get("managed"),
                "default_locking_mode": rec.get("default_locking_mode"),
                "purpose": rec.get("purpose"),
                "VIF_count": len(rec.get("VIFs", [])),
                "PIF_count": len(rec.get("PIFs", [])),
            })
        networks.sort(key=lambda n: n["name_label"] or "")
        return _ok(networks)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def network_get(network: str) -> str:
    """
    Get full details for a network.

    Args:
        network: Network name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_network(network)
        rec = c.call("network.get_record", ref)
        rec["ref"] = ref
        return _ok(rec)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def network_create(
    name_label: str,
    name_description: str = "",
    mtu: int = 1500,
) -> str:
    """
    Create a new internal network (no physical interface).

    Args:
        name_label: Name for the new network.
        name_description: Description.
        mtu: MTU size (default 1500).
    """
    try:
        c = get_client()
        net_record = {
            "name_label": name_label,
            "name_description": name_description,
            "MTU": mtu,
            "other_config": {},
        }
        ref = c.call("network.create", net_record)
        return _ok({"status": "created", "network_ref": ref, "name_label": name_label})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def network_destroy(network: str) -> str:
    """
    Destroy a network.

    Args:
        network: Network name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_network(network)
        c.call("network.destroy", ref)
        return _ok({"status": "destroyed", "network": network})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# VDI Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def vdi_list(sr: Optional[str] = None) -> str:
    """
    List VDIs, optionally filtered by SR.

    Args:
        sr: SR name label, UUID, or OpaqueRef to filter by (optional).
    """
    try:
        c = get_client()
        if sr:
            sr_ref = c.resolve_sr(sr)
            vdi_refs = c.call("SR.get_VDIs", sr_ref)
            records = {vr: c.call("VDI.get_record", vr) for vr in vdi_refs}
        else:
            records = c.call("VDI.get_all_records")

        vdis = []
        for ref, rec in records.items():
            vsize = int(rec.get("virtual_size", 0))
            phys = int(rec.get("physical_utilisation", 0))
            vdis.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "type": rec.get("type"),
                "sr": rec.get("SR"),
                "virtual_size_bytes": vsize,
                "virtual_size_gb": round(vsize / 1073741824, 2),
                "physical_utilisation_bytes": phys,
                "physical_utilisation_gb": round(phys / 1073741824, 2),
                "read_only": rec.get("read_only"),
                "is_a_snapshot": rec.get("is_a_snapshot"),
                "managed": rec.get("managed"),
            })
        vdis.sort(key=lambda v: v["name_label"] or "")
        return _ok(vdis)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vdi_get(vdi: str) -> str:
    """
    Get full details for a VDI.

    Args:
        vdi: VDI name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vdi(vdi)
        rec = c.call("VDI.get_record", ref)
        rec["ref"] = ref
        return _ok(rec)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vdi_snapshot(vdi: str) -> str:
    """
    Take a read-only snapshot of a VDI.

    Args:
        vdi: VDI name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vdi(vdi)
        snap_ref = c.call("VDI.snapshot", ref, {})
        return _ok({"status": "snapshot_created", "snapshot_ref": snap_ref})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vdi_clone(vdi: str) -> str:
    """
    Clone a VDI (writable copy).

    Args:
        vdi: VDI name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vdi(vdi)
        new_ref = c.call("VDI.clone", ref, {})
        return _ok({"status": "cloned", "new_vdi_ref": new_ref})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vdi_resize(vdi: str, new_size_gb: float) -> str:
    """
    Resize a VDI.

    Args:
        vdi: VDI name label, UUID, or OpaqueRef.
        new_size_gb: New size in gigabytes.
    """
    try:
        c = get_client()
        ref = c.resolve_vdi(vdi)
        size_bytes = int(new_size_gb * 1073741824)
        c.call("VDI.resize", ref, size_bytes)
        return _ok({"status": "resized", "vdi": vdi, "new_size_gb": new_size_gb})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vdi_destroy(vdi: str) -> str:
    """
    Destroy a VDI (permanently deletes data).

    Args:
        vdi: VDI name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vdi(vdi)
        c.call("VDI.destroy", ref)
        return _ok({"status": "destroyed", "vdi": vdi})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vdi_copy(vdi: str, sr: str) -> str:
    """
    Copy a VDI to a different SR.

    Args:
        vdi: VDI name label, UUID, or OpaqueRef.
        sr: Destination SR name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        vdi_ref = c.resolve_vdi(vdi)
        sr_ref = c.resolve_sr(sr)
        new_ref = c.call("VDI.copy", vdi_ref, sr_ref, "OpaqueRef:NULL", "OpaqueRef:NULL")
        return _ok({"status": "copied", "new_vdi_ref": new_ref})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vdi_set_name(vdi: str, name_label: str, name_description: Optional[str] = None) -> str:
    """
    Rename a VDI.

    Args:
        vdi: VDI name label, UUID, or OpaqueRef.
        name_label: New name label.
        name_description: New description (optional).
    """
    try:
        c = get_client()
        ref = c.resolve_vdi(vdi)
        c.call("VDI.set_name_label", ref, name_label)
        if name_description is not None:
            c.call("VDI.set_name_description", ref, name_description)
        return _ok({"status": "renamed", "new_name": name_label})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Task Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def task_list(include_completed: bool = False) -> str:
    """
    List tasks.

    Args:
        include_completed: Include completed/failed tasks (default false).
    """
    try:
        c = get_client()
        records = c.call("task.get_all_records")
        tasks = []
        for ref, rec in records.items():
            status = rec.get("status")
            if not include_completed and status not in ("pending", "cancelling"):
                continue
            tasks.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "name_label": rec.get("name_label"),
                "name_description": rec.get("name_description"),
                "status": status,
                "progress": rec.get("progress"),
                "created": rec.get("created"),
                "finished": rec.get("finished"),
                "error_info": rec.get("error_info"),
                "result": rec.get("result"),
            })
        tasks.sort(key=lambda t: str(t.get("created") or ""))
        return _ok(tasks)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def task_get(task: str) -> str:
    """
    Get the current status and result of a task.

    Args:
        task: Task UUID or OpaqueRef.
    """
    try:
        c = get_client()
        if task.startswith("OpaqueRef:"):
            ref = task
        else:
            ref = c.call("task.get_by_uuid", task)
        rec = c.call("task.get_record", ref)
        rec["ref"] = ref
        return _ok(rec)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def task_cancel(task: str) -> str:
    """
    Request cancellation of a task.

    Args:
        task: Task UUID or OpaqueRef.
    """
    try:
        c = get_client()
        if task.startswith("OpaqueRef:"):
            ref = task
        else:
            ref = c.call("task.get_by_uuid", task)
        c.call("task.cancel", ref)
        return _ok({"status": "cancel_requested", "task": task})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# VBD Tools (Virtual Block Device — connects VM to VDI)
# ---------------------------------------------------------------------------


@mcp.tool()
def vm_get_vbds(vm: str) -> str:
    """
    List VBDs (disk attachments) for a VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        vbd_refs = c.call("VM.get_VBDs", ref)
        vbds = []
        for vr in vbd_refs:
            rec = c.call("VBD.get_record", vr)
            vdis = []
            vdi_ref = rec.get("VDI")
            if vdi_ref and not vdi_ref.startswith("OpaqueRef:NULL"):
                vdi_rec = c.call("VDI.get_record", vdi_ref)
                vsize = int(vdi_rec.get("virtual_size", 0))
                vdis = {
                    "ref": vdi_ref,
                    "uuid": vdi_rec.get("uuid"),
                    "name_label": vdi_rec.get("name_label"),
                    "virtual_size_gb": round(vsize / 1073741824, 2),
                }
            vbds.append({
                "ref": vr,
                "uuid": rec.get("uuid"),
                "device": rec.get("device"),
                "userdevice": rec.get("userdevice"),
                "type": rec.get("type"),
                "mode": rec.get("mode"),
                "currently_attached": rec.get("currently_attached"),
                "bootable": rec.get("bootable"),
                "VDI": vdis,
            })
        vbds.sort(key=lambda v: str(v.get("userdevice") or ""))
        return _ok(vbds)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def vm_get_vifs(vm: str) -> str:
    """
    List VIFs (network interfaces) for a VM.

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        vif_refs = c.call("VM.get_VIFs", ref)
        vifs = []
        for vr in vif_refs:
            rec = c.call("VIF.get_record", vr)
            net_ref = rec.get("network", "")
            net_name = ""
            if net_ref and not net_ref.startswith("OpaqueRef:NULL"):
                net_name = c.call("network.get_name_label", net_ref)
            vifs.append({
                "ref": vr,
                "uuid": rec.get("uuid"),
                "device": rec.get("device"),
                "MAC": rec.get("MAC"),
                "MTU": rec.get("MTU"),
                "network_ref": net_ref,
                "network_name": net_name,
                "currently_attached": rec.get("currently_attached"),
                "ip_configuration_mode": rec.get("ip_configuration_mode"),
                "IPv4_allowed": rec.get("IPv4_allowed"),
            })
        vifs.sort(key=lambda v: str(v.get("device") or ""))
        return _ok(vifs)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# PIF Tools (Physical Interface)
# ---------------------------------------------------------------------------


@mcp.tool()
def pif_list(host: Optional[str] = None) -> str:
    """
    List Physical Interfaces, optionally filtered by host.

    Args:
        host: Host name label, UUID, or OpaqueRef to filter by (optional).
    """
    try:
        c = get_client()
        records = c.call("PIF.get_all_records")
        pifs = []
        host_ref = c.resolve_host(host) if host else None
        for ref, rec in records.items():
            if host_ref and rec.get("host") != host_ref:
                continue
            pifs.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "device": rec.get("device"),
                "host": rec.get("host"),
                "network": rec.get("network"),
                "MAC": rec.get("MAC"),
                "MTU": rec.get("MTU"),
                "VLAN": rec.get("VLAN"),
                "currently_attached": rec.get("currently_attached"),
                "ip_configuration_mode": rec.get("ip_configuration_mode"),
                "IP": rec.get("IP"),
                "netmask": rec.get("netmask"),
                "gateway": rec.get("gateway"),
                "DNS": rec.get("DNS"),
                "physical": rec.get("physical"),
            })
        pifs.sort(key=lambda p: str(p.get("device") or ""))
        return _ok(pifs)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Message / Alert Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def message_list(since_seconds: int = 3600) -> str:
    """
    List recent system messages/alerts.

    Args:
        since_seconds: Return messages from the last N seconds (default 3600 = 1 hour).
    """
    try:
        import time as _time
        c = get_client()
        # XenServer message.get_all_records returns all messages
        records = c.call("message.get_all_records")
        now = _time.time()
        msgs = []
        for ref, rec in records.items():
            # created is a datetime string; filter by comparing if possible
            msgs.append({
                "ref": ref,
                "uuid": rec.get("uuid"),
                "name": rec.get("name"),
                "priority": rec.get("priority"),
                "cls": rec.get("cls"),
                "obj_uuid": rec.get("obj_uuid"),
                "body": rec.get("body"),
                "timestamp": rec.get("timestamp"),
            })
        # Sort newest first
        msgs.sort(key=lambda m: str(m.get("timestamp") or ""), reverse=True)
        return _ok(msgs[:200])  # cap at 200
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Console / VNC
# ---------------------------------------------------------------------------


@mcp.tool()
def vm_get_console(vm: str) -> str:
    """
    Get console connection details for a VM (VNC/RFB location URL).

    Args:
        vm: VM name label, UUID, or OpaqueRef.
    """
    try:
        c = get_client()
        ref = c.resolve_vm(vm)
        console_refs = c.call("VM.get_consoles", ref)
        consoles = []
        for cr in console_refs:
            rec = c.call("console.get_record", cr)
            consoles.append({
                "ref": cr,
                "uuid": rec.get("uuid"),
                "protocol": rec.get("protocol"),
                "location": rec.get("location"),
            })
        return _ok(consoles)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
