# Device42 (CMDB) MCP server

**Language:** Python · **Tools:** 21 (counted from source) · **Access:** Read-only, plus one guarded write

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Device, IP, subnet, rack and VLAN questions needed the CMDB web UI, and asset records drifted because updating them was tedious.

## Why it was built this way
Read tools cover devices, IPs, subnets, VLANs, buildings, rooms, racks, hardware models, assets and interfaces using a shared read-only service account, with TLS verification on. The single write tool, `update_devices`, is deliberately fenced: it only writes when the caller supplies their *own* Device42 login in request headers, so the CMDB attributes the change to that person; it defaults to a dry run, only touches an allow-listed set of fields, takes at most 25 devices per call, has no delete, and appends every write to a change log.

## What it improves
Fast infrastructure lookups from chat, and a safe path for bulk record corrections with a per-person audit trail.
