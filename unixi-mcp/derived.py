"""
Derived (computed) tools for the Unixi MCP proxy. Read-only.

Each tool is built from the same allow-listed upstream get_* tools the proxy already exposes, using
the same MCP API key, so no extra credential and no write path. Cross-system joins (SaaS Manager,
Entra, Freshservice) are done by the caller: shadow_app_gap accepts the other system's domains as a
parameter instead of this server holding that system's credentials.
"""

import json
from typing import Any, Awaitable, Callable

# call(tool_name, arguments) -> parsed upstream tool result (the {"data": [...], "meta": {...}} body)
ToolCaller = Callable[[str, dict], Awaitable[Any]]

PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 30   # 3000 rows; upstream snapshots/cursors expire after about an hour
HARD_MAX_PAGES = 100
MAX_KNOWN_DOMAINS = 5000

DERIVED_TOOLS: list[dict] = [
    {
        "name": "residual_access_report",
        "description": (
            "Leaver-gap report: applications that still hold live accounts whose directory identity was "
            "deactivated or deleted (Unixi 'residual' accounts), ranked by residual count. Set "
            "include_users to list the residual accounts per app (returns PII: names and emails). "
            "Orphan counts are reported per app but are not the leaver signal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_users": {"type": "boolean", "default": True,
                                  "description": "List the residual accounts for each app (PII)."},
                "max_users_per_app": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100,
                                      "description": "Cap on residual accounts listed per app."},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": HARD_MAX_PAGES,
                              "default": DEFAULT_MAX_PAGES, "description": "Upstream page cap per listing."},
            },
        },
    },
    {
        "name": "shadow_app_gap",
        "description": (
            "Unmanaged applications discovered in tenant activity, ranked by user count with risk factors "
            "and login types. Pass known_domains (e.g. the domains from the SaaS Manager inventory) to drop "
            "apps that are already tracked there, leaving the true gap. A domain matches when it equals a "
            "known domain or is a subdomain of one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "known_domains": {"type": "array", "items": {"type": "string"}, "default": [],
                                  "description": "Domains already tracked elsewhere; matching apps are excluded."},
                "min_users": {"type": "integer", "minimum": 1, "default": 1,
                              "description": "Only apps with at least this many users."},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": HARD_MAX_PAGES,
                              "default": DEFAULT_MAX_PAGES, "description": "Upstream page cap."},
            },
        },
    },
]
DERIVED_NAMES = frozenset(t["name"] for t in DERIVED_TOOLS)


def _int(args: dict, key: str, default: int, low: int, high: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{key} must be an integer between {low} and {high}")
    return value


async def _collect(call: ToolCaller, tool: str, args: dict, max_pages: int) -> tuple[list, bool]:
    """Page through an upstream listing; returns (rows, truncated)."""
    rows: list = []
    cursor = ""
    for _ in range(max_pages):
        body = await call(tool, {**args, "limit": PAGE_SIZE, "cursor": cursor})
        rows.extend(body.get("data", []))
        meta = body.get("meta", {})
        if not meta.get("has_more"):
            return rows, False
        cursor = meta.get("next_cursor", "")
        if not cursor:
            return rows, False
    return rows, True


async def residual_access_report(call: ToolCaller, args: dict) -> dict:
    include_users = args.get("include_users", True)
    if not isinstance(include_users, bool):
        raise ValueError("include_users must be a boolean")
    per_app = _int(args, "max_users_per_app", 100, 1, 500)
    max_pages = _int(args, "max_pages", DEFAULT_MAX_PAGES, 1, HARD_MAX_PAGES)

    apps, truncated = await _collect(call, "get_lifecycle_applications", {}, max_pages)
    affected = sorted((a for a in apps if (a.get("residual_users_count") or 0) > 0),
                      key=lambda a: a["residual_users_count"], reverse=True)

    report = []
    for app in affected:
        entry = {
            "application": app["application"],
            "is_managed": app.get("is_managed"),
            "residual_users_count": app["residual_users_count"],
            "orphan_users_count": app.get("orphan_users_count"),
            "synced_users_count": app.get("synced_users_count"),
            "deprovisioning_enabled": app.get("deprovisioning_enabled"),
            "last_execution_at": app.get("last_execution_at"),
        }
        if include_users:
            pages = max(1, -(-per_app // PAGE_SIZE))
            users, more = await _collect(call, "get_lifecycle_users",
                                         {"application": app["application"], "residual": True}, pages)
            entry["users_truncated"] = more or len(users) > per_app
            entry["residual_users"] = [
                {k: u.get(k) for k in ("user_id", "email", "username", "full_name", "company_name",
                                       "is_active", "correlated_email", "last_login", "last_synced_at")}
                for u in users[:per_app]
            ]
        report.append(entry)

    return {
        "applications_scanned": len(apps),
        "applications_with_residual": len(report),
        "total_residual_accounts": sum(e["residual_users_count"] for e in report),
        "listing_truncated": truncated,
        "applications": report,
    }


def _is_known(domain: str, known: set[str]) -> bool:
    parts = domain.lower().strip(".").split(".")
    return any(".".join(parts[i:]) in known for i in range(len(parts)))


async def shadow_app_gap(call: ToolCaller, args: dict) -> dict:
    known_raw = args.get("known_domains", [])
    if (not isinstance(known_raw, list) or len(known_raw) > MAX_KNOWN_DOMAINS
            or not all(isinstance(d, str) for d in known_raw)):
        raise ValueError(f"known_domains must be a list of at most {MAX_KNOWN_DOMAINS} strings")
    known = {d.lower().strip().strip(".") for d in known_raw if d.strip()}
    min_users = _int(args, "min_users", 1, 1, 1_000_000)
    max_pages = _int(args, "max_pages", DEFAULT_MAX_PAGES, 1, HARD_MAX_PAGES)

    apps, truncated = await _collect(call, "get_discovery_applications", {"managed": "unmanaged"}, max_pages)
    candidates = [a for a in apps if (a.get("users") or 0) >= min_users]
    gap = [a for a in candidates if not _is_known(a.get("domain", ""), known)]
    gap.sort(key=lambda a: (a.get("users") or 0), reverse=True)

    return {
        "unmanaged_discovered": len(apps),
        "meeting_min_users": len(candidates),
        "excluded_as_known": len(candidates) - len(gap),
        "listing_truncated": truncated,
        "applications": [
            {k: a.get(k) for k in ("domain", "application", "users", "risk_factors", "login_type", "last_seen_at")}
            for a in gap
        ],
    }


_HANDLERS = {"residual_access_report": residual_access_report, "shadow_app_gap": shadow_app_gap}


async def run_derived(name: str, args: dict, call: ToolCaller) -> str:
    """Run a derived tool and return its JSON text for an MCP text content block."""
    return json.dumps(await _HANDLERS[name](call, args or {}), indent=2, default=str)
