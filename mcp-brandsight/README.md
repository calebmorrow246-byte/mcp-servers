# BrandSight domain management MCP server

**Language:** TypeScript · **Tools:** 23 (counted from source) · **Access:** Read and write (writes default to dry run)

> Part of the [`mcp-servers`](../README.md) collection. Scrubbed of identifying information (hosts, tenants, accounts, addresses are placeholders).

## Why this exists
Domain lookups, DNS edits and renewals were done in the registrar portal, which is slow and easy to get wrong across a large domain portfolio.

## Why it was built this way
Wraps the BrandSight (GoDaddy reseller) API, with production and OTE test endpoints. Read tools are side-effect free. Every write tool (updates, nameservers, DNS records, contacts, privacy, renew, register, transfer) defaults to `dry_run: true` and returns a preview of the current state and what would change; the caller must pass `dry_run: false` explicitly to execute.

## What it improves
Domain and DNS administration in one natural-language workflow, with a preview-before-change guard on anything that mutates.

---

## Reference

An MCP (Model Context Protocol) server for BrandSight domain management, letting Claude query and manage domains, DNS, and registration lifecycle. BrandSight is built on the GoDaddy reseller API (`api.godaddy.com` / `api.ote-godaddy.com` for the OTE test environment).

## Tools

### Read (safe, no side effects)

| Tool | What it does |
|------|--------------|
| `list_domains` | List domains in the account, filterable by status, status group, expiry, or modified date |
| `get_domain` | Full detail for a single domain (status, expiry, nameservers, renewal info) |
| `check_domain_availability` | Check if a single domain name is available for registration |
| `bulk_check_availability` | Check availability for multiple domain names at once |
| `get_dns_records` | Retrieve DNS records for a domain, optionally filtered by type/name |
| `list_domain_actions` | List pending/recent lifecycle actions on a domain (registrations, renewals, transfers) |
| `get_domain_action` | Status and detail for a specific action on a domain |
| `check_transfer_availability` | Check whether a domain is eligible to transfer into BrandSight |
| `get_contact_schema` | Required contact fields/validation rules for a TLD |
| `get_registration_schema` | Registration requirements (required fields, allowed values) for a TLD |

### Write (all default to `dry_run: true`)

| Tool | What it does |
|------|--------------|
| `update_domain` | Update auto-renewal or registrar lock |
| `update_nameservers` | Replace all nameservers for a domain |
| `renew_domain` | Renew a domain registration |
| `update_contacts` | Update registrant/admin/billing/tech contact info |
| `enable_privacy` | Enable WHOIS privacy protection |
| `disable_privacy` | Disable WHOIS privacy protection (registrant details become public) |
| `add_dns_records` | Add DNS records without touching existing ones |
| `replace_dns_records` | Replace all records of a given type/name |
| `delete_dns_records` | Delete all records of a given type/name |
| `register_domain` | Register a new domain (`dry_run` runs API validation only, no charge) |
| `transfer_domain` | Transfer a domain into BrandSight (`dry_run` checks eligibility only) |
| `cancel_domain_action` | Cancel a pending action (e.g. an in-progress transfer) |
| `regenerate_auth_code` | Regenerate a domain's EPP/auth code (invalidates the old one immediately) |

Every write tool defaults to `dry_run: true` and returns a preview (current state, what would change) instead of making the call. Pass `dry_run: false` explicitly to execute.

## Authentication

Set these environment variables — the server reads them directly from `process.env`, no Credential Manager integration yet:

| Var | Required | Default | Notes |
|-----|----------|---------|-------|
| `BRANDSIGHT_API_KEY` | **yes** | — | GoDaddy/BrandSight API key |
| `BRANDSIGHT_API_SECRET` | **yes** | — | API secret paired with the key |
| `BRANDSIGHT_CUSTOMER_ID` | **yes** | — | Customer/shopper ID |
| `BRANDSIGHT_ENVIRONMENT` | no | `production` | `production` or `ote` (test environment) |

## Build & run

```powershell
npm install
npm run build
npm start
```

## Register with Claude Code

```json
{
  "mcpServers": {
    "brandsight": {
      "type": "stdio",
      "command": "node",
      "args": ["/path/to/mcp-servers/mcp-brandsight/dist/index.js"],
      "env": {
        "BRANDSIGHT_API_KEY": "your-api-key",
        "BRANDSIGHT_API_SECRET": "your-api-secret",
        "BRANDSIGHT_CUSTOMER_ID": "your-customer-id"
      }
    }
  }
}
```

Prefer pulling the key/secret from Windows Credential Manager at runtime (the pattern used by the other the company MCP servers) rather than embedding them in config — add a launcher script if this server sees regular use.
