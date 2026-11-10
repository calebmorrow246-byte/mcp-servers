# NetApp ONTAP MCP server

**Language:** Python · **Tools:** 29 (counted from source) · **Access:** Read-only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Storage capacity and health questions (aggregates, volumes, snapshots, disks) required the ONTAP System Manager or CLI and manual correlation.

## Why it was built this way
Wraps the ONTAP REST API with list/get tools for the cluster, nodes, aggregates, volumes, qtrees, disks, shelves, snapshots, snapshot policies and SVMs. The client issues only GET requests (no POST, PUT, PATCH or DELETE calls exist in it), and a read-only ONTAP account is expected.

## What it improves
Fast, safe capacity and snapshot review across a storage cluster from a prompt.
