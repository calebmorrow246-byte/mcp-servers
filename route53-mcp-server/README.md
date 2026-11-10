# AWS Route 53 MCP server

**Language:** TypeScript · **Tools:** 3 (counted from source) · **Access:** Read-only (no write path exists)

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
DNS investigations (for example DKIM CNAME checks) relied on ad-hoc CLI calls with hand-loaded credentials.

## Why it was built this way
Three tools (list hosted zones, get a zone, list record sets), all auto-paginated, over the AWS SDK. It is read-only by absence, not by flag: there is no create, update or delete tool anywhere in the code, so there is no path to exercise by accident. Credentials come from Windows Credential Manager via the launcher and should be a read-only IAM user.

## What it improves
Repeatable DNS lookups without hand-run CLI commands or exposed credentials.
