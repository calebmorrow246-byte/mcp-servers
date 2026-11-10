# 1Password SaaS Manager (formerly Trelica) MCP server

**Language:** Python · **Tools:** 12 (counted from source) · **Access:** Read-only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
SaaS licence utilisation, leaver clean-up and contract renewals were buried in a separate admin console.

## Why it was built this way
Read-only tools for applications (with licences and custom fields), app users (filterable by status and days inactive), people, devices, contracts (soonest renewal first), audit log, workflows and runs, plus a generic GET passthrough. Tested against the live API.

## What it improves
Answers 'who still has a licence they don't use?' and 'what renews soon?' directly.

---

## Reference

MCP server for **1Password SaaS Manager** (formerly Trelica), hosted on mcp-host.


## Tools (all read-only)
| Tool | What it returns |
|------|-----------------|
| `list_apps` | Applications (search `q`, filter `status`) |
| `get_app` | One application in full: licences, custom fields |
| `list_app_users` | Accounts in one app, with filters for `status` and `inactive_days` (licence utilisation, leavers) |
| `list_people` | People (search `q`, filter `person_type`) |
| `get_person` | One person in full |
| `list_assets` | Devices |
| `list_contracts` | Contracts, soonest renewal first; filter `renewal_within_days` |
| `list_audit_log` | SaaS Manager's own audit log (`since`) |
| `list_workflows` / `list_workflow_runs` | Workflow definitions and their runs |
| `list_saas_manager_users` | Who can sign in to SaaS Manager (SCIM) |
| `api_get` | GET for any other `/api/...` path |

## API notes
- Host `trelica.app` (US tenant). Token: `POST /connect/token`, Basic auth `clientId:secret`, `grant_type=client_credentials`.
- **Read-only by construction:** the server requests only the read scopes (`Apps.Read Apps.Users.Read People.Read Assets.Read Contracts.Read AuditLog.Read Users.Read Workflows.Read Workflows.Runs.Read`) and only issues GETs. The token lasts an hour and is renewed automatically.
- Lists return `{next, results}`. `limit` is up to 1000; the client follows `next`. App accounts are at `/api/apps/v1/{id}/users`, workflow runs at `/api/workflows/v1/{id}/runs`. SCIM users use `startIndex`/`count`.
- Docs: `support.1password.com/saas-manager-*` (client credentials flow, scopes, pagination, filtering).

## Hosting (hosting standard)
- **Credential type:** service account, meaning one shared read-only API client. Credential Manager target `SaaS Manager API` for svc-mcp: the user field is the client ID and the password is the client secret.
- **Port:** 3115. Route: `https://mcp-host.example.com/mcp/saas-manager`.
- NSSM service `MCP-saas-manager` as svc-mcp, launched by `Start-SaasManagerMCP.ps1 -Transport http -Port 3115`.
- Set up the virtual environment with `uv venv .venv` and then `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`.
