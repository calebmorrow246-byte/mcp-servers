# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-10-28 - dict query_params, list filters, include_inactive, source fallback, derived account reports
"""
Delinea MCP Server (read-only, Discovery)

Exposes Secret Server Discovery (sources, scan status and metrics, discovered network items, scanners,
rules, audit) through the Delinea Platform as MCP tools. Read-only by construction: the client issues
only GET requests to /v1/discovery paths and redacts every credential-bearing field. There is no tool
that reads secrets.

Configuration via environment variables:
  DELINEA_TENANT_HOST        - Platform host (default: example.delinea.app)
  DELINEA_CLIENT_ID          - Service user username (required)
  DELINEA_CLIENT_SECRET      - Service user password (required)
  DELINEA_SECRET_SERVER_URL  - Secret Server base URL; default is discovered through the Vault Broker
  DELINEA_TIMEOUT            - Request timeout in seconds (default: 60)
"""

import json
import logging
import os
import sys
from typing import Any, Optional, Union

from mcp.server.mcpserver import MCPServer

from client import DelineaClient, DelineaError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("Delinea")

_client: Optional[DelineaClient] = None

# Some MCP clients turn a JSON-object string into a dict before validation, so accept both forms
QueryParams = Optional[Union[dict, str]]

NETWORK_ITEM_TYPES = ("computer", "computer-account", "directory-account", "service-account", "public-key")


def get_client() -> DelineaClient:
    global _client
    if _client is None:
        host = os.environ.get("DELINEA_TENANT_HOST", "example.delinea.app").strip()
        client_id = os.environ.get("DELINEA_CLIENT_ID", "").strip()
        client_secret = os.environ.get("DELINEA_CLIENT_SECRET", "")
        override = os.environ.get("DELINEA_SECRET_SERVER_URL", "").strip() or None
        timeout = float(os.environ.get("DELINEA_TIMEOUT", "60"))
        if not client_id or not client_secret:
            raise RuntimeError("DELINEA_CLIENT_ID and DELINEA_CLIENT_SECRET are required")
        _client = DelineaClient(host, client_id, client_secret, override, timeout)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, DelineaError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


def _parse_params(extra: QueryParams) -> dict:
    """Query parameters from a dict or a JSON object string; anything else is an error."""
    if not extra:
        return {}
    params = json.loads(extra) if isinstance(extra, str) else dict(extra)
    if not isinstance(params, dict):
        raise ValueError("query_params must be a JSON object")
    return params


def _call(path: str, params: Optional[dict] = None) -> str:
    try:
        return _ok(get_client().get(path, params))
    except Exception as exc:
        return _err(exc)


def _paged(path: str, take: int, skip: int, extra: QueryParams) -> str:
    """List call with take/skip paging plus optional extra query parameters (dict or JSON object string)."""
    try:
        params = _parse_params(extra)
        params["take"] = max(1, min(take, 500))
        params["skip"] = max(0, skip)
        return _ok(get_client().get(path, params))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


@mcp.tool()
def get_token_status() -> str:
    """Check that the Delinea service user can authenticate and which Secret Server it reaches.

    Returns authentication state and the resolved Secret Server URL. Never returns the token.
    """
    try:
        c = get_client()
        status = c.token_status()
        status["secret_server_url"] = c.secret_server_url()
        return _ok(status)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Sources and status
# ---------------------------------------------------------------------------


@mcp.tool()
def list_discovery_sources(take: int = 100, skip: int = 0, include_inactive: bool = False,
                           query_params: QueryParams = None) -> str:
    """List discovery sources (Active Directory domains, computers scanned, etc.) with their status.

    Inactive sources are hidden unless include_inactive is true (get_discovery_status counts them).

    Args:
        take:             Records to return (1-500).
        skip:             Records to skip, for paging.
        include_inactive: Also return inactive sources.
        query_params:     Extra query parameters as a JSON object (or JSON string), optional.
    """
    try:
        params = _parse_params(query_params)
        if include_inactive:
            params["filter.includeInactive"] = "true"
        return _paged("/v1/discovery/sources", take, skip, params)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_discovery_source(source_id: int) -> str:
    """Get one discovery source in full (configuration, schedule, last run).

    Secret Server Cloud currently answers the single-source endpoint with a 500; when that happens the
    matching row from the sources list is returned instead, marked with "fallback".

    Args:
        source_id: Discovery source ID.
    """
    try:
        return _ok(get_client().get(f"/v1/discovery/source/{int(source_id)}"))
    except DelineaError as exc:
        if exc.code != 500:
            return _err(exc)
    except Exception as exc:
        return _err(exc)
    try:
        listing = get_client().get("/v1/discovery/sources", {"take": 500, "skip": 0, "filter.includeInactive": "true"})
        for row in listing.get("records", []):
            if row.get("discoverySourceId") == int(source_id):
                return _ok({"fallback": "single-source endpoint returned 500; row from the sources list", **row})
        return json.dumps({"error": f"discovery source {int(source_id)} not found", "code": 404})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_discovery_status() -> str:
    """Overall Discovery status: whether scans are running and recent activity.

    discoverySourceCount includes inactive sources; list_discovery_sources hides them by default.
    """
    return _call("/v1/discovery/status")


@mcp.tool()
def get_discovery_scan_results() -> str:
    """Summary of the most recent Discovery scan results."""
    return _call("/v1/discovery/status/scan-results")


@mcp.tool()
def get_discovery_metrics(kind: str = "item") -> str:
    """Discovery counts: discovered items by type, or machines by operating system.

    Args:
        kind: 'item' for network item metrics, 'os' for operating system metrics.
    """
    if kind not in ("item", "os"):
        return json.dumps({"error": "kind must be 'item' or 'os'"})
    return _call(f"/v1/discovery/status/{kind}-metrics")


@mcp.tool()
def list_discovery_audit(take: int = 100, skip: int = 0, query_params: QueryParams = None) -> str:
    """Audit log of changes to discovery sources.

    Args:
        take:         Records to return (1-500).
        skip:         Records to skip, for paging.
        query_params: Extra query parameters as a JSON object string (optional).
    """
    return _paged("/v1/discovery-source/audit", take, skip, query_params)


# ---------------------------------------------------------------------------
# Discovered items
# ---------------------------------------------------------------------------


@mcp.tool()
def list_network_items(take: int = 100, skip: int = 0, item_type: Optional[str] = None,
                       managed: Optional[bool] = None, search_text: Optional[str] = None,
                       source_id: Optional[int] = None, operating_system: Optional[str] = None,
                       query_params: QueryParams = None) -> str:
    """Search discovered network items (computers, local/domain/service accounts, SSH keys).

    Each row shows the owning source, whether it is already managed (secretId / secretName) and password
    age. Secret values are never returned.

    Args:
        take:             Records to return (1-500).
        skip:             Records to skip, for paging.
        item_type:        Filter by type, e.g. Computer, ComputerAccount, DirectoryAccount, ServiceAccount, PublicKey.
        managed:          True for items already managed by a secret, False for unmanaged.
        search_text:      Text to match in the item name.
        source_id:        Only items from this discovery source.
        operating_system: Only items on hosts with this operating system.
        query_params:     Extra query parameters as a JSON object (or JSON string), optional.
    """
    try:
        params = _parse_params(query_params)
        for key, value in (("filter.itemType", item_type), ("filter.searchText", search_text),
                           ("filter.discoverySourceId", source_id), ("filter.operatingSystem", operating_system)):
            if value is not None:
                params[key] = value
        if managed is not None:
            params["filter.managed"] = "true" if managed else "false"
        return _paged("/v1/discovery/network/items", take, skip, params)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_network_item(item_type: str, item_id: int) -> str:
    """Get detail for one discovered network item.

    Args:
        item_type: computer, computer-account, directory-account, service-account or public-key.
        item_id:   Item ID from list_network_items.
    """
    if item_type not in NETWORK_ITEM_TYPES:
        return json.dumps({"error": f"item_type must be one of: {', '.join(NETWORK_ITEM_TYPES)}"})
    return _call(f"/v1/discovery/network/item/{item_type}/{int(item_id)}")


@mcp.tool()
def get_network_item_services(item_type: str, item_id: int) -> str:
    """Services (and the accounts they run as) on a discovered computer or directory account.

    Args:
        item_type: computer or directory-account.
        item_id:   Item ID from list_network_items.
    """
    if item_type not in ("computer", "directory-account"):
        return json.dumps({"error": "item_type must be 'computer' or 'directory-account'"})
    return _call(f"/v1/discovery/network/item/{item_type}/{int(item_id)}/services")


@mcp.tool()
def get_network_tree(query_params: QueryParams = None) -> str:
    """Network tree of discovered items (sources, domains, OUs) used by the Discovery UI.

    Args:
        query_params: Query parameters as a JSON object string (optional).
    """
    try:
        return _call("/v1/discovery/network/tree", _parse_params(query_params) or None)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Configuration: scanners, templates, rules
# ---------------------------------------------------------------------------


@mcp.tool()
def list_scanners(take: int = 100, skip: int = 0, query_params: QueryParams = None) -> str:
    """List discovery scanners (item scanners by type).

    Args:
        take:         Records to return (1-500).
        skip:         Records to skip, for paging.
        query_params: Extra query parameters as a JSON object string (optional).
    """
    return _paged("/v1/discovery/scanners", take, skip, query_params)


@mcp.tool()
def list_scan_templates() -> str:
    """Discovery scan templates."""
    return _call("/v1/discovery/scan-templates")


@mcp.tool()
def list_account_rules(take: int = 100, skip: int = 0, query_params: QueryParams = None) -> str:
    """Discovery account rules (which discovered accounts become secrets, and in which template/folder).

    Args:
        take:         Records to return (1-500).
        skip:         Records to skip, for paging.
        query_params: Extra query parameters as a JSON object string (optional).
    """
    return _paged("/v1/discovery/rules/accounts", take, skip, query_params)


@mcp.tool()
def get_account_rule(rule_id: int) -> str:
    """One discovery account rule in full. Password and key fields in the rule are redacted.

    Args:
        rule_id: Rule ID from list_account_rules.
    """
    return _call(f"/v1/discovery/rules/accounts/{int(rule_id)}")


@mcp.tool()
def list_dependency_rules(take: int = 100, skip: int = 0, query_params: QueryParams = None) -> str:
    """Discovery dependency rules.

    Args:
        take:         Records to return (1-500).
        skip:         Records to skip, for paging.
        query_params: Extra query parameters as a JSON object string (optional).
    """
    return _paged("/v1/discovery/rules/dependencies", take, skip, query_params)


# ---------------------------------------------------------------------------
# Secret names, roles, reports, unlimited admin audit
# ---------------------------------------------------------------------------


@mcp.tool()
def list_secret_names(search_text: Optional[str] = None, take: int = 100, skip: int = 0) -> str:
    """Look up secrets by name (id, name, folder, template only; never secret values).

    Args:
        search_text: Text to match in the secret name (optional).
        take:        Records to return (1-500).
        skip:        Records to skip, for paging.
    """
    extra = json.dumps({"filter.searchText": search_text}) if search_text else None
    return _paged("/v1/secrets/lookup", take, skip, extra)


@mcp.tool()
def list_roles(take: int = 100, skip: int = 0, query_params: QueryParams = None) -> str:
    """List Secret Server roles.

    Args:
        take:         Records to return (1-500).
        skip:         Records to skip, for paging.
        query_params: Extra query parameters as a JSON object string (optional).
    """
    return _paged("/v1/roles", take, skip, query_params)


@mcp.tool()
def get_role_permissions(role_id: int) -> str:
    """Permissions assigned to one role.

    Args:
        role_id: Role ID from list_roles.
    """
    return _call(f"/v1/roles/{int(role_id)}/permissions")


@mcp.tool()
def list_reports(take: int = 100, skip: int = 0, query_params: QueryParams = None) -> str:
    """List report definitions (not run results).

    Args:
        take:         Records to return (1-500).
        skip:         Records to skip, for paging.
        query_params: Extra query parameters as a JSON object string (optional).
    """
    return _paged("/v1/reports", take, skip, query_params)


@mcp.tool()
def list_unlimited_admin_audit(take: int = 100, skip: int = 0) -> str:
    """Audit log of Unlimited Admin Mode (who enabled it, when, and why).

    Args:
        take: Records to return (1-500).
        skip: Records to skip, for paging.
    """
    return _paged("/v1/configuration/unlimited-admin/audit", take, skip, None)

# ---------------------------------------------------------------------------
# Derived reports (combine the discovery calls above; no extra permissions)
# ---------------------------------------------------------------------------

PAGE_SIZE = 500
FETCH_CAP = 5000


def _fetch_all(path: str, params: Optional[dict] = None, cap: int = FETCH_CAP) -> tuple[list, int, bool]:
    """Page through a take/skip list endpoint. Returns (records, reported total, truncated)."""
    client = get_client()
    records: list = []
    total = 0
    skip = 0
    while skip < cap:
        page = client.get(path, {**(params or {}), "take": PAGE_SIZE, "skip": skip})
        total = page.get("total", 0)
        rows = page.get("records") or []
        records.extend(rows)
        skip += PAGE_SIZE
        if not rows or skip >= total:
            break
    return records, total, len(records) < total


def _account_view(row: dict) -> dict:
    """The fields of a network item row that matter for account reviews."""
    return {
        "name": row.get("fullName") or row.get("displayName"),
        "type": row.get("itemType"),
        "managed": row.get("isManaged"),
        "secretName": row.get("secretName"),
        "isLocalAdministrator": row.get("isLocalAdministrator"),
        "hasLocalAdminRights": row.get("hasLocalAdminRights"),
        "passwordLastSet": row.get("passwordLastSet"),
        "passwordExpirationStatus": row.get("passwordExpirationStatus"),
        "lastLogon": row.get("lastLogon"),
        "source": row.get("discoverySourceName"),
        "description": row.get("description") or None,
    }


@mcp.tool()
def host_account_summary(hostname: str) -> str:
    """Accounts and services for one discovered host: managed status, local-admin flags, password age,
    and which services or tasks run as which account.

    Args:
        hostname: Host name as discovery knows it (short name, case-insensitive).
    """
    try:
        wanted = hostname.strip().lower().split(".")[0]
        rows, _, truncated = _fetch_all("/v1/discovery/network/items", {"filter.searchText": wanted})
        host_rows = [r for r in rows if (r.get("hostName") or "").lower() == wanted
                     or (r.get("fullName") or "").lower().startswith(wanted + "\\")]
        computer = next((r for r in rows if r.get("itemType") == "Computer"
                         and (r.get("displayName") or "").lower().split(".")[0] == wanted), None)
        host_id = (computer or {}).get("networkItemId") or next(
            (r.get("hostId") for r in host_rows if r.get("hostId")), None)
        if host_id is None and not host_rows:
            return json.dumps({"error": f"no discovered host or accounts match '{hostname}'", "code": 404})
        services: list = []
        if host_id is not None:
            svc = get_client().get(f"/v1/discovery/network/item/computer/{int(host_id)}/services")
            services = [{"name": s.get("dependencyName"), "runsAs": s.get("computerAccountName"),
                         "secretName": s.get("secretName")} for s in (svc.get("records") or [])]
        accounts = [_account_view(r) for r in host_rows if r.get("itemType") != "Computer"]
        return _ok({
            "host": hostname, "hostId": host_id,
            "operatingSystem": next((r.get("hostEnvironment") for r in host_rows if r.get("hostEnvironment")), None),
            "accountCount": len(accounts),
            "unmanagedAccountCount": sum(1 for a in accounts if not a["managed"]),
            "accounts": accounts,
            "services": services,
            "truncated": truncated,
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def unmanaged_privileged_report(source_id: Optional[int] = None) -> str:
    """Discovered local accounts that are local administrators (or have local admin rights) and are not
    managed by any secret, grouped by host with operating system.

    Local-admin flags are only populated for some scan types, so data_quality shows how many scanned
    accounts have no flag at all; an empty result with a high unknown count is not a clean bill of health.

    Args:
        source_id: Only items from this discovery source (optional).
    """
    try:
        params: dict = {"filter.itemType": "ComputerAccount", "filter.managed": "false"}
        if source_id is not None:
            params["filter.discoverySourceId"] = int(source_id)
        rows, total, truncated = _fetch_all("/v1/discovery/network/items", params)
        hosts: dict = {}
        unknown = 0
        for r in rows:
            admin, rights = r.get("isLocalAdministrator"), r.get("hasLocalAdminRights")
            if admin is None and rights is None:
                unknown += 1
            if admin is True or rights is True:
                h = hosts.setdefault(r.get("hostName") or "unknown", {
                    "host": r.get("hostName"), "operatingSystem": r.get("hostEnvironment"), "accounts": []})
                h["accounts"].append(_account_view(r))
        ordered = sorted(hosts.values(), key=lambda h: (-len(h["accounts"]), str(h["host"])))
        return _ok({
            "unmanagedLocalAccountsScanned": len(rows), "reportedTotal": total, "truncated": truncated,
            "hostsWithUnmanagedPrivilegedAccounts": len(ordered),
            "data_quality": {"accountsWithNoLocalAdminFlag": unknown,
                             "note": "Directory and service accounts carry no local-admin flags and are not scanned here."},
            "hosts": ordered,
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def person_account_search(person: str, include_dependencies: bool = True) -> str:
    """Every discovered account whose name matches a person (for example jdoe, which also finds
    jdoe-server), plus scheduled tasks and services that run as such an account.

    Args:
        person:               Username or fragment to match (case-insensitive).
        include_dependencies: Also scan service-account items whose running account matches (slower).
    """
    try:
        needle = person.strip().lower()
        if len(needle) < 3:
            return json.dumps({"error": "person must be at least 3 characters"})
        rows, _, truncated = _fetch_all("/v1/discovery/network/items", {"filter.searchText": needle})
        accounts = [_account_view(r) for r in rows if r.get("itemType") != "Computer"]
        tasks: list = []
        deps_truncated = False
        if include_dependencies:
            deps, _, deps_truncated = _fetch_all("/v1/discovery/network/items", {"filter.itemType": "ServiceAccount"})
            for r in deps:
                if needle in (r.get("description") or "").lower():
                    tasks.append({"task": r.get("displayName"), "host": r.get("hostName"),
                                  "runsAs": r.get("description"), "type": r.get("scanItemTemplateName"),
                                  "managed": r.get("isManaged"), "secretName": r.get("secretName")})
        return _ok({"person": person, "accountCount": len(accounts), "accounts": accounts,
                    "dependencyCount": len(tasks), "dependencies": tasks,
                    "truncated": truncated or deps_truncated})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def rule_coverage_report() -> str:
    """Account rules compared with discovered accounts: what each rule matches, which rules overlap or
    duplicate each other, and how much of each account type no rule covers.

    matchedItems uses the items API's discoveryRuleId filter; treat it as indicative until confirmed
    against the Discovery UI.
    """
    try:
        rules, _, _ = _fetch_all("/v1/discovery/rules/accounts")
        report = []
        seen: dict = {}
        for r in rules:
            detail = get_client().get(f"/v1/discovery/rules/accounts/{int(r['ruleId'])}")
            matched = get_client().get("/v1/discovery/network/items",
                                       {"filter.discoveryRuleId": r["ruleId"], "take": 1, "skip": 0})
            entry = {
                "ruleId": r["ruleId"], "name": r.get("ruleName"), "active": r.get("isActive"),
                "source": r.get("discoverySourceName"), "ou": detail.get("organizationUnitName"),
                "accountNameContains": detail.get("accountNameContains"),
                "computerNameContains": detail.get("computerNameContains"),
                "operatingSystemContains": detail.get("operatingSystemContains"),
                "secretTemplate": r.get("secretTemplateName"), "folder": r.get("folderName"),
                "matchedItems": matched.get("total"),
            }
            key = (entry["source"], entry["ou"], entry["accountNameContains"],
                   entry["computerNameContains"], entry["secretTemplate"], entry["folder"])
            entry["duplicateOf"] = seen.get(key)
            seen.setdefault(key, r["ruleId"])
            report.append(entry)
        metrics = get_client().get("/v1/discovery/status/item-metrics")
        return _ok({
            "ruleCount": len(report), "rules": report,
            "uncoveredByType": [{"type": m.get("itemTypeDisplayName"), "managed": m.get("managedCount"),
                                 "notManaged": m.get("notManagedCount")}
                                for m in metrics.get("itemMetrics", [])],
        })
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------


@mcp.tool()
def api_get(path: str, query_params: QueryParams = None) -> str:
    """GET any other allow-listed Secret Server API path not covered by a dedicated tool.

    Allowed areas: discovery, secrets/lookup, roles, reports and the unlimited-admin audit. Password and key fields are redacted in the response.

    Args:
        path:         API path, e.g. '/v1/discovery/scan-types'.
        query_params: Query parameters as a JSON object string, e.g. '{"take": 10}' (optional).
    """
    try:
        return _ok(get_client().get(path, _parse_params(query_params) or None))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)

# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
# Contributor: Caleb A. Morrow - 2026-10-28 - dict query_params, list filters, include_inactive, source fallback, derived account reports
