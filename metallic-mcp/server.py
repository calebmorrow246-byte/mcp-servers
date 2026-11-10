"""
CommVault Metallic MCP Server (read-only)

Exposes the company's Metallic tenant (company ExampleCompanyInc on mXXX.metallic.io) as MCP
tools: jobs, clients/servers/VMs, alerts, storage and plans. Same Command Center API family as the
on-prem commvault-mcp, but tenant-scoped (CommCell-level pages such as /CommServ return 403) and
authenticated with a renewable API access token instead of a password.

The token pair is read from and written back to the running account's Windows Credential Manager
(targets 'Metallic Access Token' and 'Metallic Refresh Token'), because every renewal rotates it.

Configuration via environment variables:
  METALLIC_HOST     - Metallic Command Center host (default: mXXX.metallic.io)
  METALLIC_TIMEOUT  - Request timeout in seconds (default: 60)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

import wincred
from client import ACCESS_TARGET, REFRESH_TARGET, STORE_HINT, MetallicClient, MetallicError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("Metallic")

_client: Optional[MetallicClient] = None


def _load_tokens() -> tuple:
    access = wincred.read_credential(ACCESS_TARGET)
    refresh = wincred.read_credential(REFRESH_TARGET)
    if not access or not refresh:
        raise MetallicError("credential", f"Metallic token pair not found in Credential Manager. {STORE_HINT}")
    return access[1], refresh[1]


def _save_tokens(access: str, refresh: str) -> None:
    wincred.write_credential(ACCESS_TARGET, "token", access)
    wincred.write_credential(REFRESH_TARGET, "token", refresh)


def get_client() -> MetallicClient:
    global _client
    if _client is None:
        host = os.environ.get("METALLIC_HOST", "mXXX.metallic.io").strip()
        timeout = float(os.environ.get("METALLIC_TIMEOUT", "60"))
        _client = MetallicClient(host, _load_tokens, _save_tokens, timeout)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, MetallicError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


def _ts(epoch: Any) -> Optional[str]:
    """Epoch seconds -> ISO 8601 UTC (None for 0/missing)."""
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat() if epoch else None
    except (TypeError, ValueError, OSError):
        return None


def _job_summary(job: dict) -> dict:
    """Compact view of one /Job record. Full detail comes from get_job."""
    s = job.get("jobSummary", job)
    sub = s.get("subclient") or {}
    return {
        "job_id": s.get("jobId"),
        "status": s.get("status"),
        "job_type": s.get("jobType") or s.get("localizedOperationName"),
        "backup_level": s.get("backupLevelName"),
        "client": sub.get("clientName") or s.get("destClientName"),
        "agent": s.get("appTypeName"),
        "subclient": sub.get("subclientName"),
        "start": _ts(s.get("jobStartTime")),
        "end": _ts(s.get("jobEndTime")),
        "percent_complete": s.get("percentComplete"),
        "size_bytes": s.get("sizeOfApplication"),
        "pending_reason": s.get("pendingReason") or None,
    }


JOB_PAGE_SIZE = 1000
MAX_JOBS = 20000


def _fetch_jobs(last_n_days: int, client_id: Optional[int] = None) -> list:
    """All jobs active or finished in the last N days. /Job returns only 100 records unless
    limit/offset are given, so page through them."""
    params: dict = {
        "completedJobLookupTime": max(1, int(last_n_days)) * 86400,
        "limit": JOB_PAGE_SIZE,
        "offset": 0,
    }
    if client_id is not None:
        params["clientId"] = client_id
    jobs: list = []
    while True:
        data = get_client().get("/Job", params) or {}
        batch = data.get("jobs") or []
        jobs.extend(batch)
        total = int(data.get("totalRecordsWithoutPaging") or 0)
        params["offset"] += JOB_PAGE_SIZE
        if len(batch) < JOB_PAGE_SIZE or params["offset"] >= total or len(jobs) >= MAX_JOBS:
            return jobs


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@mcp.tool()
def list_jobs(
    status: Optional[str] = None,
    client_name: Optional[str] = None,
    job_type: Optional[str] = None,
    last_n_days: int = 1,
    limit: int = 50,
) -> str:
    """
    List Metallic backup/restore jobs (active plus those finished in the last N days), newest first.

    Args:
        status:      Filter by status text, case-insensitive substring, e.g. 'Completed',
                     'Failed', 'Running', 'Killed', 'Pending', 'errors' (optional).
        client_name: Filter by client name, case-insensitive substring (optional).
        job_type:    Filter by job type, substring, e.g. 'Backup', 'Restore', 'Aux Copy' (optional).
        last_n_days: How many days of finished jobs to include (default 1).
        limit:       Maximum jobs to return (default 50).
    """
    try:
        jobs = [_job_summary(j) for j in _fetch_jobs(last_n_days)]
        if status:
            jobs = [j for j in jobs if status.lower() in str(j["status"]).lower()]
        if client_name:
            jobs = [j for j in jobs if client_name.lower() in str(j["client"]).lower()]
        if job_type:
            jobs = [j for j in jobs if job_type.lower() in str(j["job_type"]).lower()]
        jobs.sort(key=lambda j: j["job_id"] or 0, reverse=True)
        return _ok({"matched": len(jobs), "returned": min(len(jobs), limit), "jobs": jobs[:limit]})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_job(job_id: int) -> str:
    """
    Get full detail for a specific Metallic job by ID.

    Args:
        job_id: The numeric job ID.
    """
    try:
        data = get_client().get(f"/Job/{job_id}") or {}
        jobs = data.get("jobs") or []
        return _ok(jobs[0] if jobs else data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_failed_jobs(last_n_days: int = 1) -> str:
    """
    List Metallic jobs that failed, were killed, or completed with errors: a quick health check.

    Args:
        last_n_days: How many days back to look (default 1).
    """
    try:
        bad = ("fail", "kill", "error")
        jobs = [_job_summary(j) for j in _fetch_jobs(last_n_days)]
        jobs = [j for j in jobs if any(word in str(j["status"]).lower() for word in bad)]
        jobs.sort(key=lambda j: j["job_id"] or 0, reverse=True)
        return _ok({"total": len(jobs), "jobs": jobs})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Clients, servers, VMs
# ---------------------------------------------------------------------------


@mcp.tool()
def list_clients(name: Optional[str] = None) -> str:
    """
    List clients in the Metallic tenant (servers, file servers, hypervisors, VMs) with ID, name and hostname.

    Args:
        name: Filter by client/display/host name, case-insensitive substring (optional).
    """
    try:
        data = get_client().get("/Client") or {}
        clients = []
        for prop in data.get("clientProperties") or []:
            entity = (prop.get("client") or {}).get("clientEntity") or {}
            clients.append({
                "client_id": entity.get("clientId"),
                "name": entity.get("clientName"),
                "display_name": entity.get("displayName"),
                "host_name": entity.get("hostName"),
            })
        if name:
            needle = name.lower()
            clients = [c for c in clients if any(needle in str(v).lower() for v in (c["name"], c["display_name"], c["host_name"]))]
        return _ok({"total": len(clients), "clients": clients})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_client_detail(client_id: int, include_all: bool = False) -> str:
    """
    Get detailed information about one client by ID: identity, OS, version, client groups and features.

    Args:
        client_id:   The numeric client ID (from list_clients).
        include_all: Also return the full 'clientProps' settings block (large). Only ask for it
                     when a specific setting is needed.
    """
    try:
        data = get_client().get(f"/Client/{client_id}") or {}
        props = [dict(p) for p in data.get("clientProperties") or []]
        if not include_all:
            for p in props:
                if "clientProps" in p:
                    p["clientProps"] = "(omitted - call again with include_all=true)"
        return json.dumps({"clientProperties": props}, default=str)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_servers() -> str:
    """
    List servers as shown on the Metallic 'Servers' page: name, host, OS, agents, last backup, plan.
    """
    try:
        return _ok(get_client().get("/V4/Servers"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_file_servers() -> str:
    """
    List file servers protected by Metallic: name, host, last backup, application size, plan.
    """
    try:
        return _ok(get_client().get("/V4/FileServers"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_hypervisors() -> str:
    """
    List hypervisors (virtualization clients) configured in Metallic.
    """
    try:
        return _ok(get_client().get("/V4/Hypervisor"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_virtual_machines() -> str:
    """
    List virtual machines protected by Metallic: name, hypervisor, VM group, OS and backup status.
    """
    try:
        return _ok(get_client().get("/V4/VirtualMachines"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_server_groups() -> str:
    """
    List server groups in the tenant with their server counts.
    """
    try:
        return _ok(get_client().get("/V4/ServerGroup"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_subclients(client_id: int) -> str:
    """
    List subclients (backup content definitions) for one client.

    Args:
        client_id: Client ID (from list_clients). Required.
    """
    try:
        data = get_client().get("/Subclient", {"clientId": client_id}) or {}
        subclients = data.get("subClientProperties") or []
        return _ok({"total": len(subclients), "subclients": subclients})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Alerts & events
# ---------------------------------------------------------------------------


@mcp.tool()
def list_alerts() -> str:
    """
    List currently triggered alerts visible to the tenant.
    """
    try:
        data = get_client().get("/Alert")
        if not data:
            return _ok({"total": 0, "alerts": []})
        alerts = data.get("feedsList") or data.get("alertList") or data.get("alerts") or data
        return _ok({"total": len(alerts) if isinstance(alerts, list) else None, "alerts": alerts})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_alert_definitions() -> str:
    """
    List configured alert definitions (rules) in the tenant: name, ID, category and type.
    """
    try:
        data = get_client().get("/AlertRule") or {}
        rules = []
        for a in data.get("alertList") or []:
            rules.append({
                "id": (a.get("alert") or {}).get("id") or a.get("id"),
                "name": (a.get("alert") or {}).get("name") or a.get("name") or a.get("description"),
                "category": (a.get("alertCategory") or {}).get("name"),
                "type": (a.get("alertType") or {}).get("name") if isinstance(a.get("alertType"), dict) else a.get("alertType"),
                "status": a.get("status"),
            })
        return _ok({"total": len(rules), "alerts": rules})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_events(severity: Optional[str] = None, limit: int = 100) -> str:
    """
    List recent events visible to the tenant, newest first.

    Args:
        severity: Filter by severity text, case-insensitive substring (optional).
        limit:    Maximum events to return (default 100).
    """
    try:
        data = get_client().get("/Events", {"level": 10}) or {}
        events = data.get("commservEvents") or []
        if severity:
            events = [e for e in events if severity.lower() in str(e.get("severity")).lower()]
        for e in events:
            if "timeSource" in e:
                e["time"] = _ts(e.get("timeSource"))
        return _ok({"matched": len(events), "returned": min(len(events), limit), "events": events[:limit]})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Storage & plans
# ---------------------------------------------------------------------------


@mcp.tool()
def list_storage() -> str:
    """
    Metallic storage: storage pools (capacity, free space, retention, cloud storage class) plus
    the disk, local and cloud storage views.
    """
    try:
        c = get_client()
        out: dict = {}
        out["storage_pools"] = (c.get("/StoragePool") or {}).get("storagePoolList") or []
        for key, path in (("disk", "/V4/Storage/Disk"), ("local", "/V4/Storage/Local"), ("cloud", "/V4/Storage/Cloud")):
            try:
                data = c.get(path) or {}
                out[key] = next((v for v in data.values() if isinstance(v, list)), [])
            except MetallicError as exc:
                out[key] = {"error": exc.message}
        return _ok(out)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_plans() -> str:
    """
    List data protection plans (backup schedules, retention, storage targets).
    """
    try:
        data = get_client().get("/Plan") or {}
        plans = data.get("plans") or []
        return _ok({"total": len(plans), "plans": plans})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Overview & token status
# ---------------------------------------------------------------------------


@mcp.tool()
def get_tenant_overview() -> str:
    """
    Metallic tenant summary: company, client/server/VM counts, storage pool count, and job counts
    by status over the last 24 hours.
    """
    try:
        c = get_client()
        company = ((c.get("/V4/Company") or {}).get("companies") or [{}])[0]
        clients = (c.get("/Client") or {}).get("clientProperties") or []
        servers = c.get("/V4/Servers") or {}
        vms = c.get("/V4/VirtualMachines") or {}
        pools = (c.get("/StoragePool") or {}).get("storagePoolList") or []
        by_status: dict = {}
        for j in _fetch_jobs(1):
            status = str(_job_summary(j)["status"])
            by_status[status] = by_status.get(status, 0) + 1
        return _ok({
            "company": {k: company.get(k) for k in ("id", "name", "alias", "status")},
            "client_count": len(clients),
            "server_count": servers.get("totalServers"),
            "vm_count": vms.get("virtualMachinesCount"),
            "storage_pool_count": len(pools),
            "jobs_last_24h_by_status": by_status,
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_token_status() -> str:
    """
    Status of the API token this server uses: current expiry (renewed automatically) and the
    'renewable until' date. After that date a new token must be created in the Metallic console
    and stored on mcp-host, or this server stops working.
    """
    try:
        data = get_client().get("/V4/AccessToken") or {}
        tokens = next((v for v in data.values() if isinstance(v, list)), [])
        out = []
        for t in tokens:
            until = t.get("renewableUntilTimestamp")
            out.append({
                "token_name": t.get("tokenName"),
                "created": _ts(t.get("createdTime")),
                "last_used": _ts(t.get("lastUsedTime")),
                "access_token_expires": _ts(t.get("tokenExpiryTimestamp")),
                "renewable_until": _ts(until),
                "days_until_replacement_needed": round((int(until) - time.time()) / 86400, 1) if until else None,
            })
        return _ok({"tokens": out, "replace_with": STORE_HINT})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


@mcp.tool()
def api_call(method: str, path: str, query_params: Optional[str] = None) -> str:
    """
    Call any Metallic Command Center API GET endpoint not covered by a dedicated tool.

    Args:
        method:       HTTP method: only 'GET' is supported (read-only server).
        path:         API path relative to the base URL (e.g. '/MediaAgent', '/Library', '/StoragePolicy').
        query_params: Query parameters as a JSON object string (e.g. '{"clientId": 2}').
    """
    try:
        if method.upper() != "GET":
            return json.dumps({"error": "Only GET is supported: this is a read-only MCP server"})
        params = json.loads(query_params) if query_params else {}
        return _ok(get_client().get(path, params))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
