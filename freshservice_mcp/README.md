# Freshservice (ITSM) MCP server

**Language:** Python · **Tools:** 98 (counted from source) · **Access:** Broad: read and write

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Routine service-desk work (finding and updating tickets, change requests, assets, requesters and knowledge-base articles) meant working the web UI one record at a time.

## Why it was built this way
A single FastMCP server exposes the Freshservice API as 98 tools (about 40 can create, update or delete). The launcher resolves the API key from Windows Credential Manager at start-up, so the key never sits in a client config. Its breadth is also why the AI-Triage app (see the `freshservice-ai-triage` repo) was built as a separate, tightly scoped platform app rather than reusing this server: a tool that fires on every ticket should not inherit full read/write/delete.

## What it improves
Ticket, change and asset operations through natural language for interactive technician work. No automated test suite yet; that is the next hardening step.

---

## Reference

## About This Repository

MCP (Model Context Protocol) server used internally to give Claude and other MCP-compatible AI agents structured access to a Freshservice ITSM instance (tickets, changes, assets, requesters, agents, canned responses, workspaces, and the knowledge base).

## the company Deployment

This internal deployment runs via `Start-FreshserviceMCP.ps1` instead of `uvx` directly, so
the API key never sits in Claude config. The launcher resolves it at runtime from **Windows
Credential Manager** (matching the credential standard used by the other the company MCP
servers), injects it into the environment for the child process only, and clears it
afterward.

Store the key once:

```
cmdkey /generic:FreshserviceAPI /user:apikey /pass:<your-api-key>
```

Register the launcher (not `uvx`/the raw executable) as the MCP command:

```json
{
  "mcpServers": {
    "freshservice": {
      "type": "stdio",
      "command": "pwsh.exe",
      "args": [
        "-NonInteractive",
        "-NoProfile",
        "-Command",
        "& '/path/to/mcp-servers/freshservice_mcp/Start-FreshserviceMCP.ps1'"
      ]
    }
  }
}
```

The launcher hardcodes `FRESHSERVICE_DOMAIN` to `example.freshservice.com` — edit the
script directly if that ever needs to change. The generic `uvx`/Smithery/Claude Desktop
instructions below are upstream's and don't apply to this deployment.

## Overview

A powerful MCP (Model Context Protocol) server implementation that seamlessly integrates with Freshservice, enabling AI models to interact with Freshservice modules and perform various IT service management operations. This integration bridge empowers your AI assistants to manage and resolve IT service tickets, streamlining your support workflow.

## Key Features

- **Enterprise-Grade Freshservice Integration**: Direct, secure communication with Freshservice API endpoints
- **AI Model Compatibility**: Enables Claude and other AI models to execute service desk operations through Freshservice
- **Automated ITSM Management**: Efficiently handle ticket creation, updates, responses, and asset management
- **Workflow Acceleration**: Reduce manual intervention in routine IT service tasks

## Supported Freshservice Modules

**This MCP server currently supports operations across a wide range of Freshservice modules**:

-  Tickets
-  Changes
-  Conversations
-  Products
-  Requesters
-  Agents
-  Agent Groups
-  Requester Groups
-  Canned Responses
-  Canned Response Folders
-  Workspaces
-  Solution Categories
-  Solution Folders
-  Solution Articles

## Components & Tools

The server provides a comprehensive toolkit for Freshservice operations:

### Ticket Management

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_ticket` | Create new service tickets | `subject`, `description`, `source`, `priority`, `status`, `email` |
| `update_ticket` | Update existing tickets | `ticket_id`, `updates` |
| `delete_ticket` | Remove tickets | `ticket_id` |
| `filter_tickets` | Find tickets matching criteria | `query` |
| `get_ticket_fields` | Retrieve ticket field definitions | None |
| `get_tickets` | List all tickets with pagination | `page`, `per_page` |
| `get_ticket_by_id` | Retrieve single ticket details | `ticket_id` |

### Change Management

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_changes` | List all changes with pagination | `page`, `per_page`, `query` |
| `filter_changes` | Filter changes with advanced queries | `query`, `page`, `per_page` |
| `get_change_by_id` | Retrieve single change details | `change_id` |
| `create_change` | Create new change request | `requester_id`, `subject`, `description`, `priority`, `impact`, `status`, `risk`, `change_type` |
| `update_change` | Update existing change | `change_id`, `change_fields` |
| `close_change` | Close change with result explanation | `change_id`, `change_result_explanation` |
| `delete_change` | Remove change | `change_id` |
| `get_change_tasks` | Get tasks for a change | `change_id` |
| `create_change_note` | Add note to change | `change_id`, `body` |

#### 🚨 Important: Query Syntax for Filtering

When using `get_changes` or `filter_changes` with the `query` parameter, **the query string must be wrapped in double quotes** for the Freshservice API to work correctly:

✅ **CORRECT**: `"status:3"`, `"approval_status:1 AND status:<6"`  
❌ **WRONG**: `status:3` (will cause 500 Internal Server Error)

**Common Query Examples:**
- `"status:3"` - Changes awaiting approval
- `"approval_status:1"` - Approved changes  
- `"approval_status:1 AND status:<6"` - Approved changes that are not closed
- `"planned_start_date:>'2025-07-14'"` - Changes starting after specific date
- `"status:3 AND priority:1"` - High priority changes awaiting approval

## Getting Started

### Prerequisites

- A Freshservice account (sign up at [freshservice.com](https://www.freshservice.com))
- Freshservice API key
- `uvx` installed (`pip install uv` or `brew install uv`)

### Configuration

1. Generate your Freshservice API key from the admin panel:
   - Navigate to Profile Settings → API Settings
   - Copy your API key for configuration

2. Set up your domain and authentication details as shown below

### Usage with Claude Desktop

1. Install Claude Desktop from the [official website](https://claude.ai/desktop)
2. Add the following configuration to your `claude_desktop_config.json`:

```json
"mcpServers": {
  "freshservice-mcp": {
    "command": "uvx",
    "args": [
        "freshservice-mcp"
    ],
    "env": {
      "FRESHSERVICE_APIKEY": "<YOUR_FRESHSERVICE_APIKEY>",
      "FRESHSERVICE_DOMAIN": "<YOUR_FRESHSERVICE_DOMAIN>"
    }
  }
}
```
**Important**: Replace `<YOUR_FRESHSERVICE_APIKEY>` with your actual API key and `<YOUR_FRESHSERVICE_DOMAIN>` with your domain (e.g., `yourcompany.freshservice.com`)

## Example Operations

Once configured, you can ask Claude to perform operations like:

**Tickets:**
- "Create a new incident ticket with subject 'Network connectivity issue in Marketing department' and description 'Users unable to connect to Wi-Fi in Marketing area', set priority to high"
- "List all critical incidents reported in the last 24 hours"
- "Update ticket #12345 status to resolved"

**Changes:**
- "Create a change request for scheduled server maintenance next Tuesday at 2 AM"
- "Update the status of change request #45678 to 'Approved'"
- "Close change #5092 with result explanation 'Successfully deployed to production. All tests passed.'"
- "List all pending changes"

**Other Operations:**
- "Show asset details for laptop with asset tag 'LT-2023-087'"
- "Create a solution article about password reset procedures"

## Testing

For testing purposes, you can start the server manually:

```bash
uvx freshservice-mcp --env FRESHSERVICE_APIKEY=<your_api_key> --env FRESHSERVICE_DOMAIN=<your_domain>
```

## Troubleshooting

- Verify your Freshservice API key and domain are correct
- Ensure proper network connectivity to Freshservice servers
- Check API rate limits and quotas
- Verify the `uvx` command is available in your PATH

## Additional Resources

- [Freshservice API Documentation](https://api.freshservice.com/)
- [Claude Desktop Integration Guide](https://docs.anthropic.com/claude/docs/claude-desktop)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
