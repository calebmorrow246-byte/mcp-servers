# Unixi proxy MCP server

**Language:** Python · **Tools:** 7 allow-listed + derived (counted from source) · **Access:** Read-only by construction

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
The vendor's beta MCP endpoint needs a shared API key and tenant ID that users should never hold, and it may add write tools later.

## Why it was built this way
A hosted proxy in front of the vendor's own MCP server. Callers authenticate with their own bearer token (with audit logging); the proxy adds the shared vendor credentials upstream. Only an explicit allow-list of seven `get_*` tools is listed or callable, so any tool the vendor adds later (including writes) stays hidden until added on purpose. Locally derived tools (such as a residual-access report) are computed only from those allow-listed tools.

## What it improves
Safe access to a beta vendor API without distributing its key or trusting its future tool list.

---

## Reference

Hosted, read-only proxy in front of Unixi's own beta MCP server (`POST https://app.unixi.io/mcp`).

- Callers send their per-user bearer token (standard the company MCP auth + audit logging).
- The proxy adds the shared Unixi `X-API-KEY` / `X-TENANT-ID` upstream. Users never hold the Unixi key.
- Only the 7 allow-listed `get_*` tools are listed or callable (`ALLOWED_TOOLS` in `server.py`). New
  upstream tools, including any write tool, stay hidden until added there on purpose.

| Tool | Mirrors |
|------|---------|
| get_logs | GET /api/public/v1/logs |
| get_applications | /applications |
| get_discovery_shared_accounts | /discovery/shared-accounts |
| get_discovery_applications | /discovery/applications |
| get_lifecycle_applications | /lifecycle/applications |
| get_lifecycle_app_tenants | /lifecycle/app-tenants |
| get_lifecycle_users | /lifecycle/users (orphan / residual filters) |

## Derived tools (derived.py)

Computed locally from the allow-listed tools above with the same key; no extra credential, read-only.

| Tool | What it does |
|------|--------------|
| residual_access_report | Apps with live accounts whose directory identity is gone (leaver gap), ranked by count; `include_users` lists the accounts (PII) |
| shadow_app_gap | Unmanaged discovered apps ranked by users with risk factors; pass `known_domains` (e.g. from SaaS Manager) to drop apps already tracked, matching subdomains too |

Cross-system joins stay with the caller so this server never holds another system's credentials.

Port 3118. Credential: `Unixi MCP API` (key with purpose "MCP API"; tenant-wide, cannot be scoped).
Run with `Start-UnixiMCP.ps1 -Port 3118` (HTTP only). Contains PII (lifecycle users, logs, shared accounts).

Planned: derived tools (`residual_access_report`, `shadow_app_gap`) using the `Unixi Public API` key.
