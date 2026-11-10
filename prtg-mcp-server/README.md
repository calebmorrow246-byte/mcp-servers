# PRTG Network Monitor MCP server

**Language:** TypeScript · **Tools:** 5 (counted from source) · **Access:** Read-only plus pause/resume

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Triaging a monitoring alarm or silencing sensors for a maintenance window meant a round trip through the PRTG web console.

## Why it was built this way
Five narrow tools: active alarms, sensor detail, sensor list, and pause/resume. The only mutating actions are pause and resume, and pausing requires a reason that is written to PRTG's own audit trail, so every action the assistant takes is traceable in the system of record, not just in agent logs.

## What it improves
Routine alarm checks and maintenance-window pauses without opening the console, with an audit reason on every change.

---

## Reference

An [MCP](https://modelcontextprotocol.io) server for [PRTG Network Monitor](https://www.paessler.com/prtg) that lets Claude Code query alarms, inspect sensors, and pause/resume monitoring — all from natural language.

## Tools

| Tool | Description |
|------|-------------|
| `get_active_alarms` | Return all Down / Warning / Acknowledged sensors |
| `get_sensor_details` | Full detail for a sensor by ID (uptime, last check, etc.) |
| `list_sensors` | List sensors with optional status or name filter |
| `pause_sensor` | Pause a sensor during maintenance (with reason logged to PRTG) |
| `resume_sensor` | Resume a paused sensor |

## Prerequisites

- [Node.js](https://nodejs.org/) 18+
- A PRTG instance with API access enabled
- A PRTG API token (Setup → My Account → API Token)

## Setup

```bash
git clone https://github.com/calebmorrow246-byte/mcp-servers.git
cd prtg-mcp-server
npm install
npm run build
```

## Authentication

The server never stores secrets in config. `Start-PrtgMCP.ps1` resolves the API token at
runtime from **Windows Credential Manager** via the `CredentialManager` PowerShell module
(`Get-StoredCredential`), matching the the company credential standard used by the Qualys and
Freshservice MCP servers — the token is injected into the environment only for the child
node process and cleared afterward.

Store the token once:

```
cmdkey /generic:"PRTG API" /user:apitoken /pass:<your-api-token>
```

`Start-PrtgMCP.ps1` also sets `PRTG_BASE_URL` and `PRTG_INSECURE` for this deployment — edit
the script directly if either needs to change.

## Claude Code Integration

Register the launcher script (not `node` directly) as the MCP command, so the token is
pulled from Credential Manager instead of sitting in `.mcp.json` / `settings.json`:

```json
{
  "mcpServers": {
    "prtg": {
      "type": "stdio",
      "command": "pwsh.exe",
      "args": [
        "-NonInteractive",
        "-NoProfile",
        "-Command",
        "& '/path/to/mcp-servers/prtg-mcp-server/Start-PrtgMCP.ps1'"
      ]
    }
  }
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PRTG_BASE_URL` | Yes | Base URL of your PRTG server. Set in `Start-PrtgMCP.ps1` for this deployment. |
| `PRTG_API_TOKEN` | Yes | PRTG API token. Resolved from Credential Manager by the launcher — set directly only for local/CI testing (`npm start`). |
| `PRTG_INSECURE` | No | Set `true` to allow self-signed TLS certs (default: `false`). Set in `Start-PrtgMCP.ps1` for this deployment. |

## Generating a PRTG API Token

1. Log in to PRTG
2. Go to **Setup → My Account**
3. Click the **API Token** tab
4. Click **Add API Token**, give it a name, and copy the token

Each user should generate their own token — do not share tokens.
