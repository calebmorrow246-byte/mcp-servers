# XenServer / Citrix Hypervisor MCP server

**Language:** Python · **Tools:** 62 (counted from source) · **Access:** Capable of writes; read-only enforced by the hypervisor role

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Virtualisation questions (VMs, hosts, storage, networks, tasks, metrics) required XenCenter or the `xe` CLI.

## Why it was built this way
Exposes the XenServer management API over JSON-RPC as 62 tools, including a generic `api_call`. Note: the server *can* issue mutating calls (VM start, shutdown, migrate, destroy, host reboot, and so on, 27 tools by name). The deployment is read-only because the credential has a read-only RBAC role on the hypervisor, verified when a task cancel was refused with `RBAC_PERMISSION_DENIED`. Capability and permission are separate layers: the safe pattern is to hand a human the exact `xe` command for anything beyond read.

## What it improves
Fast, read-only visibility into a virtualisation pool, with a clear model of where the safety actually lives.

---

## Reference

An MCP (Model Context Protocol) server that exposes the XenServer Management API as tools for use with Claude or other MCP-compatible AI assistants.

## Requirements

- Python 3.10+
- XenServer / Citrix Hypervisor 8.x or later (JSON-RPC endpoint at `/jsonrpc`)
- Network access to the XenServer host on port 443

## Installation

```bash
cd C:\Programs\xenserver-mcp
pip install -r requirements.txt
```

## Configuration

Set these environment variables before starting the server (or add them to your Claude Code MCP config):

| Variable | Required | Default | Description |
|---|---|---|---|
| `XENSERVER_HOST` | Yes | — | XenServer hostname or IP address |
| `XENSERVER_USERNAME` | No | `root` | XenServer username |
| `XENSERVER_PASSWORD` | Yes | — | XenServer password |
| `XENSERVER_VERIFY_SSL` | No | `false` | Verify TLS certificate (`true`/`false`) |
| `XENSERVER_TIMEOUT` | No | `60` | Request timeout in seconds |

> **Note:** XenServer uses self-signed TLS certificates by default, so `XENSERVER_VERIFY_SSL` defaults to `false`.  Set it to `true` only if you have a valid certificate installed.

## Claude Code Integration

Add this block to your Claude Code MCP configuration file (`~/.claude/mcp_servers.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "xenserver": {
      "command": "python",
      "args": ["C:\\Programs\\xenserver-mcp\\server.py"],
      "env": {
        "XENSERVER_HOST": "your-xenserver-ip-or-hostname",
        "XENSERVER_USERNAME": "root",
        "XENSERVER_PASSWORD": "your-password",
        "XENSERVER_VERIFY_SSL": "false"
      }
    }
  }
}
```

## Available Tools

### Session
| Tool | Description |
|---|---|
| `connect` | Connect (optionally overriding env vars) |
| `disconnect` | Logout and close session |
| `api_call` | Raw API call (escape hatch for any operation) |

### VM Operations
| Tool | Description |
|---|---|
| `vm_list` | List all VMs (optionally include templates) |
| `vm_get` | Full VM record |
| `vm_start` | Start a VM |
| `vm_shutdown` | Clean or forced shutdown |
| `vm_reboot` | Clean or forced reboot |
| `vm_suspend` | Suspend to disk |
| `vm_resume` | Resume from suspend |
| `vm_pause` | Pause (keep in memory) |
| `vm_unpause` | Unpause |
| `vm_clone` | Fast clone (COW) |
| `vm_copy` | Full independent copy |
| `vm_snapshot` | Disk-only snapshot |
| `vm_checkpoint` | Snapshot + memory |
| `vm_revert` | Revert to snapshot |
| `vm_migrate` | Live migrate to another host |
| `vm_set_memory` | Set memory limits |
| `vm_set_vcpus` | Set vCPU count |
| `vm_set_name` | Rename VM |
| `vm_destroy` | Permanently destroy VM |
| `vm_provision` | Provision from template |
| `vm_get_possible_hosts` | List eligible hosts |
| `vm_get_vbds` | List disk attachments |
| `vm_get_vifs` | List network interfaces |
| `vm_get_console` | Get VNC console URL |

### Host Operations
| Tool | Description |
|---|---|
| `host_list` | List all hosts |
| `host_get` | Full host record |
| `host_enable` | Enable host |
| `host_disable` | Disable host |
| `host_evacuate` | Migrate all VMs off host |
| `host_reboot` | Reboot host |
| `host_shutdown` | Shut down host |
| `host_get_resident_vms` | VMs on a specific host |
| `host_get_free_memory` | Available memory |
| `host_call_plugin` | Call a host plugin |

### Pool Operations
| Tool | Description |
|---|---|
| `pool_get` | Get pool record |
| `pool_get_license_state` | Get license info |

### Storage Repository
| Tool | Description |
|---|---|
| `sr_list` | List all SRs |
| `sr_get` | Full SR record |
| `sr_scan` | Refresh VDI list from backend |
| `sr_get_vdis` | List VDIs in an SR |
| `sr_set_name` | Rename SR |
| `sr_get_supported_types` | List supported SR types |

### Network
| Tool | Description |
|---|---|
| `network_list` | List all networks |
| `network_get` | Full network record |
| `network_create` | Create internal network |
| `network_destroy` | Destroy a network |

### VDI (Virtual Disk Image)
| Tool | Description |
|---|---|
| `vdi_list` | List VDIs (optionally filter by SR) |
| `vdi_get` | Full VDI record |
| `vdi_snapshot` | Read-only snapshot |
| `vdi_clone` | Writable clone |
| `vdi_resize` | Resize disk |
| `vdi_copy` | Copy to different SR |
| `vdi_destroy` | Permanently delete |
| `vdi_set_name` | Rename VDI |

### Physical Interfaces
| Tool | Description |
|---|---|
| `pif_list` | List PIFs (filter by host) |

### Tasks & Alerts
| Tool | Description |
|---|---|
| `task_list` | List pending tasks |
| `task_get` | Task status / result |
| `task_cancel` | Cancel a task |
| `message_list` | Recent system alerts |

## Identifying Objects

Most tools accept a **name label, UUID, or OpaqueRef** to identify VMs, hosts, SRs, networks, and VDIs.

```
vm_get("web-server-01")          # by name label
vm_get("abc123-...")             # by UUID
vm_get("OpaqueRef:1a2b3c...")   # by opaque reference
```

If multiple objects share the same name label, use the UUID or OpaqueRef to disambiguate.

## Raw API Calls

Use `api_call` to call any XenServer API method not covered by the built-in tools:

```json
{
  "method": "VM.set_HVM_boot_policy",
  "params": ["OpaqueRef:...", "BIOS order"]
}
```

The session reference is always prepended automatically.

## Resumability

If the server process is stopped and restarted, it automatically creates a new session on the next tool call using the configured environment variables. No state is lost on the XenServer side.
