# Commvault MCP server

**Language:** Python · **Tools:** 14 (counted from source) · **Access:** Read-only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Checking backup health meant opening the Commvault console and clicking through jobs, clients and alerts one view at a time.

## Why it was built this way
Wraps the Commvault REST API with read-only tools (jobs, failed jobs, clients, servers, events, alerts, storage pools, plans, subclients, CommCell overview). Endpoints were verified against a real CommServe 11.40 instead of assumed from documentation: the classic Command Center API and the V4 endpoints that exist on that version are used, and the lowercase `/v4/...` paths that 404 there are avoided. Setup note: on this deployment the API is served by the Command Center web server, not the CommServe itself. A generic `api_call` tool exists for uncovered endpoints and accepts GET only.

## What it improves
Answers 'what failed overnight and where?' in one question instead of a console walk-through.
