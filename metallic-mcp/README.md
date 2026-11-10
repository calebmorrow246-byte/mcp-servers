# Commvault Metallic MCP server

**Language:** Python · **Tools:** 19 (counted from source) · **Access:** Read-only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Cloud backup and offsite retention status lived in a separate Metallic console from the on-prem backup tool.

## Why it was built this way
Read-only tools for jobs, failed jobs, clients, servers, file servers, hypervisors, VMs, server groups, subclients, alerts, events, storage and plans, running as a user in a read-only role group tied to the company. API token renewal was verified against the live tenant.

## What it improves
Cloud-tier backup health alongside on-prem backup health, in one conversation.

---

## Reference

MCP server for **CommVault Metallic**, the company's cloud backup and offsite retention tier (tenant `ExampleCompanyInc` on `mXXX.metallic.io`), hosted on mcp-host.


## Tools (all read-only)
| Area | Tools |
|------|-------|
| Jobs | `list_jobs`, `get_job`, `list_failed_jobs` |
| Clients | `list_clients`, `get_client_detail`, `list_servers`, `list_file_servers`, `list_hypervisors`, `list_virtual_machines`, `list_server_groups`, `list_subclients` |
| Alerts | `list_alerts`, `list_alert_definitions`, `list_events` |
| Storage | `list_storage` (pools plus disk, local and cloud views), `list_plans` |
| Overview | `get_tenant_overview`, `get_token_status` |
| Other | `api_call` (GET only) |

The tools share the Command Center API family with `commvault-mcp` (on-prem), and the tool code follows it. Two differences:
- **Tenant-scoped:** CommCell-level pages (`/CommServ`, `/Dashboard/SLA`, `/V4/Cloud/Office365`) return 403.
- **Token auth:** it signs in with an API access token, not a password.

## Authentication
- **User:** `MetallicRO`, a member of user group `RO Access`. The group has role `RO` (Global View, View SecOps Manager), **associated with the company** `ExampleCompanyInc`. Associating it only with the role and alerts shows nothing: `/Job` says "User has no credentials on this CommServe".
- **Tokens:** an API access token created in the Metallic console, sent as the plain `Authtoken` header with no `QSDK` prefix.
  - The access token lasts **2 hours**.
  - `POST /V4/AccessToken/Renew {accessToken, refreshToken}` returns a **new pair**, and the old refresh token stops working. The response keys are accessToken, refreshToken, tokenExpiryTimestamp, refreshTokenExpiryTimestamp and renewableUntilTimestamp.
  - `client.py` renews ahead of expiry, on 401 and at startup. It **writes the new pair back to Credential Manager before using it** (`wincred.py`, ctypes CredRead/CredWrite).
- **Replacement:** a token can be renewed only until its *renewable until* date, about 90 days after creation (the first token is good until **2026-12-23**). Before then, create a new token for MetallicRO and store it on mcp-host with:
  ```powershell
  Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Metallic Access Token','Metallic Refresh Token' -Force
  ```
  `get_token_status` reports the days left.
- **Keep one process per token pair.** Anything else that renews with the same pair (for example an ad-hoc test as svc-mcp) rotates it. The server reloads from Credential Manager and recovers, but don't run two long-lived consumers.

## Hosting (hosting standard)
- **Credential type:** service account, read-only (token pair above, stored for svc-mcp).
- **Port:** 3113. Route: `https://mcp-host.example.com/mcp/metallic`.
- NSSM service `MCP-metallic` as svc-mcp, launched by `Start-MetallicMCP.ps1 -Transport http -Port 3113`.
