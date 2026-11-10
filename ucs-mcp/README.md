# Cisco UCS Manager MCP server

**Language:** Python · **Tools:** 10 (counted from source) · **Access:** Read-only by construction

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Blade, service-profile and fault status required UCS Manager or ad-hoc PowerShell.

## Why it was built this way
Uses UCS Manager's XML API (login, resolve class or DN, logout) with a read-only account and a self-signed certificate handled explicitly. Tools: blades, rack servers, service profiles, chassis, fabric interconnects, firmware, faults, plus generic object and class resolution. No config-changing XML methods are implemented.

## What it improves
Hardware and fault inventory from chat, with no way to alter configuration.

---

## Reference

MCP server for **Cisco UCS Manager** (`ucs-manager.example.com`), hosted on mcp-host.


## What's known
- Read-only UCS Manager **XML API**: `aaaLogin` -> `configResolveClass` / `configResolveDn` -> `aaaLogout` (UCSM uses a self-signed cert).
- Credential: Credential Manager target `UCS RO`.
- Candidate tools: blades/rack servers (model, serial, power, association, faults), service profiles and their association, chassis, fabric interconnects, faults by severity, firmware versions, and vNIC/vHBA state.

## Hosting (hosting standard)
- **Credential type:** service account, read-only (`UCS RO`, stored for svc-mcp).
- **Port:** 3114. Route: `https://mcp-host.example.com/mcp/ucs`.
- Standard transport helper, NSSM service `MCP-ucs` as svc-mcp, `.mcp.json` entry with headersHelper. Read-only by construction: no config-changing XML methods.
