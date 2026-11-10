"""
1Password SaaS Manager (formerly Trelica) MCP Server (read-only)

Exposes SaaS Manager inventory (applications and their user accounts, people, devices, contracts,
workflows, audit log) as MCP tools. Read-only by construction: tokens carry only read scopes and the
client only issues GET requests.

Configuration via environment variables:
  SAAS_MANAGER_HOST          - API host: trelica.app (default) or trelica.eu
  SAAS_MANAGER_CLIENT_ID     - OAuth client ID (required)
  SAAS_MANAGER_CLIENT_SECRET - OAuth client secret (required)
  SAAS_MANAGER_TIMEOUT       - Request timeout in seconds (default: 60)
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import SaasManagerClient, SaasManagerError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("SaaS-Manager")

_client: Optional[SaasManagerClient] = None

# Most records scanned when a tool filters client-side (the API has no filter for these fields)
FILTER_SCAN = 25000


def get_client() -> SaasManagerClient:
    global _client
    if _client is None:
        host = os.environ.get("SAAS_MANAGER_HOST", "trelica.app").strip()
        client_id = os.environ.get("SAAS_MANAGER_CLIENT_ID", "").strip()
        client_secret = os.environ.get("SAAS_MANAGER_CLIENT_SECRET", "")
        timeout = float(os.environ.get("SAAS_MANAGER_TIMEOUT", "60"))
        if not client_id or not client_secret:
            raise RuntimeError("SAAS_MANAGER_CLIENT_ID and SAAS_MANAGER_CLIENT_SECRET are required")
        _client = SaasManagerClient(host, client_id, client_secret, timeout)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, SaasManagerError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


def _pick(obj: dict, *fields: str) -> dict:
    return {f: obj.get(f) for f in fields if obj.get(f) not in (None, "", [])}


def _listing(key: str, items: list, more: bool) -> str:
    return _ok({"returned": len(items), "more_available": more, key: items})


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@mcp.tool()
def list_apps(q: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> str:
    """
    List applications in SaaS Manager: id, name, status, vendor and licence summary.
    There are about 1,300 apps (only ~60 Managed), so search with q where possible.

    Args:
        q:      Free-text search, e.g. an app or vendor name (optional).
        status: Filter by status text, case-insensitive exact match, Managed, New, InReview, Accepted, PlanToClose, Closed, Ignored (optional).
        limit:  Maximum apps to return (default 100, max 5000).
    """
    try:
        params = {"q": q} if q else {}
        apps, more = get_client().get_all("/api/apps/v1", params, max_items=min(limit, 5000) if not status else FILTER_SCAN)
        if status:
            apps = [a for a in apps if str(a.get("status", "")).lower() == status.lower()]
            more = more or len(apps) > limit
            apps = apps[:limit]
        apps = [_pick(a, "id", "name", "status", "vendor", "licenses", "lastModifiedDtm") for a in apps]
        return _listing("apps", apps, more)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_app(app_id: str) -> str:
    """
    Full detail for one application, including licences and custom fields.

    Args:
        app_id: Application ID (from list_apps).
    """
    try:
        return _ok(get_client().get(f"/api/apps/v1/{app_id}"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_app_users(app_id: str, status: Optional[str] = None, inactive_days: Optional[int] = None, limit: int = 1000) -> str:
    """
    List the user accounts in one application: name, email, status and last login. Use for licence
    utilisation (inactive_days) and leaver checks.

    Args:
        app_id:        Application ID (from list_apps).
        status:        Filter by account status, case-insensitive exact match (optional).
        inactive_days: Only accounts whose last login is older than N days, or who never logged in (optional).
        limit:         Maximum accounts to return (default 1000).
    """
    try:
        users, more = get_client().get_all(f"/api/apps/v1/{app_id}/users", max_items=FILTER_SCAN)
        if status:
            users = [u for u in users if str(u.get("status", "")).lower() == status.lower()]
        if inactive_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)

            def stale(u: dict) -> bool:
                last = u.get("lastLoginDtm")
                if not last:
                    return True
                try:
                    return datetime.fromisoformat(str(last).replace("Z", "+00:00")) < cutoff
                except ValueError:
                    return False

            users = [u for u in users if stale(u)]
        total = len(users)
        users = [_pick(u, "id", "name", "email", "status", "lastLoginDtm", "deleted") for u in users[:limit]]
        return _ok({"matched": total, "matched_is_partial": more, "returned": len(users), "more_available": more or total > limit, "users": users})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


@mcp.tool()
def list_people(q: Optional[str] = None, person_type: Optional[str] = None, limit: int = 100) -> str:
    """
    List people (employees, contractors, external, service accounts) known to SaaS Manager, with
    teams and leaving date.

    Args:
        q:           Free-text search, e.g. a name or email (optional).
        person_type: Filter by person type, case-insensitive exact match, Employee, Contractor, External, ServiceAccount (optional).
        limit:       Maximum people to return (default 100).
    """
    try:
        params = {"q": q} if q else {}
        people, more = get_client().get_all("/api/people/v1", params, max_items=min(limit, 5000) if not person_type else FILTER_SCAN)
        if person_type:
            people = [p for p in people if str(p.get("personType", "")).lower() == person_type.lower()]
            more = more or len(people) > limit
            people = people[:limit]
        people = [
            _pick(p, "id", "firstName", "lastName", "email", "personType", "status", "teams", "leavingDate",
                  "aliases", "lastModifiedDtm")
            for p in people
        ]
        return _listing("people", people, more)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_person(person_id: str) -> str:
    """
    Full detail for one person.

    Args:
        person_id: Person ID (from list_people).
    """
    try:
        return _ok(get_client().get(f"/api/people/v1/{person_id}"))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Devices, contracts
# ---------------------------------------------------------------------------


@mcp.tool()
def list_assets(q: Optional[str] = None, limit: int = 100) -> str:
    """
    List devices (assets): name, model, serial, asset tag, status and who they're assigned to.

    Args:
        q:     Free-text search, e.g. a device name, serial or person (optional).
        limit: Maximum devices to return (default 100).
    """
    try:
        params = {"q": q} if q else {}
        assets, more = get_client().get_all("/api/assets/v1", params, max_items=min(limit, 5000))
        assets = [
            _pick(a, "id", "deviceName", "hardwareVendor", "modelName", "serialNumber", "assetTag", "status",
                  "statusType", "assignedTo", "assignedToEmail")
            for a in assets
        ]
        return _listing("assets", assets, more)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_contracts(renewal_within_days: Optional[int] = None, limit: int = 200) -> str:
    """
    List contracts with start and renewal dates and line items, soonest renewal first.

    Args:
        renewal_within_days: Only contracts renewing within the next N days (optional).
        limit:               Maximum contracts to return (default 200).
    """
    try:
        contracts, more = get_client().get_all("/api/contracts/v1", max_items=5000)
        if renewal_within_days is not None:
            today = datetime.now(timezone.utc).date()
            horizon = today + timedelta(days=renewal_within_days)

            def renews_soon(c: dict) -> bool:
                try:
                    d = datetime.fromisoformat(str(c.get("renewalDate"))[:10]).date()
                    return today <= d <= horizon
                except ValueError:
                    return False

            contracts = [c for c in contracts if renews_soon(c)]
        contracts.sort(key=lambda c: str(c.get("renewalDate") or "9999"))
        total = len(contracts)
        return _ok({"matched": total, "returned": min(total, limit), "more_available": more, "contracts": contracts[:limit]})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Audit log, workflows, SaaS Manager users
# ---------------------------------------------------------------------------


@mcp.tool()
def list_audit_log(since: Optional[str] = None, limit: int = 100) -> str:
    """
    SaaS Manager's own audit log (who changed what in SaaS Manager).

    Args:
        since: ISO-8601 timestamp, e.g. '2026-09-01T00:00:00Z' (optional).
        limit: Maximum entries to return (default 100).
    """
    try:
        params = {"since": since} if since else {}
        logs, more = get_client().get_all("/api/audit/v1/logs", params, max_items=min(limit, 5000))
        return _listing("entries", logs, more)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_workflows(limit: int = 200) -> str:
    """
    List workflow definitions (onboarding/offboarding and other automations): id, name, enabled, trigger.
    """
    try:
        flows, more = get_client().get_all("/api/workflows/v1", max_items=min(limit, 5000))
        flows = [_pick(f, "id", "name", "description", "enabled", "trigger", "lastModifiedDtm", "deleted") for f in flows]
        return _listing("workflows", flows, more)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_workflow_runs(workflow_id: str, limit: int = 50) -> str:
    """
    List runs of one workflow: status, when, and what triggered it.

    Args:
        workflow_id: Workflow ID (from list_workflows).
        limit:       Maximum runs to return (default 50).
    """
    try:
        runs, more = get_client().get_all(f"/api/workflows/v1/{workflow_id}/runs", max_items=min(limit, 5000))
        runs = [_pick(r, "id", "name", "status", "createdDtm", "createdBy", "lastModifiedDtm", "trigger", "context") for r in runs]
        return _listing("runs", runs, more)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_saas_manager_users() -> str:
    """
    People who can sign in to SaaS Manager itself (SCIM users): name, email, active.
    """
    try:
        c = get_client()
        users: list = []
        start = 1
        while True:
            page = c.get("/api/scim/v2/Users", {"startIndex": start, "count": 100}) or {}
            batch = page.get("Resources") or []
            users.extend(batch)
            start += len(batch)
            if not batch or len(users) >= int(page.get("totalResults") or 0):
                break
        compact = []
        for u in users:
            emails = [e.get("value") for e in u.get("emails") or [] if e.get("value")]
            compact.append({"id": u.get("id"), "userName": u.get("userName"), "name": (u.get("name") or {}).get("formatted"),
                            "emails": emails, "active": u.get("active")})
        return _ok({"total": len(compact), "users": compact})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Read-only escape hatch
# ---------------------------------------------------------------------------


@mcp.tool()
def api_get(path: str, query_params: Optional[str] = None) -> str:
    """
    GET any SaaS Manager API path not covered by a dedicated tool (read-only; path must start
    with /api/), e.g. '/api/apps/v1/{id}/users'.

    Args:
        path:         API path starting with /api/.
        query_params: Query parameters as a JSON object string, e.g. '{"limit": 10}' (optional).
    """
    try:
        params = json.loads(query_params) if query_params else None
        return _ok(get_client().get(path, params))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
