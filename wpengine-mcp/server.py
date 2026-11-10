"""
WPEngine MCP Server

Exposes the WP Engine Hosting Platform API (read-only, plus two approved non-destructive write
tools) and per-install SFTP troubleshooting tools.

WPEngine's account-level API credential has no read-only scope of its own — access is all-or-nothing
per API user. The read-only guarantee for this server is enforced entirely by which tool functions
below are wired up to call the REST API, not by the credential. Review this file's tool list, not
just test results, when auditing what this server can do.

Configuration via environment variables:
  WPENGINE_API_USER      - WPEngine API user/access ID (required)
  WPENGINE_API_PASSWORD  - WPEngine API password (required)
  WPENGINE_TIMEOUT       - Request timeout in seconds (default: 30)

SFTP tools read per-install credentials on demand from Windows Credential Manager
(target: 'WPEngine SFTP <install-name>') rather than from environment variables — see sftp_tools.py.
"""

import json
import logging
import os
import sys
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import WPEngineClient, WPEngineError
from mcp_transport import run_server
import sftp_tools
from sftp_tools import WPEngineSftpError

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("WPEngine")

_client: Optional[WPEngineClient] = None


def get_client() -> WPEngineClient:
    global _client
    if _client is None:
        username = os.environ.get("WPENGINE_API_USER", "").strip()
        password = os.environ.get("WPENGINE_API_PASSWORD", "").strip()
        timeout = float(os.environ.get("WPENGINE_TIMEOUT", "30"))
        if not username or not password:
            raise RuntimeError("WPENGINE_API_USER and WPENGINE_API_PASSWORD environment variables are required")
        _client = WPEngineClient(username, password, timeout)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, (WPEngineError, WPEngineSftpError)):
        return json.dumps({"error": str(exc)})
    return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Installs & Sites
# ---------------------------------------------------------------------------


@mcp.tool()
def list_installs(limit: int = 100, offset: int = 0) -> str:
    """
    List WPEngine installs (WordPress sites/environments) on the account.

    Args:
        limit:  Records to return (default 100).
        offset: Pagination offset (default 0).
    """
    try:
        c = get_client()
        data = c.get("/installs", {"limit": limit, "offset": offset})
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_install(install_id: str) -> str:
    """
    Get full details for a specific install.

    Args:
        install_id: WPEngine install ID or name (from list_installs).
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Backups (create_backup is the one approved write tool in this group)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_backups(install_id: str, limit: int = 100, offset: int = 0) -> str:
    """
    List backups for an install.

    Args:
        install_id: WPEngine install ID or name.
        limit:      Records to return (default 100).
        offset:     Pagination offset (default 0).
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}/backups", {"limit": limit, "offset": offset})
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def create_backup(install_id: str, description: Optional[str] = None) -> str:
    """
    Trigger a new backup for an install. Additive/non-destructive — approved as this server's
    one exception to read-only, matching the "always backup before changes" convention.

    Args:
        install_id:  WPEngine install ID or name.
        description: Optional note for the backup (e.g. "before plugin update").
    """
    try:
        c = get_client()
        body: dict = {}
        if description:
            body["description"] = description
        data = c.post(f"/installs/{install_id}/backups", body)
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Cache (purge_cache is the second approved write tool)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_cache_exclusions(install_id: str) -> str:
    """
    List cache exclusions configured for an install.

    Args:
        install_id: WPEngine install ID or name.
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}/cache_exclusions")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def purge_cache(install_id: str) -> str:
    """
    Purge an install's cache. Non-destructive — the cache simply rebuilds on next request.
    Approved as this server's second exception to read-only (same category as create_backup).

    Args:
        install_id: WPEngine install ID or name.
    """
    try:
        c = get_client()
        data = c.post(f"/installs/{install_id}/purge_cache")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------


@mcp.tool()
def list_domains(install_id: str) -> str:
    """
    List domains assigned to an install.

    Args:
        install_id: WPEngine install ID or name.
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}/domains")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_domain(install_id: str, domain_id: str) -> str:
    """
    Get details for a specific domain on an install.

    Args:
        install_id: WPEngine install ID or name.
        domain_id:  Domain ID (from list_domains).
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}/domains/{domain_id}")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_domain_certificate(install_id: str, domain_id: str) -> str:
    """
    Get SSL certificate status for a domain — for expiry monitoring.

    Args:
        install_id: WPEngine install ID or name.
        domain_id:  Domain ID (from list_domains).
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}/domains/{domain_id}/ssl_certificate")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_domain_status_report(install_id: str, report_id: str) -> str:
    """
    Retrieve a domain status/verification report by ID.

    Args:
        install_id: WPEngine install ID or name.
        report_id:  Report ID (returned when a status check was previously submitted).
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}/domains/check_status/{report_id}")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# SSH keys (listing only — no add/delete)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_ssh_keys() -> str:
    """List SSH public keys registered on the WPEngine account (read-only; no add/delete tool)."""
    try:
        c = get_client()
        data = c.get("/ssh_keys")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Accounts & Users
# ---------------------------------------------------------------------------


@mcp.tool()
def list_accounts(limit: int = 100, offset: int = 0) -> str:
    """
    List WPEngine accounts visible to this API credential.

    Args:
        limit:  Records to return (default 100).
        offset: Pagination offset (default 0).
    """
    try:
        c = get_client()
        data = c.get("/accounts", {"limit": limit, "offset": offset})
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_account(account_id: str) -> str:
    """
    Get details for a specific account.

    Args:
        account_id: WPEngine account ID (from list_accounts).
    """
    try:
        c = get_client()
        data = c.get(f"/accounts/{account_id}")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_account_users(account_id: str, limit: int = 100, offset: int = 0) -> str:
    """
    List users with access to an account — for access audits.

    Args:
        account_id: WPEngine account ID.
        limit:      Records to return (default 100).
        offset:     Pagination offset (default 0).
    """
    try:
        c = get_client()
        data = c.get(f"/accounts/{account_id}/account_users", {"limit": limit, "offset": offset})
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Usage & status metrics
# ---------------------------------------------------------------------------


@mcp.tool()
def get_account_usage_limits(account_id: str) -> str:
    """
    Get usage limits for an account.

    Args:
        account_id: WPEngine account ID.
    """
    try:
        c = get_client()
        data = c.get(f"/accounts/{account_id}/limits")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_account_usage_metrics(account_id: str) -> str:
    """
    Get usage metrics (performance data across installs) for an account.

    Args:
        account_id: WPEngine account ID.
    """
    try:
        c = get_client()
        data = c.get(f"/accounts/{account_id}/usage")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_account_usage_insights(account_id: str) -> str:
    """
    Get usage insights (consumption patterns) for an account.

    Args:
        account_id: WPEngine account ID.
    """
    try:
        c = get_client()
        data = c.get(f"/accounts/{account_id}/usage/insights")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_account_usage_summary(account_id: str) -> str:
    """
    Get a usage summary for an account.

    Args:
        account_id: WPEngine account ID.
    """
    try:
        c = get_client()
        data = c.get(f"/accounts/{account_id}/usage/summary")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_install_usage_metrics(install_id: str) -> str:
    """
    Get per-install usage/consumption metrics.

    Args:
        install_id: WPEngine install ID or name.
    """
    try:
        c = get_client()
        data = c.get(f"/installs/{install_id}/usage")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_api_status() -> str:
    """Get the current status of the WP Engine Hosting Platform API itself."""
    try:
        c = get_client()
        data = c.get("/status")
        return _ok(data)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# SFTP troubleshooting tools (read-only; per-install shared service credentials)
# ---------------------------------------------------------------------------


@mcp.tool()
def sftp_list_files(install_id: str, path: str = "wp-content") -> str:
    """
    List files/directories under a path on an install's filesystem via SFTP.

    Args:
        install_id: WPEngine install name (must match a 'WPEngine SFTP <install>' credential).
        path:       Remote directory path (default 'wp-content').
    """
    try:
        return _ok(sftp_tools.list_files(install_id, path))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sftp_read_file(install_id: str, path: str, max_bytes: int = 262144) -> str:
    """
    Read a text file from an install's filesystem via SFTP. Never returns wp-config.php
    (contains the DB password and auth keys in plaintext) regardless of the path given.

    Args:
        install_id: WPEngine install name.
        path:       Remote file path (e.g. 'wp-content/themes/mytheme/functions.php').
        max_bytes:  Size cap in bytes (default 256 KB); larger files are truncated.
    """
    try:
        return _ok(sftp_tools.read_file(install_id, path, max_bytes))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sftp_tail_log(install_id: str, path: str = "wp-content/debug.log", lines: int = 200) -> str:
    """
    Tail the last N lines of a log file via SFTP — the main troubleshooting use case.

    Args:
        install_id: WPEngine install name.
        path:       Remote log file path (default 'wp-content/debug.log').
        lines:      Number of lines to return from the end of the file (default 200, max 2000).
    """
    try:
        return _ok(sftp_tools.tail_log(install_id, path, lines))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sftp_hash_file(install_id: str, path: str) -> str:
    """
    Compute the SHA-256 hash of a remote file via SFTP (streamed, client-side) — for comparing
    against known-good file hashes to spot tampering/malware. Never hashes wp-config.php.

    Args:
        install_id: WPEngine install name.
        path:       Remote file path.
    """
    try:
        return _ok(sftp_tools.hash_file(install_id, path))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sftp_find_recent_files(install_id: str, path: str = "wp-content", hours: int = 24) -> str:
    """
    Recursively list files under a path modified within the last N hours — first move in
    incident triage ("what changed right before this broke").

    Args:
        install_id: WPEngine install name.
        path:       Remote directory to scan (default 'wp-content').
        hours:      Lookback window in hours (default 24).
    """
    try:
        return _ok(sftp_tools.find_recent_files(install_id, path, hours))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sftp_grep_files(install_id: str, pattern: str, path: str = "wp-content") -> str:
    """
    Search file contents for a regex pattern across a directory tree via SFTP — standard
    WordPress backdoor/malware-hunting technique (e.g. pattern 'base64_decode|eval\\('.
    Bounded to 300 files scanned / 200 matches; never scans wp-config.php.

    Args:
        install_id: WPEngine install name.
        pattern:    Python regex pattern to search for in each file's lines.
        path:       Remote directory to scan (default 'wp-content').
    """
    try:
        return _ok(sftp_tools.grep_files(install_id, pattern, path))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def sftp_list_plugins_themes(install_id: str) -> str:
    """
    List installed plugins and themes with their versions (parsed from each plugin's header
    comment or theme's style.css) — quick inventory without WP-CLI or admin access.

    Args:
        install_id: WPEngine install name.
    """
    try:
        return _ok(sftp_tools.list_plugins_themes(install_id))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server(mcp)
