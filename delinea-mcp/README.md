# Delinea Secret Server Discovery MCP server

**Language:** Python · **Tools:** 26 (counted from source) · **Access:** Read-only, metadata only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Discovery scans find accounts, services and scheduled tasks across the estate, but answering 'which discovered accounts are still unmanaged, and what runs as them?' meant stitching together several screens in the vault's cloud console.

## Why it was built this way
Wraps the Delinea Platform and Secret Server Discovery APIs using OAuth client credentials (stored in Windows Credential Manager). All tools are read-only and return metadata about discovery sources, scans, network items, scanners, templates and account rules, never secret values. It adds derived reports on top, such as every discovered account matching a person plus the scheduled tasks and services that run as such an account. Known cloud quirk handled in code: `get_discovery_source` returns a 500, so it falls back to the sources list row.

## What it improves
Turns discovery data into direct answers about unmanaged privileged accounts and residual access, without opening the vault UI or ever touching a secret.

---

## Reference

MCP server for **Delinea Secret Server Discovery** through the Delinea Platform (tenant `company`), hosted on mcp-host.


## Tools (all read-only, metadata only)
| Tool | What it returns |
|------|-----------------|
| `get_token_status` | Auth check and the resolved Secret Server URL (never the token) |
| `list_discovery_sources` / `get_discovery_source` | Discovery sources and their configuration |
| `get_discovery_status` / `get_discovery_scan_results` / `get_discovery_metrics` | Scan state, results, item and OS counts |
| `list_network_items` / `get_network_item` / `get_network_item_services` / `get_network_tree` | Discovered computers, accounts, keys and services |
| `list_scanners` / `list_scan_templates` | Scanner and template configuration |
| `list_account_rules` / `get_account_rule` / `list_dependency_rules` | Rules that turn discoveries into secrets |
| `list_discovery_audit` | Audit log for discovery sources |
| `list_secret_names` / `list_roles` / `get_role_permissions` / `list_reports` / `list_unlimited_admin_audit` | Secret names (no values), roles, report definitions, unlimited-admin audit |
| `host_account_summary` | One host: accounts, managed status, local-admin flags, password age, services and the accounts they run as |
| `unmanaged_privileged_report` | Unmanaged local accounts with local admin rights, grouped by host and OS (reports data quality) |
| `person_account_search` | Every account matching a person, plus tasks and services that run as them (leaver sweeps) |
| `rule_coverage_report` | Account rules, duplicates, matched item counts and uncovered account totals |
| `api_get` | GET for any other allow-listed path (see `client.py`) |

## Safety
- GET only, and only `/v1/discovery...` and `/v1/discovery-source...` paths (checked in `client.py`).
- No tool reads secrets. `DiscoveryRuleAccountDetail` carries `currentPassword`, `currentPassphrase`, `currentPrivateKey` and `newPassword`; the client replaces any such key with `[redacted]` in every response.
- Token request failures return the status and the API's error text only; the secret is never echoed.

## API notes
- Auth: `POST https://example.delinea.app/identity/api/oauth2/token/xpmplatform`, form body `grant_type=client_credentials`, `scope=xpmheadless`, `client_id` = service username, `client_secret` = its password. The token lasts about an hour and renews automatically.
- Secret Server URL: `GET /vaultbroker/api/vaults` (`vaults[].connection.url`), or set `DELINEA_SECRET_SERVER_URL`. Calls go to `<url>/api/v1/discovery/...` with the same Platform bearer token. The `/api` base is inferred from the OpenAPI spec (`servers: /SecretServer/api` for on-prem) and still needs checking on the live instance.
- Spec: https://updates.thycotic.net/secretserver/restapiguide/TokenAuth/ (Secret Server 12.1.2, a 23 MB Redoc page with the OpenAPI JSON embedded).
- Paging uses `take` and `skip`. Other filter and sort parameters are untested, so list tools accept an extra `query_params` JSON object.

## Hosting (hosting standard)
- **Credential type:** service account, meaning one shared read-only service user. Credential Manager target `DelineaPlatform`: user = service username, password = its password.
- **Port:** 3119. Route: `https://mcp-host.example.com/mcp/delinea`.
- NSSM service `MCP-delinea` as svc-mcp, launched by `Start-DelineaMCP.ps1 -Transport http -Port 3119`.
- Create the virtual environment with `uv venv .venv; uv pip install --link-mode=copy --python .venv\Scripts\python.exe -r requirements.txt`.

# Initial version by a colleague, built with the toolbox and reference material provided by Caleb A. Morrow, who reworked, extended, tested and deployed it
