# phpIPAM MCP server

**Language:** TypeScript · **Tools:** 13 (counted from source) · **Access:** Read-only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
IP planning ('what is this address?', 'is there a free IP in that subnet?') meant searching the IPAM UI.

## Why it was built this way
Read-only tools for sections, subnets, addresses, VLANs, devices and VRFs, including subnet utilisation and `get_first_free_ip`. TypeScript with the official MCP SDK, matching the other TypeScript servers in this repo.

## What it improves
Address lookups and free-IP planning in one question.

---

## Reference

MCP (Model Context Protocol) server for the [phpIPAM](https://phpipam.net) IP Address Management API.
Provides IP planning and address-lookup tools to Claude.

## Tools

| Tool | Description |
|------|-------------|
| `list_sections` | List all IP address sections (top-level containers) |
| `list_subnets` | List subnets, optionally scoped to a section |
| `search_subnets` | Search subnets by CIDR or description keyword |
| `get_subnet` | Get full details for a subnet by ID |
| `get_subnet_usage` | IP utilization statistics for a subnet |
| `get_first_free_ip` | First available IP in a subnet |
| `list_addresses` | All address assignments in a subnet |
| `search_address` | Look up an IP address across all subnets |
| `list_vlans` | List all VLANs |
| `search_vlans` | Search VLANs by name or number |
| `list_devices` | List all network devices |
| `search_devices` | Search devices by hostname or IP |
| `list_vrfs` | List all VRFs |

## Requirements

- Node.js 20+
- PowerShell 7+ (for Windows Credential Manager integration)
- phpIPAM instance with API access enabled

## Setup

### 1. Store credentials

The server supports two phpIPAM security modes:

**App token mode** (recommended — store the token as the credential password):
```powershell
cmdkey /generic:"a personal API credential" /user:"phpipam" /pass:"<app-token-from-phpipam>"
```

**User token mode** (username + password):
```powershell
cmdkey /generic:"a personal API credential" /user:"<phpipam_user>" /pass:"<phpipam_password>"
```

Override the credential target with `PHPIPAM_CRED_TARGET` env var (default `a personal API credential`).

### 2. Build

```powershell
npm install
npm run build
```

### 3. Run

```powershell
.\Start-PhpIPAMMCP.ps1
```

Or set env vars manually and run directly:
```powershell
$env:PHPIPAM_BASE_URL = "https://ipam.example.com"
$env:PHPIPAM_APP_ID  = "claude"
$env:PHPIPAM_APP_TOKEN = "<token>"   # or set PHPIPAM_USERNAME + PHPIPAM_PASSWORD
node dist/index.js
```

### 4. Claude Code `.mcp.json` entry

```json
{
  "mcpServers": {
    "phpipam": {
      "type": "stdio",
      "command": "pwsh",
      "args": ["-NoProfile", "-NonInteractive", "-File", "C:\\path\\to\\phpipam-mcp-server\\Start-PhpIPAMMCP.ps1"]
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PHPIPAM_BASE_URL` | *(required)* | phpIPAM instance URL |
| `PHPIPAM_APP_ID` | `claude` | API application name |
| `PHPIPAM_APP_TOKEN` | — | Static app token (skips user auth) |
| `PHPIPAM_USERNAME` | — | Username (user token mode) |
| `PHPIPAM_PASSWORD` | — | Password (user token mode) |
| `PHPIPAM_CRED_TARGET` | `a personal API credential` | Windows Credential Manager target |
| `PHPIPAM_INSECURE` | `false` | Skip TLS verification (dev only) |

## Project Structure

```
src/
  index.ts          # MCP server entry point, tool definitions and handlers
  phpipam-client.ts # Typed phpIPAM REST API client
  creds.ts          # Windows Credential Manager credential resolver
Start-PhpIPAMMCP.ps1  # PowerShell launcher (the company standard)
.env.example          # Environment variable reference
```
