# Valimail (DMARC / DKIM / SPF) MCP server

**Language:** TypeScript · **Tools:** 26 (counted from source) · **Access:** Read and write

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Managing email-authentication domains, DKIM keys, approved senders and DMARC reports meant clicking through Valimail's UI.

## Why it was built this way
Covers the Configuration API (domains, senders, DKIM, netblocks: read and write) and the Reporting Data API (DMARC and TLS reporting). Credentials come from Windows Credential Manager, using the same TypeScript pattern as the PRTG and Qualys servers.

## What it improves
Email-authentication changes and reporting in one natural-language workflow. Review write tools before enabling them against production.

---

## Reference

An MCP (Model Context Protocol) server exposing Valimail's **Configuration API** and
**Reporting Data API** to Claude — DMARC/DKIM/SPF domain configuration, sender approval,
and DMARC/TLS reporting.

Built to match the `prtg-mcp-server` / `qualys-mcp-server` pattern (TypeScript,
`@modelcontextprotocol/sdk`, stdio transport, credentials from Windows Credential Manager).

## Tools

### Configuration (read/write)

| Tool | Endpoint | What it does |
|------|----------|--------------|
| `list_domains` | `GET /accounts/{slug}/domains` | List domains/subdomains with DMARC record, policy, enforcement & sending status. Filterable. |
| `get_domain` | `GET .../domains/{domain}` | Full detail for one domain. |
| `create_domain` | `POST .../domains` | Add a domain/subdomain. |
| `update_domain` | `PUT .../domains/{domain}` | Update DMARC policy and/or sending status. |
| `delete_domain` | `DELETE .../domains/{domain}` | **Destructive.** Remove a domain and its config. Requires `confirm: true`. |
| `list_senders` | `GET .../domains/{domain}/senders` | List senders linked to a domain and their approval status. |
| `get_sender` | `GET .../senders/{sender-slug}` | Detail for one linked sender. |
| `create_sender` | `POST .../domains/{domain}/senders` | Link a new sender to a domain (pending_approval). |
| `update_sender_status` | `PUT .../senders/{sender-slug}` | Approve / deny / reset a sender. |
| `list_available_senders` | `GET /resource/senders` | Catalog of every sender Valimail knows about. |
| `list_domain_dkims` | `GET .../domains/{domain}/dkims` | List DKIM records for a domain. |
| `get_domain_dkim` | `GET .../dkims/{selector}` | Detail for one DKIM record. |
| `create_domain_dkim` | `POST .../domains/{domain}/dkims` | Create a DKIM record (public key or CNAME target). |
| `update_domain_dkim` | `PUT .../dkims/{selector}` | Update a DKIM record's comment/owners/linked sender. |
| `list_netblocks` | `GET .../domains/{domain}/netblocks` | List SPF-authorized IP ranges for a domain. |
| `get_netblock` | `GET .../netblocks/{netblock}` | Detail for one netblock. |
| `create_netblock` | `POST .../domains/{domain}/netblocks` | Add an SPF-authorized netblock. |
| `update_netblock` | `PUT .../netblocks/{netblock}` | Update a netblock's comment/associated sender. |

### Reporting (read-only)

| Tool | Endpoint | What it does |
|------|----------|--------------|
| `get_domains_report` | `GET .../reports/domains` | Reporting-API view of domains (same filters as `list_domains`). |
| `get_senders_report` | `GET .../reports/senders` | DMARC compliance per sending source over a date range: volume, pass/fail, SPF alignment, quarantine/reject counts. |
| `get_unidentified_report` | `GET .../reports/unidentified` | Unattributed traffic over a date range — spot shadow IT or spoofing. |
| `get_events_report` | `GET .../reports/events` | Configuration change audit log (domain/DKIM/policy/user changes). |
| `get_dkim_continuous_protection_report` | `GET .../reports/continuous-protection/dkim` | DKIM key inventory with upload/last-seen dates — find stale keys. |
| `get_senders_continuous_protection_report` | `GET .../reports/continuous-protection/senders` | Sending-source inventory with last-seen date and volume. |
| `get_tls_report` | `GET .../reports/mta-sts/tls` | MTA-STS/TLS reporting summary (policy mode, MX host, cache age). |
| `get_tls_failure_details` | `GET .../reports/mta-sts/tls/failure-details` | TLS session failure detail for a specific report ID. |

**Deliberately out of scope** (not needed for the DMARC reporting/configuration workflow this
was built for — add later if needed):
- Sender-level DKIM (`.../senders/{sender-slug}/dkims`) — domain-level DKIM covers the
  common case; the sender-scoped variant has the same shape.
- MTA-STS / TLS-RPT **policy** create/update (`.../mta_sts_policy`, `.../smtp_tls_policy`) —
  only the *reporting* side of MTA-STS/TLS is wired up above.
- SCIM user management (`.../scim/v2/Users`) — account/user administration, not DMARC config.

## Authentication

Valimail's API key is a **client-id / app-id pair** (shown once when the key is created in
**Account Settings → API Keys**, with Key Access set to Configuration, Reporting, or Both).
The server exchanges that pair for a short-lived bearer token via `POST /auth` and caches it
until shortly before expiry.

The server never stores secrets in config. At startup it resolves the pair from **Windows
Credential Manager** via the `CredentialManager` PowerShell module (`Get-StoredCredential`),
matching the the company credential standard — client-id as the stored username, app-id as the
stored password:

```
cmdkey /generic:"Valimail API" /user:<client-id> /pass:<app-id>
```

## Configuration

Environment variables (see `.env.example`):

| Var | Required | Default | Notes |
|-----|----------|---------|-------|
| `VALIMAIL_ACCOUNT_SLUG` | **yes** | — | The string after `/app/` in the URL once logged into Valimail. Unsure? Ask support@valimail.com. |
| `VALIMAIL_BASE_URL` | no | `https://api.valimail.com` | Both the Config and Reporting APIs live on this same host. |
| `VALIMAIL_CRED_TARGET` | no | `Valimail API` | Credential Manager target name. |
| `VALIMAIL_INSECURE` | no | `false` | `true` skips TLS verification (not recommended). |
| `VALIMAIL_CLIENT_ID` / `VALIMAIL_APP_ID` | no | — | Bypass Credential Manager (test/CI only). |

`Start-ValimailMCP.ps1` already sets `$env:VALIMAIL_ACCOUNT_SLUG` to this deployment's account
slug (`example-account`) — edit the script directly if the account ever changes.

## Build & run

```powershell
npm install
npm run build
# Smoke test:
$env:VALIMAIL_ACCOUNT_SLUG = "your-account-slug"; npm start
```

## Register with Claude Code

Add to a project-scoped `.mcp.json` (or `claude mcp add`), pointing at the launcher script
so the credential is pulled from Credential Manager rather than sitting in config:

```json
{
  "mcpServers": {
    "valimail": {
      "type": "stdio",
      "command": "pwsh",
      "args": [
        "-NoProfile",
        "-File",
        "/path/to/mcp-servers/valimail-mcp-server/Start-ValimailMCP.ps1"
      ]
    }
  }
}
```

## Notes

- `delete_domain` is destructive and irreversible via the API — it requires an explicit
  `confirm: true` argument as a safety guard against an agent calling it unprompted.
- The Config and Reporting APIs are documented as two separate Swagger specs
  (`https://api.valimail.com/docs/config.html` / `.../docs/reports.html`) but resolve to the
  same host and appear to accept the same bearer token, so this server uses one client-id/app-id
  pair and one cached token for both. If your key is scoped to only one of Configuration or
  Reporting, calls to the other API's tools will fail with a 401/403 from Valimail — that's
  expected, not a bug in this server.
