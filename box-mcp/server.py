# Authored by Caleb A. Morrow
"""
Box MCP Server (read-only)

Exposes Box search, folders, files, comments, collaborations, metadata, Hubs, users, groups, admin
events, collaboration controls, legal hold, retention and enterprise configuration as MCP tools. Read-only by construction: the client issues only GET requests to an allow-listed set of
paths. There is no write tool and no Box AI tool (nothing under /ai), so Box AI usage is never
triggered.

The server acts as one Box user (box.admin) through a Client Credentials Grant app.

Configuration via environment variables:
  BOX_CLIENT_ID      - Box app client ID (required)
  BOX_CLIENT_SECRET  - Box app client secret (required)
  BOX_SUBJECT_ID     - Box user ID (or enterprise ID) the token is issued for (required)
  BOX_SUBJECT_TYPE   - user (default) or enterprise
  BOX_TIMEOUT        - Request timeout in seconds (default: 60)
"""

import json
import logging
import os
import re
import sys
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from client import BoxClient, BoxError
from mcp_transport import run_server

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer("Box")

_client: Optional[BoxClient] = None

# Files whose raw bytes are plain text; anything else goes through Box's extracted-text representation
TEXT_EXTENSIONS = {"txt", "md", "csv", "tsv", "json", "xml", "yaml", "yml", "log", "html", "htm",
                   "ps1", "py", "js", "ts", "sql", "ini", "cfg", "conf", "boxnote"}
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024


def get_client() -> BoxClient:
    global _client
    if _client is None:
        client_id = os.environ.get("BOX_CLIENT_ID", "").strip()
        client_secret = os.environ.get("BOX_CLIENT_SECRET", "")
        subject_id = os.environ.get("BOX_SUBJECT_ID", "").strip()
        subject_type = os.environ.get("BOX_SUBJECT_TYPE", "user").strip() or "user"
        timeout = float(os.environ.get("BOX_TIMEOUT", "60"))
        if not client_id or not client_secret or not subject_id:
            raise RuntimeError("BOX_CLIENT_ID, BOX_CLIENT_SECRET and BOX_SUBJECT_ID are required")
        _client = BoxClient(client_id, client_secret, subject_id, subject_type, timeout)
    return _client


def _ok(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _err(exc: Exception) -> str:
    if isinstance(exc, BoxError):
        return json.dumps({"error": exc.message, "code": exc.code})
    return json.dumps({"error": str(exc)})


def _id(value: str, name: str) -> str:
    value = str(value).strip()
    if not re.fullmatch(r"\d+", value):
        raise ValueError(f"{name} must be a numeric Box ID")
    return value


def _fields(fields: Optional[str]) -> dict:
    """Optional comma-separated Box field list as a query parameter."""
    return {"fields": fields} if fields else {}


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


@mcp.tool()
def get_token_status() -> str:
    """Check that the Box app can authenticate and which Box user the token is for.

    Returns authentication state, subject and seconds until renewal. Never returns the token.
    """
    try:
        return _ok(get_client().token_status())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def who_am_i() -> str:
    """Return the Box user this server acts as (name, login, role, status)."""
    try:
        return _ok(get_client().get("/users/me"))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Search, folders and files
# ---------------------------------------------------------------------------


@mcp.tool()
def search_files(query: str, item_type: Optional[str] = None, ancestor_folder_ids: Optional[str] = None,
                 file_extensions: Optional[str] = None, owner_user_ids: Optional[str] = None,
                 limit: int = 30, offset: int = 0, fields: Optional[str] = None) -> str:
    """Keyword search across Box content visible to the acting user.

    Args:
        query: Search text (Box matches names, descriptions and file content).
        item_type: Optional file, folder or web_link.
        ancestor_folder_ids: Optional comma-separated folder IDs to search inside.
        file_extensions: Optional comma-separated extensions, for example "pdf,docx".
        owner_user_ids: Optional comma-separated owner user IDs.
        limit: Results per page (1 to 200).
        offset: Paging offset.
        fields: Optional comma-separated Box fields to return.
    """
    try:
        params: dict = {"query": query, "limit": max(1, min(limit, 200)), "offset": max(0, offset)}
        if item_type:
            if item_type not in ("file", "folder", "web_link"):
                raise ValueError("item_type must be file, folder or web_link")
            params["type"] = item_type
        for key, value in (("ancestor_folder_ids", ancestor_folder_ids),
                           ("file_extensions", file_extensions), ("owner_user_ids", owner_user_ids)):
            if value:
                params[key] = value
        params.update(_fields(fields))
        return _ok(get_client().get("/search", params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_folder_items(folder_id: str = "0", limit: int = 100, offset: int = 0,
                      fields: Optional[str] = None) -> str:
    """List the files, folders and web links in a folder. Folder 0 is the root.

    Args:
        folder_id: Numeric folder ID (default 0, the root).
        limit: Items per page (1 to 1000).
        offset: Paging offset.
        fields: Optional comma-separated Box fields, for example "id,name,type,size,owned_by".
    """
    try:
        params = {"limit": max(1, min(limit, 1000)), "offset": max(0, offset), **_fields(fields)}
        return _ok(get_client().get(f"/folders/{_id(folder_id, 'folder_id')}/items", params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_folder(folder_id: str, fields: Optional[str] = None) -> str:
    """Details of one folder (owner, parent, path, size, collaboration flag)."""
    try:
        return _ok(get_client().get(f"/folders/{_id(folder_id, 'folder_id')}", _fields(fields)))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_file(file_id: str, fields: Optional[str] = None) -> str:
    """Details of one file (name, size, owner, parent, path, dates, extension)."""
    try:
        return _ok(get_client().get(f"/files/{_id(file_id, 'file_id')}", _fields(fields)))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_file_text(file_id: str, max_chars: int = 100000) -> str:
    """Read a file's text content.

    Plain-text types are downloaded directly (up to 5 MB). Other types (Word, PDF, and so on) use Box's
    extracted-text representation when it is ready. Returns an error note for types Box cannot extract.

    Args:
        file_id: Numeric file ID.
        max_chars: Maximum characters returned (1 to 500000).
    """
    try:
        fid = _id(file_id, "file_id")
        limit = max(1, min(max_chars, 500000))
        client = get_client()
        info = client.get(f"/files/{fid}", {"fields": "name,extension,size"})
        ext = (info.get("extension") or "").lower()
        if ext in TEXT_EXTENSIONS:
            data, truncated = client.download(fid, MAX_DOWNLOAD_BYTES)
            text, note = data.decode("utf-8", errors="replace"), ""
            if truncated:
                note = "File larger than 5 MB; content cut off"
        else:
            text, note = client.extracted_text(fid, MAX_DOWNLOAD_BYTES)
        if text is None:
            return _ok({"file": info.get("name"), "text": None, "note": note})
        cut = len(text) > limit
        return _ok({"file": info.get("name"), "extension": ext, "characters": min(len(text), limit),
                    "truncated": cut or bool(note), "note": note, "text": text[:limit]})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_file_comments(file_id: str, limit: int = 100, offset: int = 0) -> str:
    """Comments on a file. NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        params = {"limit": max(1, min(limit, 1000)), "offset": max(0, offset)}
        return _ok(get_client().get(f"/files/{_id(file_id, 'file_id')}/comments", params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_collaborations(item_type: str, item_id: str) -> str:
    """Who has access to a file or folder (collaborators and their roles).

    Args:
        item_type: file or folder.
        item_id: Numeric ID of the file or folder.
    """
    try:
        if item_type not in ("file", "folder"):
            raise ValueError("item_type must be file or folder")
        return _ok(get_client().get(f"/{item_type}s/{_id(item_id, 'item_id')}/collaborations"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_metadata_templates() -> str:
    """Enterprise metadata templates (names, keys and field definitions)."""
    try:
        return _ok(get_client().get("/metadata_templates/enterprise"))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Hubs
# ---------------------------------------------------------------------------


@mcp.tool()
def list_hubs(query: Optional[str] = None, limit: int = 100, marker: Optional[str] = None) -> str:
    """List Box Hubs, optionally filtered by a search string. Pass the returned marker to page."""
    try:
        params: dict = {"limit": max(1, min(limit, 1000))}
        if query:
            params["query"] = query
        if marker:
            params["marker"] = marker
        return _ok(get_client().get("/hubs", params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_hub(hub_id: str) -> str:
    """Details of one Box Hub."""
    try:
        return _ok(get_client().get(f"/hubs/{_id(hub_id, 'hub_id')}"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_hub_items(hub_id: str, limit: int = 100, marker: Optional[str] = None) -> str:
    """Items (files, folders, web links) in a Box Hub. Pass the returned marker to page."""
    try:
        params: dict = {"hub_id": _id(hub_id, "hub_id"), "limit": max(1, min(limit, 1000))}
        if marker:
            params["marker"] = marker
        return _ok(get_client().get("/hub_items", params))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_hub_collaborations(hub_id: str, limit: int = 100, marker: Optional[str] = None) -> str:
    """Who has access to a Box Hub and with which role. Pass the returned marker to page."""
    try:
        params: dict = {"hub_id": _id(hub_id, "hub_id"), "limit": max(1, min(limit, 1000))}
        if marker:
            params["marker"] = marker
        return _ok(get_client().get("/hub_collaborations", params))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Shared helpers for the enterprise tools below
# ---------------------------------------------------------------------------


def _page(limit: int, offset: Optional[int] = None, marker: Optional[str] = None,
          fields: Optional[str] = None, top: int = 1000, **extra: Any) -> dict:
    """Common paging query parameters; None-valued extras are dropped."""
    params: dict = {"limit": max(1, min(limit, top))}
    if offset is not None:
        params["offset"] = max(0, offset)
    if marker:
        params["marker"] = marker
    params.update(_fields(fields))
    params.update({k: v for k, v in extra.items() if v not in (None, "")})
    return params


def _get(path: str, params: Optional[dict] = None) -> str:
    return _ok(get_client().get(path, params))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@mcp.tool()
def list_users(filter_term: Optional[str] = None, user_type: Optional[str] = None, limit: int = 100,
               offset: int = 0, fields: Optional[str] = None) -> str:
    """List enterprise users.

    Args:
        filter_term: Match against name or login (starts-with).
        user_type: all, managed (default) or external.
        limit: Users per page (1 to 1000).
        offset: Paging offset.
        fields: Optional comma-separated fields, for example "id,name,login,status,last_login_at,space_used".
    """
    try:
        if user_type and user_type not in ("all", "managed", "external"):
            raise ValueError("user_type must be all, managed or external")
        return _get("/users", _page(limit, offset=offset, fields=fields,
                                    filter_term=filter_term, user_type=user_type))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_user(user_id: str, fields: Optional[str] = None) -> str:
    """Details of one user (status, role, storage, login times)."""
    try:
        return _get(f"/users/{_id(user_id, 'user_id')}", _fields(fields))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_user_memberships(user_id: str, limit: int = 100, offset: int = 0) -> str:
    """Groups a user belongs to."""
    try:
        return _get(f"/users/{_id(user_id, 'user_id')}/memberships", _page(limit, offset=offset, top=1000))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_user_email_aliases(user_id: str) -> str:
    """Email aliases of a user."""
    try:
        return _get(f"/users/{_id(user_id, 'user_id')}/email_aliases")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def users_by_domain(user_type: str = "all", max_users: int = 20000) -> str:
    """Count enterprise users by login email domain and status.

    Pages through every user, so it can take a while on a large tenant. Useful as a stand-in for the
    Admin Console Domain Management list, which Box does not expose in its API: it shows which email
    domains actually have accounts, how many are active, and sample logins for each domain.

    Args:
        user_type: all (default), managed or external.
        max_users: Safety cap on users read.
    """
    try:
        if user_type not in ("all", "managed", "external"):
            raise ValueError("user_type must be all, managed or external")
        client = get_client()
        domains: dict = {}
        offset, total, seen = 0, None, 0
        cap = max(1, min(max_users, 100000))
        while seen < cap:
            page = client.get("/users", {"limit": 1000, "offset": offset, "user_type": user_type,
                                         "fields": "login,status"})
            entries = page.get("entries") or []
            total = page.get("total_count", total)
            for user in entries:
                seen += 1
                login = (user.get("login") or "").lower()
                domain = login.rsplit("@", 1)[-1] if "@" in login else "(none)"
                row = domains.setdefault(domain, {"domain": domain, "total": 0, "by_status": {}, "sample": []})
                row["total"] += 1
                status = user.get("status") or "unknown"
                row["by_status"][status] = row["by_status"].get(status, 0) + 1
                if len(row["sample"]) < 3:
                    row["sample"].append(login)
            if not entries or (total is not None and offset + len(entries) >= total):
                break
            offset += len(entries)
        result = sorted(domains.values(), key=lambda r: -r["total"])
        return _ok({"users_read": seen, "total_count": total, "complete": total is None or seen >= total,
                    "domains": result})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@mcp.tool()
def list_groups(filter_term: Optional[str] = None, limit: int = 100, offset: int = 0,
                fields: Optional[str] = None) -> str:
    """List enterprise groups. filter_term matches the group name (starts-with)."""
    try:
        return _get("/groups", _page(limit, offset=offset, fields=fields, filter_term=filter_term))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_group(group_id: str, fields: Optional[str] = None) -> str:
    """Details of one group."""
    try:
        return _get(f"/groups/{_id(group_id, 'group_id')}", _fields(fields))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_group_members(group_id: str, limit: int = 100, offset: int = 0) -> str:
    """Members of a group with their group role."""
    try:
        return _get(f"/groups/{_id(group_id, 'group_id')}/memberships", _page(limit, offset=offset))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_group_collaborations(group_id: str, limit: int = 100, offset: int = 0) -> str:
    """Files and folders a group has been given access to."""
    try:
        return _get(f"/groups/{_id(group_id, 'group_id')}/collaborations", _page(limit, offset=offset))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Audit events, collaboration controls
# ---------------------------------------------------------------------------


@mcp.tool()
def list_admin_events(event_types: Optional[str] = None, created_after: Optional[str] = None,
                      created_before: Optional[str] = None, limit: int = 100,
                      stream_position: Optional[str] = None) -> str:
    """Enterprise admin audit events (logins, shares, downloads, permission changes, and so on).

    NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope. Box keeps about a year of history.

    Args:
        event_types: Optional comma-separated event types, for example "LOGIN,FAILED_LOGIN,SHARE,DOWNLOAD".
        created_after: Optional RFC 3339 start time, for example 2026-11-01T00:00:00-06:00.
        created_before: Optional RFC 3339 end time.
        limit: Events per page (1 to 500).
        stream_position: Position returned by the previous call, to page forward.
    """
    try:
        params = {"stream_type": "admin_logs", "limit": max(1, min(limit, 500))}
        for key, value in (("event_type", event_types), ("created_after", created_after),
                           ("created_before", created_before), ("stream_position", stream_position)):
            if value:
                params[key] = value
        return _get("/events", params)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_collaboration_allowlist(limit: int = 100, marker: Optional[str] = None) -> str:
    """Domains allowed for collaboration invites (the 'domain restrictions' setting), with direction."""
    try:
        return _get("/collaboration_whitelist_entries", _page(limit, marker=marker, top=1000))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_collaboration_allowlist_entry(entry_id: str) -> str:
    """One collaboration allowlist entry."""
    try:
        return _get(f"/collaboration_whitelist_entries/{_id(entry_id, 'entry_id')}")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_collaboration_allowlist_exempt_users(limit: int = 100, marker: Optional[str] = None) -> str:
    """Users exempt from the collaboration domain restrictions."""
    try:
        return _get("/collaboration_whitelist_exempt_targets", _page(limit, marker=marker, top=1000))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_pending_collaborations(limit: int = 100, offset: int = 0) -> str:
    """Collaboration invitations that have not been accepted yet (for the acting user's view)."""
    try:
        return _get("/collaborations", _page(limit, offset=offset, status="pending", top=1000))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_collaboration(collaboration_id: str, fields: Optional[str] = None) -> str:
    """Details of one collaboration (who, role, status, expiry, item)."""
    try:
        return _get(f"/collaborations/{_id(collaboration_id, 'collaboration_id')}", _fields(fields))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Compliance: legal hold and retention
# ---------------------------------------------------------------------------


@mcp.tool()
def list_legal_hold_policies(policy_name: Optional[str] = None, limit: int = 100,
                             marker: Optional[str] = None) -> str:
    """Legal hold policies. policy_name filters by name (starts-with). NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        return _get("/legal_hold_policies", _page(limit, marker=marker, policy_name=policy_name))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_legal_hold_policy(policy_id: str) -> str:
    """One legal hold policy. NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        return _get(f"/legal_hold_policies/{_id(policy_id, 'policy_id')}")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_legal_hold_assignments(policy_id: str, assign_to_type: Optional[str] = None,
                                assign_to_id: Optional[str] = None, limit: int = 100,
                                marker: Optional[str] = None) -> str:
    """What a legal hold policy is assigned to (users, files, folders, file versions). NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope.

    Args:
        policy_id: Numeric legal hold policy ID.
        assign_to_type: Optional file, file_version, folder or user (needs assign_to_id).
        assign_to_id: Optional ID of the assigned item.
    """
    try:
        if assign_to_type and assign_to_type not in ("file", "file_version", "folder", "user"):
            raise ValueError("assign_to_type must be file, file_version, folder or user")
        extra = {"policy_id": _id(policy_id, "policy_id"), "assign_to_type": assign_to_type,
                 "assign_to_id": _id(assign_to_id, "assign_to_id") if assign_to_id else None}
        return _get("/legal_hold_policy_assignments", _page(limit, marker=marker, **extra))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_files_on_hold(assignment_id: str, limit: int = 100, marker: Optional[str] = None) -> str:
    """Current file versions held under one legal hold assignment. NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        return _get(f"/legal_hold_policy_assignments/{_id(assignment_id, 'assignment_id')}/files_on_hold",
                    _page(limit, marker=marker))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_retention_policies(policy_name: Optional[str] = None, policy_type: Optional[str] = None,
                            limit: int = 100, marker: Optional[str] = None) -> str:
    """Retention policies. policy_type is finite or indefinite. NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        if policy_type and policy_type not in ("finite", "indefinite"):
            raise ValueError("policy_type must be finite or indefinite")
        return _get("/retention_policies", _page(limit, marker=marker, policy_name=policy_name,
                                                 policy_type=policy_type))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_retention_policy(policy_id: str) -> str:
    """One retention policy. NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        return _get(f"/retention_policies/{_id(policy_id, 'policy_id')}")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_retention_assignments(policy_id: str, assignment_type: Optional[str] = None, limit: int = 100,
                               marker: Optional[str] = None) -> str:
    """What a retention policy is assigned to. assignment_type: folder, enterprise or metadata_template. NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        if assignment_type and assignment_type not in ("folder", "enterprise", "metadata_template"):
            raise ValueError("assignment_type must be folder, enterprise or metadata_template")
        return _get(f"/retention_policies/{_id(policy_id, 'policy_id')}/assignments",
                    _page(limit, marker=marker, type=assignment_type))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_files_under_retention(assignment_id: str, limit: int = 100, marker: Optional[str] = None) -> str:
    """Files under retention for one retention policy assignment. NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        return _get(f"/retention_policy_assignments/{_id(assignment_id, 'assignment_id')}/files_under_retention",
                    _page(limit, marker=marker))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Item details: versions, metadata, tasks, trash, locks, web links
# ---------------------------------------------------------------------------


@mcp.tool()
def list_file_versions(file_id: str, limit: int = 100, offset: int = 0) -> str:
    """Previous versions of a file (who uploaded, when, size)."""
    try:
        return _get(f"/files/{_id(file_id, 'file_id')}/versions", _page(limit, offset=offset, top=1000))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_file_tasks(file_id: str) -> str:
    """Tasks attached to a file. NOTE: returns 403 with the current app scopes."""
    try:
        return _get(f"/files/{_id(file_id, 'file_id')}/tasks")
    except Exception as exc:
        return _err(exc)


def _metadata_path(kind: str, item_id: str, template_key: Optional[str]) -> str:
    base = f"/{kind}s/{_id(item_id, kind + '_id')}/metadata"
    if not template_key:
        return base
    key = template_key.strip()
    if key == "properties":
        return f"{base}/global/properties"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError("template_key must be the template key, or 'properties' for the global template")
    return f"{base}/enterprise/{key}"


@mcp.tool()
def get_file_metadata(file_id: str, template_key: Optional[str] = None) -> str:
    """Metadata on a file, such as its security classification.

    Args:
        file_id: Numeric file ID.
        template_key: Optional enterprise template key (see list_metadata_templates), or 'properties'.
            Without it, every metadata instance on the file is returned.
    """
    try:
        return _get(_metadata_path("file", file_id, template_key))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_folder_metadata(folder_id: str, template_key: Optional[str] = None) -> str:
    """Metadata on a folder. template_key works as in get_file_metadata."""
    try:
        return _get(_metadata_path("folder", folder_id, template_key))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_trash(limit: int = 100, offset: int = 0, fields: Optional[str] = None) -> str:
    """Items in the acting user's trash. Use a small limit and fields (for example "id,name,trashed_at"); the default is slow on a large trash."""
    try:
        return _get("/folders/trash/items", _page(limit, offset=offset, fields=fields or "id,name,type,trashed_at,size"))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_folder_locks(folder_id: str) -> str:
    """Locks on a folder (prevent move or delete)."""
    try:
        return _get("/folder_locks", {"folder_id": _id(folder_id, "folder_id")})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_web_link(web_link_id: str) -> str:
    """Details of one web link item (target URL, parent, owner)."""
    try:
        return _get(f"/web_links/{_id(web_link_id, 'web_link_id')}")
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Enterprise configuration
# ---------------------------------------------------------------------------


@mcp.tool()
def list_webhooks(limit: int = 100, marker: Optional[str] = None) -> str:
    """Webhooks created by the acting app or user (targets, triggers, addresses)."""
    try:
        return _get("/webhooks", _page(limit, marker=marker, top=200))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_webhook(webhook_id: str) -> str:
    """One webhook."""
    try:
        return _get(f"/webhooks/{_id(webhook_id, 'webhook_id')}")
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_storage_policies(limit: int = 100, marker: Optional[str] = None) -> str:
    """Storage policies (data residency zones) defined for the enterprise."""
    try:
        return _get("/storage_policies", _page(limit, marker=marker, top=100))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_terms_of_service(tos_type: Optional[str] = None) -> str:
    """Terms of service configured for the enterprise. tos_type: managed or external."""
    try:
        if tos_type and tos_type not in ("managed", "external"):
            raise ValueError("tos_type must be managed or external")
        return _get("/terms_of_services", {"tos_type": tos_type} if tos_type else None)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_terms_of_service_user_statuses(tos_id: str, user_id: Optional[str] = None) -> str:
    """Whether users have accepted a terms of service. user_id narrows it to one user."""
    try:
        params = {"tos_id": _id(tos_id, "tos_id")}
        if user_id:
            params["user_id"] = _id(user_id, "user_id")
        return _get("/terms_of_service_user_statuses", params)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def list_sign_requests(limit: int = 100, marker: Optional[str] = None) -> str:
    """Box Sign requests created by the acting user (status, signers, source files). NOTE: needs a Box app scope the current app does not have; expect 403 insufficient_scope."""
    try:
        return _get("/sign_requests", _page(limit, marker=marker, top=1000))
    except Exception as exc:
        return _err(exc)


if __name__ == "__main__":
    run_server(mcp)

# Authored by Caleb A. Morrow
