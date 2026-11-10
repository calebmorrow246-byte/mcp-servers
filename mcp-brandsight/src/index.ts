import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { startServer } from "./transport.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { BrandSightClient, type Environment } from "./client.js";

// ── Credentials ──────────────────────────────────────────────────────────────

function getClient(): BrandSightClient {
  const apiKey = process.env.BRANDSIGHT_API_KEY;
  const apiSecret = process.env.BRANDSIGHT_API_SECRET;
  const customerId = process.env.BRANDSIGHT_CUSTOMER_ID;
  const environment = (process.env.BRANDSIGHT_ENVIRONMENT ?? "production") as Environment;

  if (!apiKey || !apiSecret || !customerId) {
    throw new Error(
      "Missing BrandSight credentials. Set the following environment variables:\n" +
        "  BRANDSIGHT_API_KEY       — your API key\n" +
        "  BRANDSIGHT_API_SECRET    — your API secret\n" +
        "  BRANDSIGHT_CUSTOMER_ID   — your customer/shopper ID\n" +
        "  BRANDSIGHT_ENVIRONMENT   — 'production' or 'ote' (default: production)"
    );
  }

  return new BrandSightClient(apiKey, apiSecret, customerId, environment);
}

// ── Tool definitions ──────────────────────────────────────────────────────────

const TOOLS: Tool[] = [
  // ── Read tools ──────────────────────────────────────────────────────────
  {
    name: "list_domains",
    description: "List all domains in the BrandSight account with optional filtering by status, expiry date, or pagination.",
    inputSchema: {
      type: "object",
      properties: {
        statuses: {
          type: "array",
          items: {
            type: "string",
            enum: [
              "ACTIVE", "CANCELLED", "EXPIRED", "FAILED", "LOCKED_REGISTRAR",
              "PARKED", "HELD_REGISTRAR", "PENDING_TRANSFER", "PENDING_REGISTRATION",
              "REPOSSESSED", "SUSPENDED", "TRANSFERRED",
            ],
          },
          description: "Filter by specific domain statuses",
        },
        statusGroups: {
          type: "array",
          items: { type: "string", enum: ["PENDING", "REGISTERED", "PENDING_TERMINAL", "TERMINAL"] },
          description: "Filter by status group",
        },
        limit: { type: "number", description: "Max results to return (max 500)" },
        marker: { type: "string", description: "Domain name to use as pagination cursor" },
        expiresAtBefore: { type: "string", description: "ISO-8601 date — return domains expiring before this date" },
        modifiedAtAfter: { type: "string", description: "ISO-8601 date — return domains modified after this date" },
        includes: {
          type: "array",
          items: { type: "string", enum: ["actions", "authCode", "contacts", "dnssecRecords"] },
          description: "Extra fields to include in the response",
        },
      },
    },
  },
  {
    name: "get_domain",
    description: "Get full details for a specific domain including status, expiry, nameservers, and renewal info.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name (e.g. example.com)" },
        includes: {
          type: "array",
          items: { type: "string", enum: ["actions", "authCode", "contacts", "dnssecRecords"] },
          description: "Extra fields to include",
        },
      },
    },
  },
  {
    name: "check_domain_availability",
    description: "Check if a single domain name is available for registration.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name to check (e.g. example.com)" },
      },
    },
  },
  {
    name: "bulk_check_availability",
    description: "Check availability for multiple domain names in a single request.",
    inputSchema: {
      type: "object",
      required: ["domains"],
      properties: {
        domains: {
          type: "array",
          items: { type: "string" },
          description: "List of domain names to check",
        },
      },
    },
  },
  {
    name: "get_dns_records",
    description: "Retrieve DNS records for a domain. Optionally filter by record type and name.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        type: { type: "string", description: "DNS record type (A, AAAA, CNAME, MX, TXT, NS, SRV, etc.)" },
        name: { type: "string", description: "Record name — only used when type is also provided" },
      },
    },
  },
  {
    name: "list_domain_actions",
    description: "List all pending or recent lifecycle actions on a domain (registrations, renewals, transfers, etc.).",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name" },
      },
    },
  },
  {
    name: "get_domain_action",
    description: "Get the current status and details of a specific action on a domain.",
    inputSchema: {
      type: "object",
      required: ["domain", "type"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        type: {
          type: "string",
          description: "Action type (e.g. REGISTER, RENEW, TRANSFER_IN, DOMAIN_UPDATE)",
        },
      },
    },
  },
  {
    name: "check_transfer_availability",
    description: "Check whether a domain is eligible to be transferred into BrandSight.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name to check for transfer eligibility" },
      },
    },
  },
  {
    name: "get_contact_schema",
    description: "Get the required contact fields and validation rules for a specific TLD.",
    inputSchema: {
      type: "object",
      required: ["tld"],
      properties: {
        tld: { type: "string", description: "TLD to get the contact schema for (e.g. com, net, io, uk)" },
      },
    },
  },
  {
    name: "get_registration_schema",
    description: "Get the registration requirements (required fields, allowed values) for a specific TLD.",
    inputSchema: {
      type: "object",
      required: ["tld"],
      properties: {
        tld: { type: "string", description: "TLD to get the registration schema for" },
      },
    },
  },

  // ── Write tools (dry_run guardrail) ────────────────────────────────────
  {
    name: "update_domain",
    description:
      "Update domain settings such as auto-renewal or registrar lock. " +
      "Defaults to dry_run: true — preview changes before applying.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        renewAuto: { type: "boolean", description: "Enable or disable auto-renewal" },
        locked: { type: "boolean", description: "Lock (true) or unlock (false) the domain against transfers" },
        dry_run: {
          type: "boolean",
          default: true,
          description: "Preview the change without applying it (default: true). Set false to execute.",
        },
      },
    },
  },
  {
    name: "update_nameservers",
    description:
      "Replace all nameservers for a domain. " +
      "Defaults to dry_run: true — preview before applying.",
    inputSchema: {
      type: "object",
      required: ["domain", "nameServers"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        nameServers: {
          type: "array",
          items: { type: "string" },
          description: "Full replacement nameserver list (e.g. ['ns1.example.com', 'ns2.example.com'])",
        },
        dry_run: { type: "boolean", default: true, description: "Preview without applying (default: true)" },
      },
    },
  },
  {
    name: "renew_domain",
    description:
      "Renew a domain registration. Fetches current expiry to show in the preview. " +
      "Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name to renew" },
        period: { type: "number", description: "Years to renew for (default: 1)" },
        dry_run: { type: "boolean", default: true, description: "Preview without executing (default: true)" },
      },
    },
  },
  {
    name: "update_contacts",
    description:
      "Update registrant, admin, billing, or tech contact information for a domain. " +
      "Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain", "contacts"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        contacts: {
          type: "object",
          description:
            "Contact data to update. Can include registrant, admin, billing, tech keys. " +
            "Use get_contact_schema to see required fields for the domain's TLD.",
        },
        dry_run: { type: "boolean", default: true, description: "Preview without applying (default: true)" },
      },
    },
  },
  {
    name: "enable_privacy",
    description:
      "Enable WHOIS privacy protection on a domain to hide registrant contact details. " +
      "Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        dry_run: { type: "boolean", default: true, description: "Preview without applying (default: true)" },
      },
    },
  },
  {
    name: "disable_privacy",
    description:
      "Disable WHOIS privacy protection. Registrant contact details will become publicly visible. " +
      "Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        dry_run: { type: "boolean", default: true, description: "Preview without applying (default: true)" },
      },
    },
  },
  {
    name: "add_dns_records",
    description:
      "Add new DNS records to a domain without replacing existing ones. " +
      "Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain", "records"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        records: {
          type: "array",
          items: {
            type: "object",
            required: ["type", "name", "data"],
            properties: {
              type: { type: "string", description: "Record type (A, AAAA, CNAME, MX, TXT, etc.)" },
              name: { type: "string", description: "Record name (use @ for root)" },
              data: { type: "string", description: "Record value" },
              ttl: { type: "number", description: "TTL in seconds (default: 3600)" },
              priority: { type: "number", description: "Priority — required for MX and SRV records" },
            },
          },
        },
        dry_run: { type: "boolean", default: true, description: "Preview without applying (default: true)" },
      },
    },
  },
  {
    name: "replace_dns_records",
    description:
      "Replace all DNS records of a specific type and name. Existing records of that type/name are overwritten. " +
      "Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain", "type", "name", "records"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        type: { type: "string", description: "DNS record type to replace (A, CNAME, MX, TXT, etc.)" },
        name: { type: "string", description: "Record name (use @ for root)" },
        records: {
          type: "array",
          items: {
            type: "object",
            required: ["type", "name", "data"],
            properties: {
              type: { type: "string" },
              name: { type: "string" },
              data: { type: "string" },
              ttl: { type: "number" },
              priority: { type: "number" },
            },
          },
        },
        dry_run: { type: "boolean", default: true, description: "Preview without applying (default: true)" },
      },
    },
  },
  {
    name: "delete_dns_records",
    description:
      "Delete ALL DNS records of a specific type and name for a domain. " +
      "Fetches and shows current records in the dry-run preview. Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain", "type", "name"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        type: { type: "string", description: "DNS record type to delete (A, AAAA, CNAME, MX, TXT, etc.)" },
        name: { type: "string", description: "Record name to delete (use @ for root)" },
        dry_run: { type: "boolean", default: true, description: "Preview without deleting (default: true)" },
      },
    },
  },
  {
    name: "register_domain",
    description:
      "Register a new domain. With dry_run: true (default), runs API validation only — no charge. " +
      "Set dry_run: false to purchase.",
    inputSchema: {
      type: "object",
      required: ["domain", "period", "contacts"],
      properties: {
        domain: { type: "string", description: "Domain name to register" },
        period: { type: "number", description: "Registration period in years" },
        contacts: {
          type: "object",
          description: "Contact information (registrant, admin, billing, tech). Use get_contact_schema to check requirements.",
        },
        nameServers: {
          type: "array",
          items: { type: "string" },
          description: "Custom nameservers — uses BrandSight defaults if omitted",
        },
        privacy: { type: "boolean", description: "Enable WHOIS privacy on registration" },
        renewAuto: { type: "boolean", description: "Enable auto-renewal" },
        dry_run: {
          type: "boolean",
          default: true,
          description: "Validate registration without purchasing (default: true). Set false to purchase.",
        },
      },
    },
  },
  {
    name: "transfer_domain",
    description:
      "Transfer a domain into BrandSight. With dry_run: true (default), checks transfer eligibility only. " +
      "Set dry_run: false to initiate the transfer.",
    inputSchema: {
      type: "object",
      required: ["domain", "authCode"],
      properties: {
        domain: { type: "string", description: "Domain name to transfer in" },
        authCode: { type: "string", description: "EPP / auth code from the current registrar" },
        period: { type: "number", description: "Additional years to add during transfer" },
        dry_run: {
          type: "boolean",
          default: true,
          description: "Check eligibility without initiating transfer (default: true)",
        },
      },
    },
  },
  {
    name: "cancel_domain_action",
    description:
      "Cancel a pending domain action (e.g. an in-progress transfer). " +
      "Fetches the action status in the dry-run preview. Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain", "type"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        type: { type: "string", description: "Action type to cancel (e.g. TRANSFER_IN)" },
        dry_run: { type: "boolean", default: true, description: "Preview without cancelling (default: true)" },
      },
    },
  },
  {
    name: "regenerate_auth_code",
    description:
      "Regenerate the EPP / auth code for a domain. The existing code is immediately invalidated. " +
      "Defaults to dry_run: true.",
    inputSchema: {
      type: "object",
      required: ["domain"],
      properties: {
        domain: { type: "string", description: "Domain name" },
        dry_run: { type: "boolean", default: true, description: "Preview without executing (default: true)" },
      },
    },
  },
];

// ── Server ────────────────────────────────────────────────────────────────────

function createServer(): Server {
  const server = new Server(
    { name: "mcp-brandsight", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

  // ── Tool handler ──────────────────────────────────────────────────────────────

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args = {} } = request.params;
    const a = args as Record<string, unknown>;

    let client: BrandSightClient;
    try {
      client = getClient();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { content: [{ type: "text", text: `Configuration error:\n${msg}` }], isError: true };
    }

    try {
      switch (name) {
        // ── Read ──────────────────────────────────────────────────────────────

        case "list_domains": {
          const result = await client.listDomains({
            statuses: a.statuses as string[] | undefined,
            statusGroups: a.statusGroups as string[] | undefined,
            limit: a.limit as number | undefined,
            marker: a.marker as string | undefined,
            modifiedAtAfter: a.modifiedAtAfter as string | undefined,
            expiresAtBefore: a.expiresAtBefore as string | undefined,
            includes: a.includes as string[] | undefined,
          });
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "get_domain": {
          const result = await client.getDomain(
            a.domain as string,
            a.includes as string[] | undefined
          );
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "check_domain_availability": {
          const result = await client.checkAvailability(a.domain as string);
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "bulk_check_availability": {
          const result = await client.bulkCheckAvailability(a.domains as string[]);
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "get_dns_records": {
          const result = await client.getDnsRecords(
            a.domain as string,
            a.type as string | undefined,
            a.name as string | undefined
          );
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "list_domain_actions": {
          const result = await client.getDomainActions(a.domain as string);
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "get_domain_action": {
          const result = await client.getDomainAction(a.domain as string, a.type as string);
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "check_transfer_availability": {
          const result = await client.checkTransferAvailability(a.domain as string);
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "get_contact_schema": {
          const result = await client.getContactSchema(a.tld as string);
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        case "get_registration_schema": {
          const result = await client.getRegistrationSchema(a.tld as string);
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        }

        // ── Write ─────────────────────────────────────────────────────────────

        case "update_domain": {
          const { domain, dry_run = true, renewAuto, locked } = a as {
            domain: string;
            dry_run?: boolean;
            renewAuto?: boolean;
            locked?: boolean;
          };
          const updates = { ...(renewAuto !== undefined && { renewAuto }), ...(locked !== undefined && { locked }) };
          if (dry_run) {
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would update domain "${domain}" with:\n` +
                  `${JSON.stringify(updates, null, 2)}\n\n` +
                  `To apply, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.updateDomain(domain, updates);
          return { content: [{ type: "text", text: `Domain "${domain}" updated.\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "update_nameservers": {
          const { domain, nameServers, dry_run = true } = a as {
            domain: string;
            nameServers: string[];
            dry_run?: boolean;
          };
          if (dry_run) {
            const current = await client.getDomain(domain, undefined);
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would replace nameservers for "${domain}".\n\n` +
                  `Current:  ${JSON.stringify((current as Record<string,unknown>).nameServers ?? [])}\n` +
                  `New:      ${JSON.stringify(nameServers)}\n\n` +
                  `To apply, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.updateNameServers(domain, nameServers);
          return { content: [{ type: "text", text: `Nameservers for "${domain}" updated.\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "renew_domain": {
          const { domain, period = 1, dry_run = true } = a as {
            domain: string;
            period?: number;
            dry_run?: boolean;
          };
          if (dry_run) {
            const domainInfo = await client.getDomain(domain);
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would renew "${domain}" for ${period} year(s).\n` +
                  `Current expiry: ${(domainInfo as Record<string,unknown>).expiresAt ?? "unknown"}\n` +
                  `Renewal price: see domain.renewal field below\n` +
                  `${JSON.stringify({ renewal: (domainInfo as Record<string,unknown>).renewal }, null, 2)}\n\n` +
                  `To execute, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.renewDomain(domain, period);
          return { content: [{ type: "text", text: `Renewal for "${domain}" initiated.\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "update_contacts": {
          const { domain, contacts, dry_run = true } = a as {
            domain: string;
            contacts: unknown;
            dry_run?: boolean;
          };
          if (dry_run) {
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would update contacts for "${domain}" with:\n` +
                  `${JSON.stringify(contacts, null, 2)}\n\n` +
                  `To apply, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.updateContacts(domain, contacts as never);
          return { content: [{ type: "text", text: `Contacts for "${domain}" updated.\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "enable_privacy": {
          const { domain, dry_run = true } = a as { domain: string; dry_run?: boolean };
          if (dry_run) {
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would enable WHOIS privacy for "${domain}".\n` +
                  `Registrant contact details will be hidden from public WHOIS lookups.\n\n` +
                  `To apply, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.enablePrivacy(domain);
          return { content: [{ type: "text", text: `WHOIS privacy enabled for "${domain}".\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "disable_privacy": {
          const { domain, dry_run = true } = a as { domain: string; dry_run?: boolean };
          if (dry_run) {
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would DISABLE WHOIS privacy for "${domain}".\n` +
                  `⚠ Registrant contact details will become publicly visible in WHOIS lookups.\n\n` +
                  `To apply, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.disablePrivacy(domain);
          return { content: [{ type: "text", text: `WHOIS privacy disabled for "${domain}".\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "add_dns_records": {
          const { domain, records, dry_run = true } = a as {
            domain: string;
            records: unknown[];
            dry_run?: boolean;
          };
          if (dry_run) {
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would add ${records.length} DNS record(s) to "${domain}":\n` +
                  `${JSON.stringify(records, null, 2)}\n\n` +
                  `Existing records of the same type/name will NOT be removed.\n` +
                  `To apply, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.addDnsRecords(domain, records as never);
          return { content: [{ type: "text", text: `DNS records added to "${domain}".\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "replace_dns_records": {
          const { domain, type, name: recName, records, dry_run = true } = a as {
            domain: string;
            type: string;
            name: string;
            records: unknown[];
            dry_run?: boolean;
          };
          if (dry_run) {
            const existing = await client.getDnsRecords(domain, type, recName);
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would REPLACE all ${type} "${recName}" records on "${domain}".\n\n` +
                  `Current records:\n${JSON.stringify(existing, null, 2)}\n\n` +
                  `Replacement records:\n${JSON.stringify(records, null, 2)}\n\n` +
                  `To apply, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.replaceDnsRecords(domain, type, recName, records as never);
          return { content: [{ type: "text", text: `${type} "${recName}" records on "${domain}" replaced.\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "delete_dns_records": {
          const { domain, type, name: recName, dry_run = true } = a as {
            domain: string;
            type: string;
            name: string;
            dry_run?: boolean;
          };
          if (dry_run) {
            const existing = await client.getDnsRecords(domain, type, recName);
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would DELETE all ${type} records named "${recName}" from "${domain}".\n\n` +
                  `Records that would be deleted:\n${JSON.stringify(existing, null, 2)}\n\n` +
                  `⚠ This action cannot be undone.\n` +
                  `To delete, call again with dry_run: false.`,
              }],
            };
          }
          await client.deleteDnsRecords(domain, type, recName);
          return { content: [{ type: "text", text: `Deleted all ${type} records named "${recName}" from "${domain}".` }] };
        }

        case "register_domain": {
          const { domain, dry_run = true, ...regFields } = a as {
            domain: string;
            dry_run?: boolean;
            period: number;
            contacts: unknown;
            nameServers?: string[];
            privacy?: boolean;
            renewAuto?: boolean;
          };
          if (dry_run) {
            await client.validateRegistration({ domain, ...regFields } as never);
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Registration for "${domain}" passed API validation. No charge made.\n\n` +
                  `Details:\n${JSON.stringify({ domain, ...regFields }, null, 2)}\n\n` +
                  `To purchase, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.registerDomain({ domain, ...regFields } as never);
          return { content: [{ type: "text", text: `Registration for "${domain}" initiated.\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "transfer_domain": {
          const { domain, authCode, period, dry_run = true } = a as {
            domain: string;
            authCode: string;
            period?: number;
            dry_run?: boolean;
          };
          if (dry_run) {
            const eligibility = await client.checkTransferAvailability(domain);
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Transfer eligibility for "${domain}":\n` +
                  `${JSON.stringify(eligibility, null, 2)}\n\n` +
                  `Auth code provided: ${authCode ? "yes (redacted)" : "no"}\n` +
                  `Additional years: ${period ?? "none"}\n\n` +
                  `To initiate transfer, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.transferDomain(domain, authCode, period);
          return { content: [{ type: "text", text: `Transfer of "${domain}" initiated.\n${JSON.stringify(result, null, 2)}` }] };
        }

        case "cancel_domain_action": {
          const { domain, type, dry_run = true } = a as {
            domain: string;
            type: string;
            dry_run?: boolean;
          };
          if (dry_run) {
            const action = await client.getDomainAction(domain, type);
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would cancel action "${type}" on "${domain}".\n\n` +
                  `Current action state:\n${JSON.stringify(action, null, 2)}\n\n` +
                  `To cancel, call again with dry_run: false.`,
              }],
            };
          }
          await client.cancelDomainAction(domain, type);
          return { content: [{ type: "text", text: `Action "${type}" on "${domain}" cancelled.` }] };
        }

        case "regenerate_auth_code": {
          const { domain, dry_run = true } = a as { domain: string; dry_run?: boolean };
          if (dry_run) {
            return {
              content: [{
                type: "text",
                text:
                  `[DRY RUN] Would regenerate the auth/EPP code for "${domain}".\n` +
                  `⚠ The existing auth code will be immediately invalidated.\n\n` +
                  `To execute, call again with dry_run: false.`,
              }],
            };
          }
          const result = await client.regenerateAuthCode(domain);
          return { content: [{ type: "text", text: `Auth code for "${domain}" regenerated.\n${JSON.stringify(result, null, 2)}` }] };
        }

        default:
          return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
    }
  });

  return server;
}

// ── Entry point ───────────────────────────────────────────────────────────────

startServer(createServer, "BrandSight MCP server").catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
