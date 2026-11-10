# WP Engine MCP server

**Language:** Python · **Tools:** 27 (counted from source) · **Access:** Read-only by tool selection, plus two approved writes

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
WordPress hosting status (installs, backups, domains, certificates, cache) and per-install SFTP troubleshooting needed the WP Engine portal.

## Why it was built this way
WP Engine's API credential has no read-only scope, so read-only is enforced by which tools are wired up, not by the credential. That means the tool list is the audit surface: review `server.py`, not just test results. Two non-destructive writes are approved (create a backup, purge cache). SFTP tools read per-install credentials on demand from Windows Credential Manager instead of environment variables.

## What it improves
Hosting status and routine troubleshooting from chat, with a small, reviewable write surface.
