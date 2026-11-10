# Authored by Caleb A. Morrow
"""
Mend MCP Server (read-only)

Exposes the Mend platform (SCA dependencies, SAST code, container images, AI, red teaming, reports,
administration) as MCP tools, acting as the shared service account. Read-only by construction: the
REST client issues only GET requests to the GET operations in Mend's OpenAPI description
(endpoints.json). `api_get` reaches every one of those endpoints; the named tools are shortcuts for
the common ones. Two tools forward to Mend's own hosted MCP assistants (dependency lookup, SAST
review), which only analyse what you send them.

Configuration via environment variables:
  MEND_USER_KEY   - Mend user key for the service account (required)
  MEND_USER_EMAIL - Mend service account email (required)
  MEND_ORG_UUID   - Mend organization UUID (required)
  MEND_MCP_URL    - Mend hosted MCP endpoint (default: https://saas.whitesourcesoftware.com/mcp)
  MEND_TIMEOUT    - Request timeout in seconds (default: 60)
"""

import json
import logging
import os
import re
import sys
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import TEMPLATES, MendClient, MendError, upstream_tools_call
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("Mend")

_client: Optional[MendClient] = None
UPSTREAM_MCP = os.environ.get("MEND_MCP_URL", "https://saas.whitesourcesoftware.com/mcp")
UUID = re.compile(r"[0-9A-Za-z-]{8,64}")


def get_client() -> MendClient:
    global _client
    if _client is None:
        key = os.environ.get("MEND_USER_KEY", "")
        email = os.environ.get("MEND_USER_EMAIL", "").strip()
        org = os.environ.get("MEND_ORG_UUID", "").strip()
        if not key or not email or not org:
            raise RuntimeError("MEND_USER_KEY, MEND_USER_EMAIL and MEND_ORG_UUID are required")
        _client = MendClient(key, email, org, float(os.environ.get("MEND_TIMEOUT", "60")))
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, MendError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


def _uuid(value: str, name: str) -> str:
    value = str(value).strip()
    if not UUID.fullmatch(value):
        raise ValueError(f"{name} must be a Mend UUID")
    return value


def _page(limit: int, cursor: Optional[str], extra: Optional[dict]) -> dict:
    params: dict = {"limit": max(1, min(limit, 1000))}
    if cursor:
        params["cursor"] = cursor
    params.update(extra or {})
    return params


def _get(path: str, params: Optional[dict] = None) -> str:
    return _ok(get_client().get(path, params))


# ---------------------------------------------------------------------------
# Connection and discovery
# ---------------------------------------------------------------------------


@mcp.tool()
def get_token_status() -> str:
    """Check that the Mend service account can authenticate. Never returns the token."""
    try:
        return _ok(get_client().token_status())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_endpoints(search: Optional[str] = None) -> str:
    """List the Mend REST GET endpoints reachable through api_get, with their query parameters.

    Args:
        search: Optional text to filter on path, summary or tag (case-insensitive).
    """
    needle = (search or "").lower()
    rows = [{"path": e["path"], "summary": e["summary"], "tag": e["tag"], "query": e["query"]}
            for _, e in TEMPLATES
            if not needle or needle in (e["path"] + e["summary"] + e["tag"]).lower()]
    return _ok(rows)


@mcp.tool()
def api_get(path: str, params: Optional[dict] = None) -> str:
    """GET any Mend REST API 3.0 endpoint on the allow-list (see list_endpoints). Read-only.

    Args:
        path: Path after /api/v3.0, for example /orgs/{orgUuid}/projects (the {orgUuid} placeholder is
            filled in automatically) or /projects/<projectUuid>/dependencies/findings/security.
        params: Optional query parameters, for example {"limit": 100, "cursor": "..."}.
            List responses page with additionalData.paging.next (pass its cursor back).
    """
    try:
        return _get(path, params)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Organization, applications, projects, scans
# ---------------------------------------------------------------------------


@mcp.tool()
def list_applications(limit: int = 100, cursor: Optional[str] = None, params: Optional[dict] = None) -> str:
    """Mend applications (a group of projects) in the organization."""
    try:
        return _get("/orgs/{orgUuid}/applications", _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_application_totals(from_date: str, to_date: str, params: Optional[dict] = None) -> str:
    """Organization-wide application totals for a date range (dates are yyyy-MM-dd)."""
    try:
        return _get("/orgs/{orgUuid}/applications/summaries/totals",
                    {"fromDate": from_date, "toDate": to_date, **(params or {})})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_projects(limit: int = 100, cursor: Optional[str] = None, populate_applications: bool = True,
                  exclude_inactive: bool = False, params: Optional[dict] = None) -> str:
    """Mend projects in the organization (name, UUID, application, last scan)."""
    try:
        extra = {"populateApplications": str(populate_applications).lower(),
                 "excludeInactiveProjects": str(exclude_inactive).lower(), **(params or {})}
        return _get("/orgs/{orgUuid}/projects", _page(limit, cursor, extra))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_project_totals(from_date: str, to_date: str, params: Optional[dict] = None) -> str:
    """Organization-wide project totals for a date range (dates are yyyy-MM-dd)."""
    try:
        return _get("/orgs/{orgUuid}/projects/summaries/totals",
                    {"fromDate": from_date, "toDate": to_date, **(params or {})})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_project_totals_by_date(from_date: str, to_date: str, params: Optional[dict] = None) -> str:
    """Project totals grouped by date, for trends (dates are yyyy-MM-dd)."""
    try:
        return _get("/orgs/{orgUuid}/projects/summaries/total/date",
                    {"fromDate": from_date, "toDate": to_date, **(params or {})})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_project_scans(project_uuid: str, limit: int = 50, cursor: Optional[str] = None,
                       params: Optional[dict] = None) -> str:
    """Scan history for a project."""
    try:
        return _get(f"/orgs/{{orgUuid}}/projects/{_uuid(project_uuid, 'project_uuid')}/scans",
                    _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_scan_summary(project_uuid: str, scan_uuid: str) -> str:
    """Summary (finding counts, status) of one scan."""
    try:
        return _get(f"/orgs/{{orgUuid}}/projects/{_uuid(project_uuid, 'project_uuid')}"
                    f"/scans/{_uuid(scan_uuid, 'scan_uuid')}/summary")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_project_violations(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                            params: Optional[dict] = None) -> str:
    """Policy-violating findings for a project."""
    try:
        return _get(f"/orgs/{{orgUuid}}/projects/{_uuid(project_uuid, 'project_uuid')}/violations",
                    _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Dependencies (SCA)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_dependency_findings(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                             params: Optional[dict] = None) -> str:
    """SCA security findings (CVEs, severity, fix versions) for a project."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/dependencies/findings/security",
                    _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_dependency_findings_by_library(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                                        params: Optional[dict] = None) -> str:
    """SCA findings grouped by vulnerable library (one row per library)."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/dependencies/findings/security/groupBy/library",
                    _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_dependency_findings_by_root_library(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                                             params: Optional[dict] = None) -> str:
    """SCA findings grouped by the top-level (direct) library that pulls the vulnerable one in."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/dependencies/findings/security/groupBy/rootLibrary",
                    _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_project_libraries(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                           params: Optional[dict] = None) -> str:
    """Libraries (inventory) used by a project."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/dependencies/libraries",
                    _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_library_licenses(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                          params: Optional[dict] = None) -> str:
    """Due-diligence and license information for a project's libraries."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/dependencies/libraries/licenses",
                    _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_zero_day_events(limit: int = 50, cursor: Optional[str] = None, params: Optional[dict] = None) -> str:
    """Zero-day vulnerability events Mend has published (params: fromDate, toDate)."""
    try:
        return _get("/orgs/{orgUuid}/dependencies/events/zeroday", _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_zero_day_findings(event_uuid: str, limit: int = 100, cursor: Optional[str] = None) -> str:
    """Libraries in this organization affected by one zero-day event."""
    try:
        return _get(f"/orgs/{{orgUuid}}/dependencies/events/zeroday/{_uuid(event_uuid, 'event_uuid')}/findings",
                    _page(limit, cursor, None))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Code (SAST), container images, AI
# ---------------------------------------------------------------------------


@mcp.tool()
def list_code_findings(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                       params: Optional[dict] = None) -> str:
    """SAST (code) findings for a project."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/code/findings", _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_code_finding(project_uuid: str, finding_uuid: str) -> str:
    """One SAST finding with its data-flow detail."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/code/findings/{_uuid(finding_uuid, 'finding_uuid')}")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_image_findings(project_uuid: str, kind: str = "security", limit: int = 100, cursor: Optional[str] = None,
                        params: Optional[dict] = None) -> str:
    """Container image scan results for a project from the latest scan.

    Args:
        kind: security (vulnerabilities), secrets, or packages.
    """
    try:
        if kind not in ("security", "secrets", "packages"):
            raise ValueError("kind must be security, secrets or packages")
        suffix = "packages" if kind == "packages" else f"findings/{kind}"
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/images/{suffix}", _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_ai_vulnerabilities(project_uuid: str, limit: int = 100, cursor: Optional[str] = None,
                            params: Optional[dict] = None) -> str:
    """AI-related vulnerabilities for a project (models, technologies, implementation findings via api_get)."""
    try:
        return _get(f"/projects/{_uuid(project_uuid, 'project_uuid')}/ai/vulnerabilities", _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Reports, workflows, administration
# ---------------------------------------------------------------------------


@mcp.tool()
def list_reports(limit: int = 50, cursor: Optional[str] = None) -> str:
    """Reports already generated in the organization. (Creating reports is not exposed: it is a write.)"""
    try:
        return _get("/orgs/{orgUuid}/reports", _page(limit, cursor, None))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_report_status(report_uuid: str) -> str:
    """Status of a generated report."""
    try:
        return _get(f"/orgs/{{orgUuid}}/reports/{_uuid(report_uuid, 'report_uuid')}")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_workflows(limit: int = 100, cursor: Optional[str] = None) -> str:
    """Automation workflows in the organization."""
    try:
        return _get("/orgs/{orgUuid}/automation/workflows", _page(limit, cursor, None))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_labels(limit: int = 100, cursor: Optional[str] = None) -> str:
    """Organization labels."""
    try:
        return _get("/orgs/{orgUuid}/labels", _page(limit, cursor, None))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_integrations(limit: int = 100, cursor: Optional[str] = None) -> str:
    """Configured integrations (SCM, CI, ticketing)."""
    try:
        return _get("/orgs/{orgUuid}/integrations", _page(limit, cursor, None))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_activity_logs(limit: int = 100, cursor: Optional[str] = None, params: Optional[dict] = None) -> str:
    """Organization activity (audit) log. params: startDate, days, engineType."""
    try:
        return _get("/orgs/{orgUuid}/activity-logs", _page(limit, cursor, params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_groups(limit: int = 100, cursor: Optional[str] = None) -> str:
    """Administration groups. NOTE: the service account's role may return 403."""
    try:
        return _get("/orgs/{orgUuid}/groups", _page(limit, cursor, None))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_users(limit: int = 100, cursor: Optional[str] = None) -> str:
    """Organization users. NOTE: the service account's role may return 403."""
    try:
        return _get("/orgs/{orgUuid}/users", _page(limit, cursor, None))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Mend's hosted MCP assistants (analyse what you send; nothing is stored in Mend)
# ---------------------------------------------------------------------------


def _upstream(name: str, arguments: dict) -> str:
    try:
        client = get_client()
        headers = {"X-UserKey": client.user_key, "X-UserEmail": client.email, "X-OrgId": client.org_uuid}
        return _ok(upstream_tools_call(UPSTREAM_MCP, headers, name, arguments))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def check_dependency(library_name: str = "", library_version: str = "", language: str = "",
                     group_id: str = "", packages: str = "") -> str:
    """Check libraries for known vulnerabilities, license and fix versions (Mend's dependencies assistant).

    Single package: library_name, library_version and language. Bulk: packages as a JSON array.

    Args:
        library_name: Package name, for example "lodash".
        library_version: Version to check.
        language: Ecosystem: JAVA, RUBY, PYTHON, NPM, NUGET, GO, PHP, COCOAPODS, HEX, R, OPAM, CRATE, CABAL, SWIFT.
        group_id: Maven group ID (Java only).
        packages: Bulk mode, JSON array: [{"library":"name","version":"1.0.0","language":"NPM","groupId":"optional"}].
    """
    arguments = {"library_name": library_name, "library_version": library_version, "language": language,
                 "groupId": group_id, "packages": packages}
    return _upstream("mend-dependencies-assistant", {k: v for k, v in arguments.items() if v})


@mcp.tool()
def review_code_change(file_path: str, modified_method: str, modified_file_content: str) -> str:
    """Review a code change for security weaknesses (Mend's SAST code-security assistant).

    The code you pass is sent to Mend for analysis. Do not send secrets.
    """
    return _upstream("mend-code-security-assistant", {
        "file_path": file_path, "modified_method": modified_method,
        "modified_file_content": modified_file_content})


if __name__ == "__main__":
    run_server(mcp)

# Authored by Caleb A. Morrow
