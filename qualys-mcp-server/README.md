# Qualys MCP server

**Language:** TypeScript · **Tools:** 7 (counted from source) · **Access:** Read-only

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Vulnerability remediation work needs Qualys data (detections by host, QID details, scans, assets, web-app findings) cross-referenced with other systems, which was manual.

## Why it was built this way
Read-only tools over VMDR host detections (filterable by asset tag, IP, severity, QID and status), the KnowledgeBase, VM scans, host assets, tags, and Web Application Scanning. Built to the same pattern as the PRTG server (TypeScript, official MCP SDK).

## What it improves
Remediation lists and vulnerability lookups driven directly by scan data, in natural language.

---

## Reference

An MCP (Model Context Protocol) server that exposes read-only Qualys data to Claude —
VMDR vulnerability detections, the KnowledgeBase, VM scans, host asset inventory, and
Web Application Scanning (WAS) results.

Built to match the `prtg-mcp-server` pattern (TypeScript, `@modelcontextprotocol/sdk`,
stdio transport).

## Tools

| Tool | Qualys API | What it does |
|------|-----------|--------------|
| `list_host_detections` | VMDR Host List Detection (`/api/2.0/fo/asset/host/vm/detection/`) | Vulnerabilities (QIDs) detected per host, filterable by **asset tag**, IP, severity, QID, status. |
| `get_vulnerability_info` | KnowledgeBase (`/api/2.0/fo/knowledge_base/vuln/`) | QID/CVE details: title, severity, CVEs, diagnosis, solution. |
| `list_scans` | Scan List (`/api/2.0/fo/scan/`) | VM scan status, launch time, duration, target. |
| `list_host_assets` | Host List (`/api/2.0/fo/asset/host/`) | Asset inventory: IP, DNS, NetBIOS, OS, **tags**, tracking, last scan. Filterable by **asset tag**. |
| `list_tags` | AM Tagging (`/qps/rest/2.0/search/am/tag`) | List asset tags and their IDs (e.g. `LF_Server_*`). |
| `list_web_apps` | WAS Search WebApp (`/qps/rest/3.0/search/was/webapp`) | Configured web applications and their IDs. |
| `list_was_findings` | WAS Search Finding (`/qps/rest/3.0/search/was/finding`) | Web-app findings, filterable by web app, severity, status. |

All tools are **read-only**, consistent with the read-only `Qualys RO` API account.

### Filtering by asset tag

`list_host_detections` and `list_host_assets` accept a `tags` parameter (comma-separated
tag **names**, e.g. `LF_Server_Infra,LF_Server_Security`) plus an optional `tag_match`
(`any` = host has at least one tag, the default; `all` = host has every tag). When `tags`
is set it replaces the `ips` filter (Qualys treats them as alternative selection modes).
Every host row also reports the tags it carries. Use `list_tags` to discover exact names.

## Authentication

The server never stores secrets in config. At startup it resolves the Qualys API
username/password from **Windows Credential Manager** via the `CredentialManager`
PowerShell module (`Get-StoredCredential`), matching the the company credential standard.

Store the credential once (already done for `Qualys RO`):

```
cmdkey /generic:"Qualys RO" /user:<qualys_user> /pass:<qualys_password>
```

All Qualys calls use HTTP Basic auth plus the required `X-Requested-With` header.

## Configuration

Environment variables (see `.env.example`):

| Var | Required | Default | Notes |
|-----|----------|---------|-------|
| `QUALYS_BASE_URL` | **yes** | — | Your platform/POD API URL, e.g. `https://qualysapi.qg3.apps.qualys.com`. |
| `QUALYS_CRED_TARGET` | no | `Qualys RO` | Credential Manager target name. |
| `QUALYS_KB_VERSION` | no | `2.0` | Set `3.0` if the KnowledgeBase tool returns a deprecation error. |
| `QUALYS_INSECURE` | no | `false` | `true` skips TLS verification (not recommended). |
| `QUALYS_USERNAME` / `QUALYS_PASSWORD` | no | — | Bypass Credential Manager (test/CI only). |

## Build & run

```powershell
npm install
npm run build
# Smoke test:
$env:QUALYS_BASE_URL = "https://qualysapi.qg3.apps.qualys.com"; npm start
```

## Register with Claude Code

Add to a project-scoped `.mcp.json` (or `claude mcp add`):

```json
{
  "mcpServers": {
    "qualys": {
      "type": "stdio",
      "command": "C:/Program Files/nodejs/node.exe",
      "args": [
        "/path/to/mcp-servers/qualys-mcp-server/dist/index.js"
      ],
      "env": {
        "QUALYS_BASE_URL": "https://qualysapi.qg3.apps.qualys.com"
      }
    }
  }
}
```

## Notes / future work

- **Asset Management**: this server uses the classic Host List API for inventory (same host
  and Basic auth as VMDR). The newer GAV/CSAM API (`/rest/2.0/search/am/asset`) lives on a
  separate **gateway** host and uses **JWT bearer** auth — can be added as a second client if
  richer CSAM inventory is needed.
- **WAS scan launches** and other write actions are intentionally omitted (read-only account).
