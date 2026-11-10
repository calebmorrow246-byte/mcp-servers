"""
Windows read-only MCP Server (WinRM + JEA)

Reads diagnostics from Windows servers through the constrained "ReadOnly" JEA endpoint
(role definition not included in this repo). The endpoint exposes only nine Get-Ro*
functions in NoLanguage mode, so this server cannot write, start, stop or run arbitrary commands.
Only servers listed in servers.json can be queried.

Configuration via environment variables:
  WINRM_USERNAME     - Domain service account allowed on the endpoint, DOMAIN\\name (required)
  WINRM_PASSWORD     - Its password (required)
  WINRM_SERVERS_FILE - Allow-list file (default: servers.json next to this script)
  WINRM_PORT         - WinRM HTTP port (default: 5985)
  WINRM_TIMEOUT      - Per-call timeout in seconds (default: 120)
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

import kb
from client import WinRmClient, WinRmError, from_env, hours_ago
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("Windows-ReadOnly")

_client: Optional[WinRmClient] = None

MAX_ROWS = 500


def get_client() -> WinRmClient:
    global _client
    if _client is None:
        _client = from_env(Path(__file__).resolve().parent)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    return json.dumps({"error": str(exc)})


def _run(server: str, function: str, parameters: Optional[dict[str, Any]] = None, limit: int = MAX_ROWS) -> str:
    try:
        rows = get_client().invoke(server, function, parameters)
        return _ok({"server": server.strip().lower(), "total": len(rows), "truncated": len(rows) > limit,
                    "results": rows[:limit]})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


@mcp.tool()
def list_servers() -> str:
    """
    List the Windows servers this MCP is allowed to query (the allow-list in servers.json), with a
    note on why each is there. Servers need the ReadOnly JEA endpoint deployed before they can be added.
    """
    try:
        return _ok({"servers": [{"name": n, "note": note} for n, note in sorted(get_client().servers.items())]})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@mcp.tool()
def get_os_info(server: str) -> str:
    """
    OS caption, version/build, last boot time, uptime in days and whether a reboot is pending.

    Args:
        server: Server FQDN from list_servers.
    """
    return _run(server, "Get-RoOsInfo")


@mcp.tool()
def get_service_info(server: str, name: str = "*") -> str:
    """
    Windows services: state, start mode, run-as account and ImagePath. UnquotedPath is true when the
    ImagePath has spaces and no quotes (QID 105484, service path hijack).

    Args:
        server: Server FQDN from list_servers.
        name:   Service name or wildcard, e.g. 'CertSvc' or 'W3*' (default: all services).
    """
    return _run(server, "Get-RoServiceInfo", {"Name": name})


@mcp.tool()
def get_installed_software(server: str, name: str = "*") -> str:
    """
    Installed programs (name, version, publisher, install date) from both the 64-bit and 32-bit
    uninstall registry views.

    Args:
        server: Server FQDN from list_servers.
        name:   Display name or wildcard, e.g. 'Microsoft .NET*' (default: everything).
    """
    return _run(server, "Get-RoInstalledSoftware", {"Name": name})


@mcp.tool()
def get_registry_value(server: str, path: str) -> str:
    """
    Read every value under one registry key. Only an allow-listed set of HKLM keys is readable
    (Windows NT\\CurrentVersion, .NETFramework, ASP.NET, Uninstall, Cryptography, Lsa,
    SecurityProviders, Services\\<name>). Product-key blobs are never returned.

    Args:
        server: Server FQDN from list_servers.
        path:   Key path, e.g. 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\SCHANNEL'.
    """
    return _run(server, "Get-RoRegistryValue", {"Path": path})


@mcp.tool()
def get_file_info(server: str, path: str) -> str:
    """
    Version, size, last write time, SHA-256 and Authenticode signature of one file. Never returns
    contents. Only files under Program Files, Program Files (x86), System32, C:\\inetpub or
    ProgramData are allowed; wildcards are rejected.

    Args:
        server: Server FQDN from list_servers.
        path:   Full file path, e.g. 'C:\\Program Files\\dotnet\\dotnet.exe'.
    """
    return _run(server, "Get-RoFileInfo", {"Path": path})


# ---------------------------------------------------------------------------
# Event logs
# ---------------------------------------------------------------------------


@mcp.tool()
def get_event_log(
    server: str,
    log_name: str = "System",
    max_level: int = 3,
    hours_back: int = 24,
    event_ids: Optional[list[int]] = None,
    max_events: int = 50,
) -> str:
    """
    Recent events from an allow-listed log. Messages are cut at 500 characters. Look back at most 30 days.
    For correlating one event ID with scan or change windows use get_event_times instead (timestamps only,
    up to 5000 events, much smaller).

    Args:
        server:     Server FQDN from list_servers.
        log_name:   System, Application, Setup, Microsoft-Windows-WinRM/Operational or
                    Microsoft-Windows-Windows Defender/Operational.
        max_level:  Highest level number to include: 1 Critical, 2 Error, 3 Warning, 4 Information, 5 Verbose
                    (default 3 = critical, error and warning).
        hours_back: How far back to look, 1-720 hours (default 24).
        event_ids:  Only these event IDs (optional).
        max_events: Maximum events, 1-200 (default 50).
    """
    try:
        if not 1 <= hours_back <= 720:
            raise WinRmError("hours_back must be between 1 and 720 (30 days)")
        parameters: dict[str, Any] = {
            "LogName": log_name, "Level": max_level,
            "StartTime": hours_ago(hours_back), "MaxEvents": max_events,
        }
        if event_ids:
            parameters["Id"] = [int(i) for i in event_ids]
        return _run(server, "Get-RoEventLog", parameters)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_event_summary(
    server: str,
    log_name: str = "System",
    max_level: int = 2,
    days_back: int = 30,
    top: int = 30,
) -> str:
    """
    Events grouped by provider, event ID and level, with count, first/last time seen and one trimmed
    sample message per group, most frequent first. Use this (not get_event_log) for the SQM
    "Check Event Viewer Logs" item: it covers up to 20000 events, so a noisy server is not cut off.
    A clean server returns one row with Count 0. EventsScanned/GroupsTotal give the whole-scan totals;
    ScanLimitReached true means older events were not counted.

    Args:
        server:     Server FQDN from list_servers.
        log_name:   System, Application, Setup, Microsoft-Windows-WinRM/Operational or
                    Microsoft-Windows-Windows Defender/Operational (default System).
        max_level:  1 Critical, 2 Error, 3 Warning (default 2 = critical and error).
        days_back:  1-30 days (default 30).
        top:        Maximum groups, 1-100 (default 30).
    """
    return _run(server, "Get-RoEventSummary",
                {"LogName": log_name, "MaxLevel": max_level, "DaysBack": days_back, "Top": top})


@mcp.tool()
def get_event_times(server: str, event_id: int, log_name: str = "System", max_level: int = 2,
                    days_back: int = 30, max_events: int = 2000) -> str:
    """
    UTC timestamps of every event with one ID, and nothing else: no messages. Built for checking whether an
    event only ever happens inside known windows, such as Qualys scan windows (the SQM Qualys rule). Returns
    the count, whether the newest-N read hit the limit (truncatedAtMax), and timesUtc as ISO strings.

    Args:
        server:     Server FQDN from list_servers.
        event_id:   The event ID, e.g. 36874.
        log_name:   System, Application, Setup, Microsoft-Windows-WinRM/Operational or
                    Microsoft-Windows-Windows Defender/Operational (default System).
        max_level:  Highest level to include, 1-4 (default 2 = critical and error).
        days_back:  1-30 days (default 30).
        max_events: Newest N events to read, 1-5000 (default 2000).
    """
    return _run(server, "Get-RoEventTimes",
                {"LogName": log_name, "Id": event_id, "MaxLevel": max_level, "DaysBack": days_back, "MaxEvents": max_events})


@mcp.tool()
def triage_events(server: str, days_back: int = 30, max_level: int = 2, top: int = 30) -> str:
    """
    One-call Event Viewer triage for a server (the SQM "Check Event Viewer Logs" item): groups System and
    Application events (Critical + Error by default) and matches every group against the known-events
    knowledge base. Each group comes back with status matched / partial / unknown:
      matched - every returned message variant has a KB entry (priority, fix, root cause, tags);
      partial - some variants matched, the rest need assessing;
      unknown - no KB entry: assess it using get_triage_guidance.
    kb.benign true means the KB treats it as noise. kb.needsScanCorrelation true means it is benign ONLY if
    its timing matches Qualys scan windows (the caller must check). kb.reviewed false means the KB entry was
    drafted but not yet reviewed by a person. A clean log returns no groups. A log that could not be read is
    reported under logErrors and must never be treated as clean.

    Args:
        server:     Server FQDN from list_servers.
        days_back:  1-30 days (default 30).
        max_level:  1 Critical, 2 Error, 3 Warning (default 2).
        top:        Maximum groups per log, 1-100 (default 30).
    """
    try:
        client = get_client()
        logs, log_errors, groups = [], {}, []
        for log_name in ("System", "Application"):
            try:
                rows = client.invoke(server, "Get-RoEventSummary",
                                     {"LogName": log_name, "MaxLevel": max_level, "DaysBack": days_back, "Top": top})
            except Exception as exc:
                log_errors[log_name] = str(exc)
                continue
            real = [r for r in rows if r.get("Count")]
            first = rows[0] if rows else {}
            logs.append({"log": log_name, "eventsScanned": first.get("EventsScanned", 0),
                         "groupsTotal": first.get("GroupsTotal", 0),
                         "scanLimitReached": bool(first.get("ScanLimitReached", False))})
            groups.extend(kb.classify_group(r) for r in real)
        counts = {s: sum(1 for g in groups if g["status"] == s) for s in ("matched", "partial", "unknown")}
        return _ok({
            "server": server.strip().lower(), "daysBack": days_back, "maxLevel": max_level,
            "logs": logs, "logErrors": log_errors, "summary": {"groups": len(groups), **counts},
            "groups": groups,
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_known_events(scope: str = "any", source: Optional[str] = None, event_id: Optional[int] = None,
                      tag: Optional[str] = None, reviewed: Optional[bool] = None) -> str:
    """
    Query the known-events knowledge base (the same entries triage_events matches against). Filters are
    optional and combined with AND.

    Args:
        scope:    server, workstation, both or any (default any; 'server' also returns scope 'both').
        source:   Event source/provider, partial match (e.g. 'Schannel').
        event_id: Exact event ID.
        tag:      A tag, e.g. 'benign' or 'qualys'.
        reviewed: true for human-reviewed entries only, false for unreviewed drafts only.
    """
    try:
        entries = kb.list_entries(scope, source, event_id, tag, reviewed)
        return _ok({"total": len(entries), "entries": entries})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_triage_guidance() -> str:
    """
    The guidance for assessing events the knowledge base does not recognise: what to write (fix, root
    cause, priority H/M/L), how to weigh counts and timing, and how new entries get into the KB.
    """
    try:
        return kb.GUIDANCE_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# IIS
# ---------------------------------------------------------------------------


@mcp.tool()
def get_iis_bindings(server: str) -> str:
    """
    IIS site bindings: site, state, protocol, address:port:host header and SSL flags.

    Args:
        server: Server FQDN from list_servers.
    """
    return _run(server, "Get-RoIisBinding")


@mcp.tool()
def get_iis_auth(server: str, location: str) -> str:
    """
    Authentication and SSL settings for one IIS location: Windows and anonymous auth, Extended
    Protection mode (None/Allow/Require), Windows auth providers and the SSL requirement. Use it for
    NTLM relay findings (QID 91798, ADV210003 / KB5005413).

    Args:
        server:   Server FQDN from list_servers.
        location: Site and path, e.g. 'Default Web Site/certsrv'.
    """
    return _run(server, "Get-RoIisAuth", {"Location": location})


@mcp.tool()
def get_iis_log_summary(server: str, uri_prefix: str, days: int = 7, top: int = 50) -> str:
    """
    Who has been requesting a URL prefix, from the IIS logs: counts by client IP, user, user agent
    and status, with the last time seen. Never returns raw log lines. Use it to check whether a
    legacy endpoint (e.g. /certsrv) is still in use before changing its authentication.

    Args:
        server:     Server FQDN from list_servers.
        uri_prefix: Request path prefix starting with '/', e.g. '/certsrv'.
        days:       Days of logs to scan, 1-30 (default 7).
        top:        Maximum groups to return, 1-200 (default 50).
    """
    return _run(server, "Get-RoIisLogSummary", {"UriPrefix": uri_prefix, "Days": days, "Top": top})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
