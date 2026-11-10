# Windows server diagnostics (WinRM / JEA) MCP server

**Language:** Python · **Tools:** 15 (counted from source) · **Access:** Read-only by construction

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Diagnosing a Windows server meant remoting in and running ad-hoc commands, and event-log noise buried the real problems.

## Why it was built this way
Connects over WinRM to a constrained JEA endpoint exposing a handful of read-only `Get-*` functions in NoLanguage mode: no shell and no write path. Only servers on an allow-list file can be queried. An event-triage tool groups a server's System and Application errors and matches them against a knowledge base of known signatures (source and event ID, then message regex), each with a reviewed fix, root cause and priority; unreviewed draft entries can never turn a finding into 'clean'. It superseded an earlier PowerShell event-triage module.

## What it improves
Safe, repeatable server health checks, and event triage that recognises known noise so people only look at what's new.


> **Not included:** the JEA role-capability and deployment scripts (they are environment-specific). This repo ships a generic subset (29 entries) of the production known-events knowledge base and a `servers.example.json` allow-list; copy it to `servers.json` and list your own servers.

---

## Reference

MCP server for **read-only Windows server diagnostics**, hosted on mcp-host. It connects over
WinRM to the constrained **read-only JEA endpoint**, which
exposes nine `Get-Ro*` functions in NoLanguage mode. There is no shell and no write path.

## Tools
`list_servers`, `get_os_info`, `get_service_info`, `get_installed_software`, `get_registry_value`,
`get_file_info`, `get_event_log`, `get_event_summary`, `get_iis_bindings`, `get_iis_auth`, `get_iis_log_summary`,
and the event-triage tools `triage_events`, `list_known_events`, `get_triage_guidance`.

## Event triage knowledge base
`knowledge/known_events.json` holds known Windows event signatures with a reviewed fix, root cause and
priority (H/M/L). `triage_events` groups a server's System + Application errors (via `Get-RoEventSummary`)
and matches each group against it (`kb.py`: source + event ID, then message regex, then the no-pattern
default). Entries have a `scope` (server | workstation | both; the MCP uses server + both) and a
`reviewed` flag: a draft (`reviewed: false`) is shown but can never turn a finding into "clean".
Entries tagged `benign-if-scan-correlated` are only benign when their timing matches Qualys scan
windows (the SQM skill checks that). Originally a workstation proof of concept (an earlier PowerShell module,
retired 2026-10-21); retuned for servers. To change it: edit the JSON, include an `exampleMessage` for
any `messagePattern`, run `.venv\Scripts\python.exe tests\validate_kb.py`, commit via pull request.

## Hosting (hosting standard)
- **Credential type:** service account, read-only (`Windows RO` = `CORP\svc-winrm-ro`, stored for svc-mcp).
  The account is **not an administrator** anywhere; it can only open the `ReadOnly` endpoint.
- **Port:** 3117. Route: `https://mcp-host.example.com/mcp/winrm`. NSSM service `MCP-winrm` as svc-mcp.
- **Allow-list:** only hosts in `servers.json` can be queried (exact lowercase FQDNs). A server must have the
  endpoint deployed first (`Deploy-ReadOnlyJea.ps1`), then be added to `servers.json`.
- **Scope:** the example.com domain by default. Other domains need their own account and endpoint mapping. The DMZ
  (`dmz.example.com`, 192.0.2.x, not in DNS) is supported with a second account: `Windows RO DMZ`
  (`DMZDOMAIN\svc-winrm-ro`, stored for svc-mcp). A `servers.json` entry for those hosts sets
  `"address": "<ip>"` (what the client connects to) and `"credential": "dmz"` (loaded by the launcher into
  `WINRM_CRED_DMZ_USERNAME` / `WINRM_CRED_DMZ_PASSWORD`). Entries without these keys use the default account.
- Auth to the servers is Negotiate over HTTP 5985 (message-level encryption); the account password never leaves the host.

## Setup
```powershell
uv venv .venv
uv pip install --link-mode=copy --python .venv\Scripts\python.exe -r requirements.txt
.\Start-WinRmMCP.ps1 -Transport http -Port 3117    # hosted; stdio by default
```
Store the credential as svc-mcp with `Server\MCP-Hosting\Set-McpServiceCredentials.ps1 -Target 'Windows RO'`.
Local stdio testing on a workstation: `-CredentialTarget <your stored target>`.

## Adding a server
1. Deploy the endpoint: `Deploy-ReadOnlyJea.ps1 -ComputerName <fqdn> -AccountName 'CORP\svc-winrm-ro' -Credential <admin> -TestCredential <svc> -WhatIf` (preflight), then without `-WhatIf`.
2. Add `{ "name": "<fqdn>", "note": "..." }` to `servers.json` and restart `MCP-winrm`.

## Adding a function
Add it to `Server/JEA-ReadOnly/ReadOnly` (module + `VisibleFunctions` in the .psrc), redeploy the module,
then add a tool in `server.py` that calls `_run(server, "Get-Ro...", {...})`.

# Authored by Caleb A. Morrow
