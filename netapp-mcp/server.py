"""
NetApp ONTAP MCP Server

Exposes NetApp ONTAP REST API operations as MCP tools.

Configuration via environment variables:
  ONTAP_HOST       - ONTAP cluster management IP or hostname (required)
  ONTAP_USERNAME   - Admin/read-only username (required)
  ONTAP_PASSWORD   - Password (required)
  ONTAP_VERIFY_SSL - Verify TLS certificate: true/false (default: false)
  ONTAP_TIMEOUT    - Request timeout in seconds (default: 30)
"""

import json
import logging
import os
import sys
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import OntapClient, OntapError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("NetApp-ONTAP")

_client: Optional[OntapClient] = None


def get_client() -> OntapClient:
    global _client
    if _client is None:
        host = os.environ.get("ONTAP_HOST", "").strip()
        username = os.environ.get("ONTAP_USERNAME", "").strip()
        password = os.environ.get("ONTAP_PASSWORD", "").strip()
        verify_ssl = os.environ.get("ONTAP_VERIFY_SSL", "false").lower() == "true"
        timeout = float(os.environ.get("ONTAP_TIMEOUT", "30"))
        if not host:
            raise RuntimeError("ONTAP_HOST environment variable is required")
        if not username or not password:
            raise RuntimeError("ONTAP_USERNAME and ONTAP_PASSWORD are required")
        _client = OntapClient(host, username, password, verify_ssl, timeout)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, OntapError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Cluster & System
# ---------------------------------------------------------------------------


@mcp.tool()
def cluster_get() -> str:
    """
    Return cluster-level information: name, UUID, ONTAP version, location,
    contact, DNS domains, NTP servers, and management interfaces.
    """
    try:
        c = get_client()
        fields = "name,uuid,version,location,contact,dns_domains,ntp_servers,management_interfaces"
        data = c.get("/cluster", {"fields": fields})
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def software_get() -> str:
    """
    Return ONTAP software version, status, and any pending update information.
    """
    try:
        c = get_client()
        data = c.get("/cluster/software", {"fields": "*"})
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def node_list() -> str:
    """
    List all nodes in the cluster with name, serial number, model, uptime,
    ONTAP version, system state, and storage configuration.
    """
    try:
        c = get_client()
        fields = (
            "name,uuid,serial_number,model,uptime,version,state,"
            "is_all_flash_optimized,nvram,controller,storage_configuration"
        )
        records = c.get_all("/cluster/nodes", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def node_get(node: str) -> str:
    """
    Get detailed information about a single node by name or UUID.

    Args:
        node: Node name (e.g. 'cluster01-01') or UUID.
    """
    try:
        c = get_client()
        records = c.get_all("/cluster/nodes", {"name": node, "fields": "*"})
        if not records:
            return _ok({"error": f"Node not found: {node}"})
        return _ok(records[0])
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Storage — Aggregates (Local Tiers)
# ---------------------------------------------------------------------------


@mcp.tool()
def aggregate_list() -> str:
    """
    List all aggregates (local tiers) with name, node, state, disk count,
    and capacity metrics (size, used, available).
    """
    try:
        c = get_client()
        fields = "name,uuid,node,state,snaplock_type,block_storage,space,disk_count"
        records = c.get_all("/storage/aggregates", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def aggregate_get(aggregate: str) -> str:
    """
    Get detailed information about a single aggregate by name or UUID,
    including capacity breakdown, RAID configuration, and disk details.

    Args:
        aggregate: Aggregate name or UUID.
    """
    try:
        c = get_client()
        records = c.get_all("/storage/aggregates", {"name": aggregate, "fields": "*"})
        if not records:
            return _ok({"error": f"Aggregate not found: {aggregate}"})
        return _ok(records[0])
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Storage — Volumes
# ---------------------------------------------------------------------------


@mcp.tool()
def volume_list(svm: Optional[str] = None, state: Optional[str] = None) -> str:
    """
    List volumes with name, SVM, aggregate, type, state, and space usage.

    Args:
        svm:   Filter by SVM name (optional).
        state: Filter by state — 'online', 'offline', 'restricted' (optional).
    """
    try:
        c = get_client()
        fields = (
            "name,uuid,svm,aggregates,type,state,style,"
            "space,nas,guarantee,snapshot_policy,tiering"
        )
        params: dict = {"fields": fields}
        if svm:
            params["svm.name"] = svm
        if state:
            params["state"] = state
        records = c.get_all("/storage/volumes", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def volume_get(volume: str, svm: Optional[str] = None) -> str:
    """
    Get detailed information about a single volume by name or UUID.

    Args:
        volume: Volume name or UUID.
        svm:    SVM name (required when looking up by volume name to avoid ambiguity).
    """
    try:
        c = get_client()
        params: dict = {"fields": "*"}
        if svm:
            params["svm.name"] = svm
            params["name"] = volume
            records = c.get_all("/storage/volumes", params)
            if not records:
                return _ok({"error": f"Volume '{volume}' not found in SVM '{svm}'"})
            return _ok(records[0])
        # Try by UUID directly
        data = c.get(f"/storage/volumes/{volume}", {"fields": "*"})
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def qtree_list(volume: Optional[str] = None, svm: Optional[str] = None) -> str:
    """
    List qtrees with name, volume, SVM, security style, and path.

    Args:
        volume: Filter by volume name (optional).
        svm:    Filter by SVM name (optional).
    """
    try:
        c = get_client()
        params: dict = {"fields": "name,id,volume,svm,security_style,path,unix_permissions"}
        if volume:
            params["volume.name"] = volume
        if svm:
            params["svm.name"] = svm
        records = c.get_all("/storage/qtrees", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Storage — Disks & Shelves
# ---------------------------------------------------------------------------


@mcp.tool()
def disk_list(state: Optional[str] = None, node: Optional[str] = None) -> str:
    """
    List disks with name, type, RPM, state, owning node, bay, and shelf.

    Args:
        state: Filter by state — 'present', 'spare', 'broken', 'unfail' (optional).
        node:  Filter by owning node name (optional).
    """
    try:
        c = get_client()
        fields = "name,uid,type,rpm,state,node,bay,shelf,usable_size,container_type"
        params: dict = {"fields": fields}
        if state:
            params["state"] = state
        if node:
            params["node.name"] = node
        records = c.get_all("/storage/disks", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def shelf_list() -> str:
    """
    List drive shelves with model, serial number, state, module info,
    bay count, and disk occupancy.
    """
    try:
        c = get_client()
        fields = "name,uid,model,serial_number,state,module_type,bays,paths"
        records = c.get_all("/storage/shelves", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Storage — Snapshots
# ---------------------------------------------------------------------------


@mcp.tool()
def snapshot_list(volume_uuid: str, max_results: int = 50) -> str:
    """
    List snapshots for a volume.

    Args:
        volume_uuid: UUID of the volume (use volume_get to find the UUID).
        max_results:  Maximum number of snapshots to return (default 50).
    """
    try:
        c = get_client()
        fields = "name,uuid,create_time,size,owners,snapmirror_label,expiry_time"
        records = c.get_all(
            f"/storage/volumes/{volume_uuid}/snapshots",
            {"fields": fields},
            max_records=max_results,
        )
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def snapshot_policy_list() -> str:
    """
    List all snapshot policies with name, SVM scope, enabled state,
    and schedule/count/label rules.
    """
    try:
        c = get_client()
        fields = "name,uuid,svm,enabled,copies,comment"
        records = c.get_all("/storage/snapshot-policies", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# SVMs
# ---------------------------------------------------------------------------


@mcp.tool()
def svm_list() -> str:
    """
    List all Storage Virtual Machines (SVMs) with name, UUID, state,
    subtype, IP space, DNS, and enabled protocols.
    """
    try:
        c = get_client()
        fields = "name,uuid,state,subtype,ipspace,dns,nfs,cifs,iscsi,fcp,nvme,language"
        records = c.get_all("/svm/svms", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def svm_get(svm: str) -> str:
    """
    Get detailed information about a specific SVM by name or UUID.

    Args:
        svm: SVM name or UUID.
    """
    try:
        c = get_client()
        records = c.get_all("/svm/svms", {"name": svm, "fields": "*"})
        if not records:
            return _ok({"error": f"SVM not found: {svm}"})
        return _ok(records[0])
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------


@mcp.tool()
def lif_list(svm: Optional[str] = None) -> str:
    """
    List logical interfaces (LIFs) with name, SVM, IP address, current node/port,
    service policies, and data protocols.

    Args:
        svm: Filter by SVM name (optional).
    """
    try:
        c = get_client()
        fields = (
            "name,uuid,svm,ip,location,service_policy,services,"
            "state,failover_policy,dns_zone,data_protocol"
        )
        params: dict = {"fields": fields}
        if svm:
            params["svm.name"] = svm
        records = c.get_all("/network/ip/interfaces", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def port_list(node: Optional[str] = None) -> str:
    """
    List Ethernet ports with name, node, type, speed, MAC address,
    MTU, broadcast domain, and link state.

    Args:
        node: Filter by node name (optional).
    """
    try:
        c = get_client()
        fields = "name,uuid,node,type,speed,mac_address,mtu,broadcast_domain,state,reachability"
        params: dict = {"fields": fields}
        if node:
            params["node.name"] = node
        records = c.get_all("/network/ethernet/ports", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def route_list(svm: Optional[str] = None) -> str:
    """
    List IP routes with destination, gateway, SVM, and metric.

    Args:
        svm: Filter by SVM name (optional). Omit to list cluster-scoped routes.
    """
    try:
        c = get_client()
        fields = "destination,gateway,svm,metric,ipspace"
        params: dict = {"fields": fields}
        if svm:
            params["svm.name"] = svm
        records = c.get_all("/network/ip/routes", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Protocols — CIFS
# ---------------------------------------------------------------------------


@mcp.tool()
def cifs_service_list() -> str:
    """
    List CIFS (SMB) services per SVM with AD domain, server name,
    workgroup, Kerberos status, and enabled state.
    """
    try:
        c = get_client()
        fields = "name,svm,enabled,ad_domain,security,netbios"
        records = c.get_all("/protocols/cifs/services", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def cifs_share_list(svm: Optional[str] = None) -> str:
    """
    List CIFS shares with name, SVM, path, comment, access-based enumeration,
    oplocks, and ACLs.

    Args:
        svm: Filter by SVM name (optional).
    """
    try:
        c = get_client()
        fields = "name,svm,path,comment,access_based_enumeration,oplocks,acls,unix_symlink"
        params: dict = {"fields": fields}
        if svm:
            params["svm.name"] = svm
        records = c.get_all("/protocols/cifs/shares", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Protocols — NFS
# ---------------------------------------------------------------------------


@mcp.tool()
def nfs_service_list() -> str:
    """
    List NFS services per SVM with enabled protocols (NFSv3/v4/v4.1),
    Kerberos, and root squash settings.
    """
    try:
        c = get_client()
        fields = "svm,enabled,protocol,vstorage_enabled,transport,root,security"
        records = c.get_all("/protocols/nfs/services", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def nfs_export_policy_list(svm: Optional[str] = None) -> str:
    """
    List NFS export policies with name and SVM.

    Args:
        svm: Filter by SVM name (optional).
    """
    try:
        c = get_client()
        fields = "name,id,svm"
        params: dict = {"fields": fields}
        if svm:
            params["svm.name"] = svm
        records = c.get_all("/protocols/nfs/export-policies", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def nfs_export_policy_get(policy_id: int, svm: str) -> str:
    """
    Get the rules for a specific NFS export policy.

    Args:
        policy_id: Numeric export policy ID (from nfs_export_policy_list).
        svm:       SVM name that owns the policy.
    """
    try:
        c = get_client()
        rules = c.get_all(
            f"/protocols/nfs/export-policies/{policy_id}/rules",
            {"fields": "index,clients,ro_rule,rw_rule,superuser,allow_suid,protocols"},
        )
        policy = c.get_all(
            "/protocols/nfs/export-policies",
            {"id": policy_id, "svm.name": svm, "fields": "name,id,svm"},
        )
        return _ok(
            {
                "policy": policy[0] if policy else {"id": policy_id},
                "rules": {"num_records": len(rules), "records": rules},
            }
        )
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Data Protection — SnapMirror
# ---------------------------------------------------------------------------


@mcp.tool()
def snapmirror_list(
    svm: Optional[str] = None, state: Optional[str] = None
) -> str:
    """
    List SnapMirror relationships with source/destination volumes, policy,
    schedule, lag time, transfer state, and health.

    Args:
        svm:   Filter by source or destination SVM name (optional).
        state: Filter by relationship state — 'snapmirrored', 'uninitialized',
               'broken_off', 'quiesced' (optional).
    """
    try:
        c = get_client()
        fields = (
            "uuid,source,destination,policy,schedule,state,"
            "lag_time,transfer,healthy,unhealthy_reason"
        )
        params: dict = {"fields": fields}
        if svm:
            params["source.svm.name"] = svm
        if state:
            params["state"] = state
        records = c.get_all("/snapmirror/relationships", params)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Monitoring & Health
# ---------------------------------------------------------------------------


@mcp.tool()
def health_alert_list() -> str:
    """
    List active cluster health alerts with name, node, severity,
    resource, and corrective action.
    """
    try:
        c = get_client()
        fields = "name,uuid,node,severity,resource,state,acknowledge,corrective_action,cause"
        records = c.get_all("/cluster/health/alerts", {"fields": fields})
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def ems_event_list(
    severity: Optional[str] = None,
    max_results: int = 100,
) -> str:
    """
    List recent EMS (Event Management System) events.

    Args:
        severity:    Filter by minimum severity — 'emergency', 'alert', 'error',
                     'notice', 'informational', 'debug' (optional).
        max_results: Maximum number of events to return (default 100).
    """
    try:
        c = get_client()
        fields = "index,time,severity,node,message,parameters"
        params: dict = {"fields": fields, "order_by": "index desc"}
        if severity:
            params["severity"] = severity
        records = c.get_all("/support/ems/events", params, max_records=max_results)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def job_list(state: Optional[str] = None, max_results: int = 50) -> str:
    """
    List cluster jobs with UUID, description, state, progress, and timing.

    Args:
        state:       Filter by job state — 'queued', 'running', 'paused',
                     'success', 'failure' (optional).
        max_results: Maximum number of jobs to return (default 50).
    """
    try:
        c = get_client()
        fields = "uuid,description,state,message,start_time,end_time,node"
        params: dict = {"fields": fields}
        if state:
            params["state"] = state
        records = c.get_all("/cluster/jobs", params, max_records=max_results)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def quota_report_list(
    volume: Optional[str] = None, svm: Optional[str] = None, max_results: int = 200
) -> str:
    """
    List quota usage reports showing space and file consumption per quota target.

    Args:
        volume:      Filter by volume name (optional).
        svm:         Filter by SVM name (optional).
        max_results: Maximum number of records to return (default 200).
    """
    try:
        c = get_client()
        fields = "svm,volume,qtree,type,users,group,space,files"
        params: dict = {"fields": fields}
        if volume:
            params["volume.name"] = volume
        if svm:
            params["svm.name"] = svm
        records = c.get_all("/storage/quota/reports", params, max_records=max_results)
        return _ok({"num_records": len(records), "records": records})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


@mcp.tool()
def api_call(
    path: str,
    fields: Optional[str] = None,
    query_params: Optional[str] = None,
    paginate: bool = True,
) -> str:
    """
    Call any ONTAP REST API GET endpoint not covered by a dedicated tool.

    Args:
        path:         API path relative to /api (e.g. '/cluster/peers').
        fields:       Comma-separated field names to return (optional, e.g. 'name,uuid').
        query_params: Additional query params as a JSON object string
                      (e.g. '{"svm.name": "vs0", "state": "online"}').
        paginate:     If true (default), fetches all pages; if false, returns the raw
                      first-page response including _links.
    """
    try:
        c = get_client()
        params: dict = {}
        if fields:
            params["fields"] = fields
        if query_params:
            params.update(json.loads(query_params))
        if paginate:
            records = c.get_all(path, params)
            return _ok({"num_records": len(records), "records": records})
        data = c.get(path, params)
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
