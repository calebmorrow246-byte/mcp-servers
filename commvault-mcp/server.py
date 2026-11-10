"""
Commvault MCP Server

Exposes read-only Commvault REST API operations as MCP tools.

Endpoints verified against CommServe 11.40.67 (cv01, API on cvweb01): the classic
Command Center API (/Job, /Client, /Events, /AlertRule, /StoragePool, /Plan, /Subclient, /CommServ)
and the V4 endpoints that exist on this version (/V4/Servers, /V4/ServerGroup, /V4/Hypervisor).
The lowercase /v4/jobs-style paths return 404 here.

Configuration via environment variables:
  COMMVAULT_HOST       - Command Center web server hostname (required)
  COMMVAULT_USERNAME   - Service account username (required)
  COMMVAULT_PASSWORD   - Service account password (required)
  COMMVAULT_API_PATH   - API base path (default: /commandcenter/api)
  COMMVAULT_VERIFY_SSL - Verify TLS certificate: true/false (default: false)
  COMMVAULT_TIMEOUT    - Request timeout in seconds (default: 30)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import CommvaultClient, CommvaultError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("Commvault")

_client: Optional[CommvaultClient] = None


def get_client() -> CommvaultClient:
    global _client
    if _client is None:
        host = os.environ.get("COMMVAULT_HOST", "").strip()
        username = os.environ.get("COMMVAULT_USERNAME", "").strip()
        password = os.environ.get("COMMVAULT_PASSWORD", "").strip()
        api_path = os.environ.get("COMMVAULT_API_PATH", "/commandcenter/api").strip()
        verify_ssl = os.environ.get("COMMVAULT_VERIFY_SSL", "false").lower() == "true"
        timeout = float(os.environ.get("COMMVAULT_TIMEOUT", "30"))
        if not host:
            raise RuntimeError("COMMVAULT_HOST environment variable is required")
        if not username or not password:
            raise RuntimeError("COMMVAULT_USERNAME and COMMVAULT_PASSWORD are required")
        _client = CommvaultClient(host, username, password, verify_ssl, timeout, api_path)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, CommvaultError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


def _ts(epoch: Any) -> Optional[str]:
    """Commvault epoch seconds -> ISO 8601 UTC (None for 0/missing)."""
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
    limit/offset are given (529 jobs/day, ~3,900/week as of 2026-09-24), so page through them."""
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
    List backup/restore jobs (active plus those finished in the last N days), newest first.

    Args:
        status:      Filter by status text, case-insensitive substring — e.g. 'Completed',
                     'Failed', 'Running', 'Killed', 'Pending', 'Waiting', 'errors' (optional).
        client_name: Filter by client name, case-insensitive substring (optional).
        job_type:    Filter by job type, substring — e.g. 'Backup', 'Restore', 'Aux Copy' (optional).
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
    Get full detail for a specific job by ID.

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
    List jobs that failed, were killed, or completed with errors — a quick health check.

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
# Clients
# ---------------------------------------------------------------------------


@mcp.tool()
def list_clients(name: Optional[str] = None) -> str:
    """
    List clients (servers/VMs protected by Commvault) with ID, name and hostname.

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
    Get detailed information about a specific client by ID: identity, OS, version, client groups,
    readiness, VM status and installed features.

    Args:
        client_id:   The numeric client ID (from list_clients).
        include_all: Also return the full 'clientProps' settings block (~40k characters).
                     Only ask for it when a specific setting is needed.
    """
    try:
        data = get_client().get(f"/Client/{client_id}") or {}
        props = [dict(p) for p in data.get("clientProperties") or []]
        if not include_all:
            for p in props:
                if "clientProps" in p:
                    p["clientProps"] = "(omitted - call again with include_all=true)"
        # Compact JSON: this response is large even trimmed
        return json.dumps({"clientProperties": props}, default=str)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_servers() -> str:
    """
    List servers as shown on the Command Center 'Servers' page (V4 API), including their
    configuration and status summary.
    """
    try:
        return _ok(get_client().get("/V4/Servers"))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Events & Alerts
# ---------------------------------------------------------------------------


@mcp.tool()
def list_events(
    severity: Optional[str] = None,
    limit: int = 100,
) -> str:
    """
    List recent CommServe events (event viewer), newest first.

    Args:
        severity: Filter by severity text, case-insensitive substring — e.g. 'critical',
                  'major', 'minor', 'info' (optional).
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


@mcp.tool()
def list_alerts() -> str:
    """
    List currently triggered alerts from the Commvault alert console.
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
    List configured alert definitions (rules): name, ID and category.
    """
    try:
        data = get_client().get("/AlertRule") or {}
        rules = []
        for a in data.get("alertList") or []:
            rules.append({
                "id": (a.get("alert") or {}).get("id") or a.get("id"),
                "name": (a.get("alert") or {}).get("name") or a.get("name"),
                "category": (a.get("alertCategory") or {}).get("name"),
                "type": (a.get("alertType") or {}).get("name"),
            })
        return _ok({"total": len(rules), "alerts": rules})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Storage & plans
# ---------------------------------------------------------------------------


@mcp.tool()
def list_storage_pools() -> str:
    """
    List storage pools with type, capacity and free space.
    """
    try:
        data = get_client().get("/StoragePool") or {}
        pools = data.get("storagePoolList") or []
        return _ok({"total": len(pools), "storage_pools": pools})
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


@mcp.tool()
def list_subclients(client_id: int) -> str:
    """
    List subclients (backup content definitions) for one client.

    Args:
        client_id: Client ID (from list_clients). Required on this Commvault version.
    """
    try:
        data = get_client().get("/Subclient", {"clientId": client_id}) or {}
        subclients = data.get("subClientProperties") or []
        return _ok({"total": len(subclients), "subclients": subclients})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# CommCell overview
# ---------------------------------------------------------------------------


@mcp.tool()
def get_commcell_overview() -> str:
    """
    Return a CommCell summary: CommServe version and host, client and server counts,
    storage pool count, and job counts by status over the last 24 hours.
    """
    try:
        c = get_client()
        commserv = c.get("/CommServ") or {}
        clients = (c.get("/Client") or {}).get("clientProperties") or []
        servers = c.get("/V4/Servers") or {}
        pools = (c.get("/StoragePool") or {}).get("storagePoolList") or []
        by_status: dict = {}
        for j in _fetch_jobs(1):
            status = str(_job_summary(j)["status"])
            by_status[status] = by_status.get(status, 0) + 1
        return _ok({
            "commserve": commserv,
            "client_count": len(clients),
            "server_count": servers.get("totalServers"),
            "storage_pool_count": len(pools),
            "jobs_last_24h_by_status": by_status,
        })
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


@mcp.tool()
def api_call(
    method: str,
    path: str,
    query_params: Optional[str] = None,
) -> str:
    """
    Call any Commvault REST API GET endpoint not covered by a dedicated tool.

    Args:
        method:       HTTP method — only 'GET' is supported (read-only server).
        path:         API path relative to the base URL (e.g. '/MediaAgent', '/V4/ServerGroup',
                      '/StoragePolicy', '/Library').
        query_params: Query parameters as a JSON object string
                      (e.g. '{"clientId": 2}').
    """
    try:
        if method.upper() != "GET":
            return json.dumps({"error": "Only GET is supported — this is a read-only MCP server"})
        c = get_client()
        params: dict = {}
        if query_params:
            params = json.loads(query_params)
        data = c.get(path, params)
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
