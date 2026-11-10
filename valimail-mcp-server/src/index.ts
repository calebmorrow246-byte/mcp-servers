import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { createHash } from "node:crypto";
import { startServer, type RequestContext } from "./transport.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { ValimailClient, type Domain, type Sender, type Dkim, type Netblock } from "./valimail-client.js";
import { resolveCredentials } from "./creds.js";

const VALIMAIL_BASE_URL = process.env.VALIMAIL_BASE_URL || "https://api.valimail.com";
const VALIMAIL_ACCOUNT_SLUG = process.env.VALIMAIL_ACCOUNT_SLUG;
const VALIMAIL_INSECURE = process.env.VALIMAIL_INSECURE === "true";

if (!VALIMAIL_ACCOUNT_SLUG) {
  console.error(
    "Error: VALIMAIL_ACCOUNT_SLUG is required (the string after /app/ in the URL once logged in to Valimail)."
  );
  process.exit(1);
}

// Valimail access is per user: when hosted over HTTP each caller sends their own client-id/app-id in
// these headers, so Valimail attributes DMARC/DKIM changes to them. Locally (stdio) the credential
// comes from Credential Manager as before.
const CLIENT_ID_HEADER = "x-valimail-client-id";
const APP_ID_HEADER = "x-valimail-app-id";
const HTTP_MODE = (process.env.MCP_TRANSPORT ?? "stdio").toLowerCase() === "http";
const ACCOUNT_SLUG: string = VALIMAIL_ACCOUNT_SLUG;

function newClient(clientId: string, appId: string): ValimailClient {
  return new ValimailClient({ baseUrl: VALIMAIL_BASE_URL, clientId, appId, accountSlug: ACCOUNT_SLUG, insecure: VALIMAIL_INSECURE });
}

const localClient = HTTP_MODE
  ? undefined
  : await resolveCredentials()
      .then((c) => newClient(c.clientId, c.appId))
      .catch((err: Error) => {
        console.error(`Error resolving Valimail credentials: ${err.message}`);
        process.exit(1);
      });

// One client per user credential, so each keeps its own cached Valimail auth token between requests
const MAX_CACHED_CLIENTS = 50;
const userClients = new Map<string, ValimailClient>();

function clientFor(context: RequestContext): ValimailClient | undefined {
  const clientId = context.credentials[CLIENT_ID_HEADER];
  const appId = context.credentials[APP_ID_HEADER];
  if (!clientId || !appId) return localClient;
  const key = createHash("sha256").update(`${clientId}\n${appId}`).digest("hex");
  let client = userClients.get(key);
  if (!client) {
    if (userClients.size >= MAX_CACHED_CLIENTS) userClients.delete(userClients.keys().next().value as string);
    client = newClient(clientId, appId);
    userClients.set(key, client);
  }
  return client;
}

// ---- Shared schema fragments -------------------------------------------------

const domainFilterProps = {
  domain: { type: "array", items: { type: "string" }, description: "Filter to specific domain(s)/subdomain(s)." },
  dmarc_record: {
    type: "array",
    items: { type: "string", enum: ["None", "NS", "CNAME", "TXT"] },
    description: "Filter by DMARC record type.",
  },
  enforcement_status: {
    type: "array",
    items: { type: "string", enum: ["Not Configured", "Not At Enforcement", "Sending With Enforcement", "Blocked"] },
    description: "Filter by enforcement status.",
  },
  dmarc_policy: {
    type: "array",
    items: { type: "string", enum: ["None", "Quarantine", "Reject"] },
    description: "Filter by DMARC policy.",
  },
  sending_status: {
    type: "array",
    items: { type: "string", enum: ["Active", "Reporting Only", "Blocked"] },
    description: "Filter by sending status.",
  },
  org_domain_only: { type: "boolean", description: "Return only organizational domains (not subdomains)." },
  reverse: { type: "boolean", description: "Reverse the result order." },
  sort_key: {
    type: "string",
    description: "Sort key, e.g. domain_name, dmarc_record_type, enforcement_status, dmarc_policy, sending_status, last_report_date.",
  },
} as const;

const dateRangeProps = {
  start_date: { type: "string", description: "Start of the date range, ISO 8601 (yyyy-MM-ddThh:mm:ssZ)." },
  end_date: { type: "string", description: "End of the date range, ISO 8601 (yyyy-MM-ddThh:mm:ssZ)." },
} as const;

const pageProps = {
  reverse: { type: "boolean", description: "Reverse the result order." },
  page: { type: "number", description: "Page number (1-based)." },
  per_page: { type: "number", description: "Results per page." },
} as const;

// ---- Tool definitions ---------------------------------------------------------

const TOOLS: Tool[] = [
  // -- Configuration API: Domains --
  {
    name: "list_domains",
    description:
      "List domains/subdomains configured in Valimail for this account, with their current DMARC record, " +
      "policy, enforcement status, and sending status. Use to get an overview or find a domain before drilling in.",
    inputSchema: { type: "object", properties: { ...domainFilterProps } },
  },
  {
    name: "get_domain",
    description: "Get full configuration detail for a single domain or subdomain.",
    inputSchema: {
      type: "object",
      properties: { domain: { type: "string", description: "Domain name, e.g. example.com." } },
      required: ["domain"],
    },
  },
  {
    name: "create_domain",
    description: "Add a new domain or subdomain to this Valimail account.",
    inputSchema: {
      type: "object",
      properties: { domain: { type: "string", description: "Domain name to add, e.g. example.com." } },
      required: ["domain"],
    },
  },
  {
    name: "update_domain",
    description:
      "Update a domain's DMARC policy and/or sending status. At least one of dmarc_policy or sending_status must be provided. " +
      "This changes what mail servers do with unauthenticated mail claiming to be from this domain — use with care.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name to update." },
        dmarc_policy: { type: "string", enum: ["None", "Quarantine", "Reject"], description: "New DMARC policy." },
        sending_status: {
          type: "string",
          enum: ["Active", "Reporting Only", "Blocked"],
          description: "New sending status.",
        },
      },
      required: ["domain"],
    },
  },
  {
    name: "delete_domain",
    description:
      "PERMANENTLY remove a domain from this Valimail account, including its DMARC/DKIM/sender/netblock configuration. " +
      "This is destructive and cannot be undone via the API. Requires confirm: true.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name to delete." },
        confirm: { type: "boolean", description: "Must be true to actually delete. Safety guard against accidental calls." },
      },
      required: ["domain", "confirm"],
    },
  },

  // -- Configuration API: Senders --
  {
    name: "list_senders",
    description: "List the email service providers (senders) linked to a domain and their approval status.",
    inputSchema: {
      type: "object",
      properties: { domain: { type: "string", description: "Domain name." } },
      required: ["domain"],
    },
  },
  {
    name: "get_sender",
    description: "Get detail for a single sender linked to a domain.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        sender_slug: { type: "string", description: "Sender slug (from list_senders or list_available_senders), e.g. 'sendgrid'." },
      },
      required: ["domain", "sender_slug"],
    },
  },
  {
    name: "create_sender",
    description:
      "Link a new sender (email service provider) to a domain, in pending_approval status. " +
      "Use list_available_senders to find valid sender slugs.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        sender_slug: { type: "string", description: "Sender slug from list_available_senders, e.g. 'sendgrid'." },
      },
      required: ["domain", "sender_slug"],
    },
  },
  {
    name: "update_sender_status",
    description:
      "Approve, deny, or reset to pending a sender linked to a domain. Approving authorizes that service to send mail as this domain.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        sender_slug: { type: "string", description: "Sender slug." },
        status: { type: "string", enum: ["approved", "denied", "pending_approval"], description: "New status." },
      },
      required: ["domain", "sender_slug", "status"],
    },
  },
  {
    name: "list_available_senders",
    description: "List every sender (email service provider) Valimail knows about and can be linked to a domain via create_sender.",
    inputSchema: { type: "object", properties: {} },
  },

  // -- Configuration API: DKIM --
  {
    name: "list_domain_dkims",
    description: "List all DKIM key records configured for a domain.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        reverse: { type: "boolean", description: "Reverse the result order." },
      },
      required: ["domain"],
    },
  },
  {
    name: "get_domain_dkim",
    description: "Get detail for a single DKIM record by selector.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        selector: { type: "string", description: "DKIM selector." },
      },
      required: ["domain", "selector"],
    },
  },
  {
    name: "create_domain_dkim",
    description:
      "Create a new DKIM record for a domain. Provide exactly one of public_key or cname_target, not both.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        selector: { type: "string", description: "DKIM selector for the new record." },
        public_key: { type: "string", description: "RSA public key (min 1024 bits unless short_key_override is set). Provide this OR cname_target." },
        cname_target: { type: "string", description: "CNAME target hostname. Provide this OR public_key." },
        comment: { type: "string", description: "Optional note to attach to the record." },
        exact_domain_only: { type: "boolean", description: "Add the exact-domain-signing flag (t=s) to the generated record." },
        short_key_override: { type: "boolean", description: "Allow a public key shorter than 1024 bits." },
        skip_version_tag: { type: "boolean", description: "Omit the v=DKIM1 tag from the generated record." },
        skip_key_tag: { type: "boolean", description: "Omit the k tag from the generated record." },
      },
      required: ["domain", "selector"],
    },
  },
  {
    name: "update_domain_dkim",
    description:
      "Update a DKIM record's comment, sender owner, domain owner, or which sender it's linked to. " +
      "At least one field must be provided.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        selector: { type: "string", description: "DKIM selector to update." },
        new_sender_slug: { type: "string", description: "Re-link this DKIM record to a different sender slug." },
        comment: { type: "string", description: "New comment/note." },
        sender_owner: { type: "string", description: "Owner of the sending service (if known)." },
        domain_owner: { type: "string", description: "Owner of the domain (if known)." },
      },
      required: ["domain", "selector"],
    },
  },

  // -- Configuration API: Netblocks --
  {
    name: "list_netblocks",
    description: "List all netblocks (SPF-authorized IP ranges) configured for a domain.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        reverse: { type: "boolean", description: "Reverse the result order." },
      },
      required: ["domain"],
    },
  },
  {
    name: "get_netblock",
    description: "Get detail for a single netblock by IP or CIDR.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        netblock: { type: "string", description: "IP or CIDR, e.g. '203.0.113.0/24'." },
      },
      required: ["domain", "netblock"],
    },
  },
  {
    name: "create_netblock",
    description: "Add a new SPF-authorized netblock (IP range) for a domain.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        netblock: { type: "string", description: "IP or CIDR in standard notation, e.g. '203.0.113.0/24'." },
        comment: { type: "string", description: "Optional note." },
        sender_slug: { type: "string", description: "Optional sender slug to associate with this netblock." },
      },
      required: ["domain", "netblock"],
    },
  },
  {
    name: "update_netblock",
    description: "Update a netblock's comment or associated sender.",
    inputSchema: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Domain name." },
        netblock: { type: "string", description: "IP or CIDR of the netblock to update." },
        comment: { type: "string", description: "New comment/note." },
        sender_slug: { type: "string", description: "New sender slug to associate (or omit to leave unchanged)." },
      },
      required: ["domain", "netblock"],
    },
  },

  // -- Reporting API --
  {
    name: "get_domains_report",
    description:
      "Reporting view of domains — same filters as list_domains but served by the Reporting API. " +
      "Use for dashboards/summaries; use list_domains when you need the live Configuration API view.",
    inputSchema: { type: "object", properties: { ...domainFilterProps } },
  },
  {
    name: "get_senders_report",
    description:
      "DMARC compliance breakdown per sending source (service_name) for one or more domains over a date range: " +
      "message volume, pass/fail counts, SPF alignment, quarantine/reject counts.",
    inputSchema: {
      type: "object",
      properties: {
        domains: { type: "array", items: { type: "string" }, description: "Domains to report on." },
        ...dateRangeProps,
        ...pageProps,
      },
      required: ["domains", "start_date", "end_date"],
    },
  },
  {
    name: "get_unidentified_report",
    description:
      "Traffic from sources Valimail could not identify/attribute to a known sender, for one or more domains over a date range. " +
      "Use to spot shadow IT senders or spoofing attempts.",
    inputSchema: {
      type: "object",
      properties: {
        domains: { type: "array", items: { type: "string" }, description: "Domains to report on." },
        ...dateRangeProps,
        ...pageProps,
      },
      required: ["domains", "start_date", "end_date"],
    },
  },
  {
    name: "get_events_report",
    description:
      "Audit log of configuration changes (domain added/deleted, DMARC policy changed, DKIM key added/deleted, users added/removed, etc.) over a date range.",
    inputSchema: {
      type: "object",
      properties: {
        subjects: { type: "array", items: { type: "string" }, description: "Filter to specific subjects (domain names or user emails)." },
        user_id: { type: "string", description: "Filter to a specific user ID that performed the action. Use '-1' for platform-automated changes." },
        event_type: {
          type: "string",
          enum: [
            "domain_added", "domain_deleted", "user_added", "user_deleted", "user_deactivated",
            "spf_delegation_started", "spf_delegation_stopped", "service_enabled", "service_deleted",
            "dkim_key_added", "dkim_key_deleted", "dmarc_policy_set_to_quarantine",
            "dmarc_policy_set_to_reject", "dmarc_policy_set_to_none",
          ],
          description: "Filter to a specific event type.",
        },
        ...dateRangeProps,
        ...pageProps,
      },
      required: ["start_date", "end_date"],
    },
  },
  {
    name: "get_dkim_continuous_protection_report",
    description:
      "Inventory of DKIM key pairs Valimail's Continuous Protection has observed in use, with key length, upload date, " +
      "and last-seen date. Use to find stale/unrotated DKIM keys.",
    inputSchema: {
      type: "object",
      properties: {
        sender_name: { type: "string", description: "Filter by sender (email service provider) name." },
        domain_name: { type: "string", description: "Filter by domain name." },
        uploaded_start_date: { type: "string", description: "Start of the key-upload date range, ISO 8601." },
        uploaded_end_date: { type: "string", description: "End of the key-upload date range, ISO 8601." },
        last_seen_start_date: { type: "string", description: "Start of the last-seen date range, ISO 8601." },
        last_seen_end_date: { type: "string", description: "End of the last-seen date range, ISO 8601." },
        sort_key: {
          type: "string",
          enum: ["sender-name", "domain-name", "dkim-selector", "dkim-type", "dkim-bits", "uploaded-date", "last-seen-date"],
          description: "Field to sort by.",
        },
        ...pageProps,
      },
    },
  },
  {
    name: "get_senders_continuous_protection_report",
    description:
      "Inventory of sending sources Valimail's Continuous Protection has observed, with last-seen date and email volume. " +
      "Use to find senders that have gone quiet or to audit what's actually sending as a domain.",
    inputSchema: {
      type: "object",
      properties: {
        sender_name: { type: "string", description: "Filter by sender (email service provider) name." },
        domain_name: { type: "string", description: "Filter by domain name." },
        last_seen_start_date: { type: "string", description: "Start of the last-seen date range, ISO 8601." },
        last_seen_end_date: { type: "string", description: "End of the last-seen date range, ISO 8601." },
        sort_key: { type: "string", enum: ["sender-name", "domain-name", "last-seen-date", "email-volume"], description: "Field to sort by." },
        ...pageProps,
      },
    },
  },
  {
    name: "get_tls_report",
    description:
      "MTA-STS/TLS reporting summary across domains for a date range: policy mode, MX host, and policy cache age observed in TLS reports.",
    inputSchema: {
      type: "object",
      properties: {
        start_date: { type: "string", description: "Start date, YYYY-MM-DD." },
        end_date: { type: "string", description: "End date, YYYY-MM-DD." },
        domain_names: { type: "array", items: { type: "string" }, description: "Filter to specific domains. Omit for all domains." },
        policy_mx_host: { type: "string", description: "Filter by the MX host present in the TLS reports." },
        policy_mode: { type: "string", enum: ["none", "enforce", "testing", "unknown"], description: "Filter by policy mode." },
        limit: { type: "number", description: "Max records to return. Default 20." },
        page: { type: "number", description: "Page number. Default 1." },
        sort: { type: "string", description: "Sort field(s), e.g. 'domain, -policy-mx-host' ('-' prefix = descending)." },
      },
      required: ["start_date", "end_date"],
    },
  },
  {
    name: "get_tls_failure_details",
    description:
      "Detailed TLS session failure counts for a specific TLS report (from get_tls_report's report-id): sending/receiving IPs, MX host, success/failure counts.",
    inputSchema: {
      type: "object",
      properties: {
        report_id: { type: "string", description: "Report ID from get_tls_report." },
        domain_name: { type: "string", description: "Domain name the report is for." },
        policy_mode: { type: "string", enum: ["none", "enforce", "testing", "unknown"], description: "Filter by policy mode." },
        policy_type: { type: "string", enum: ["no-policy-found", "tlsa", "sts"], description: "Filter by policy type." },
      },
      required: ["report_id", "domain_name"],
    },
  },
];

// ---- Formatting helpers -----------------------------------------------------

function block(fields: Array<[string, unknown]>): string {
  return fields
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `  ${k}: ${v}`)
    .join("\n");
}

function formatDomain(d: Domain): string {
  return block([
    ["Domain", d.domain],
    ["DMARC policy", d["dmarc-policy"]],
    ["DMARC record type", d["dmarc-record-type"]],
    ["Enforcement status", d["enforcement-status"]],
    ["Sending status", d["sending-status"]],
    ["Org domain", d["is-org-domain"]],
    ["DMARC record", d["dmarc-record"]],
    ["Last report date", d["last-report-date"]],
  ]);
}

function formatSender(s: Sender): string {
  return `[${s.slug}] ${s.name ?? ""} | status: ${s.status ?? "unknown"}`;
}

function formatDkim(d: Dkim): string {
  return block([
    ["Selector", d.selector],
    ["Public key", d["public-key"] ? `${d["public-key"].slice(0, 40)}…` : undefined],
    ["CNAME target", d["cname-target"]],
    ["Sender slug", d["sender-slug"]],
    ["Sender owner", d["sender-owner"]],
    ["Domain owner", d["domain-owner"]],
    ["Comment", d.comment],
  ]);
}

function formatNetblock(n: Netblock): string {
  return block([
    ["Netblock", n.netblock],
    ["SPF record", n["spf-record"]],
    ["Sender slug", n["sender-slug"]],
    ["Comment", n.comment],
  ]);
}

function createServer(context: RequestContext): Server {
  const valimail = clientFor(context);

  const server = new Server(
    { name: "valimail-mcp-server", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const a = (args ?? {}) as Record<string, any>;

    if (!valimail) {
      return {
        content: [{ type: "text", text: "Valimail access is per user: no Valimail credential was sent. Store your own client-id/app-id in Credential Manager as 'Valimail API' and start Claude Code with the MCP launcher so they are sent as the X-Valimail-Client-Id / X-Valimail-App-Id headers." }],
        isError: true,
      };
    }

    try {
      switch (name) {
        // -- Domains --
        case "list_domains":
        case "get_domains_report": {
          const filters = {
            domain: a.domain,
            dmarcRecord: a.dmarc_record,
            enforcementStatus: a.enforcement_status,
            dmarcPolicy: a.dmarc_policy,
            sendingStatus: a.sending_status,
            orgDomainOnly: a.org_domain_only,
            reverse: a.reverse,
            sortKey: a.sort_key,
          };
          const domains = name === "list_domains" ? await valimail.listDomains(filters) : await valimail.getDomainsReport(filters);
          if (domains.length === 0) return { content: [{ type: "text", text: "No domains found." }] };
          return {
            content: [{ type: "text", text: `${domains.length} domain(s):\n\n${domains.map(formatDomain).join("\n\n")}` }],
          };
        }

        case "get_domain": {
          const domain = await valimail.getDomain(a.domain);
          return { content: [{ type: "text", text: formatDomain(domain) }] };
        }

        case "create_domain": {
          const domain = await valimail.createDomain(a.domain);
          return { content: [{ type: "text", text: `Domain created:\n${formatDomain(domain)}` }] };
        }

        case "update_domain": {
          if (!a.dmarc_policy && !a.sending_status) {
            return {
              content: [{ type: "text", text: "At least one of dmarc_policy or sending_status must be provided." }],
              isError: true,
            };
          }
          const domain = await valimail.updateDomain(a.domain, {
            dmarcPolicy: a.dmarc_policy,
            sendingStatus: a.sending_status,
          });
          return { content: [{ type: "text", text: `Domain updated:\n${formatDomain(domain)}` }] };
        }

        case "delete_domain": {
          if (a.confirm !== true) {
            return {
              content: [{ type: "text", text: "Refusing to delete: confirm must be explicitly set to true." }],
              isError: true,
            };
          }
          const domain = await valimail.deleteDomain(a.domain);
          return { content: [{ type: "text", text: `Domain deleted:\n${formatDomain(domain)}` }] };
        }

        // -- Senders --
        case "list_senders": {
          const senders = await valimail.listSenders(a.domain);
          if (senders.length === 0) return { content: [{ type: "text", text: `No senders linked to ${a.domain}.` }] };
          return { content: [{ type: "text", text: `${senders.length} sender(s) for ${a.domain}:\n\n${senders.map(formatSender).join("\n")}` }] };
        }

        case "get_sender": {
          const sender = await valimail.getSender(a.domain, a.sender_slug);
          return { content: [{ type: "text", text: formatSender(sender) }] };
        }

        case "create_sender": {
          const sender = await valimail.createSender(a.domain, a.sender_slug);
          return { content: [{ type: "text", text: `Sender linked:\n${formatSender(sender)}` }] };
        }

        case "update_sender_status": {
          const sender = await valimail.updateSenderStatus(a.domain, a.sender_slug, a.status);
          return { content: [{ type: "text", text: `Sender status updated:\n${formatSender(sender)}` }] };
        }

        case "list_available_senders": {
          const senders = await valimail.listAvailableSenders();
          return {
            content: [
              {
                type: "text",
                text: `${senders.length} available sender(s):\n\n${senders.map((s) => `[${s.slug}] ${s.name ?? ""}`).join("\n")}`,
              },
            ],
          };
        }

        // -- DKIM --
        case "list_domain_dkims": {
          const dkims = await valimail.listDomainDkims(a.domain, a.reverse);
          if (dkims.length === 0) return { content: [{ type: "text", text: `No DKIM records for ${a.domain}.` }] };
          return { content: [{ type: "text", text: `${dkims.length} DKIM record(s) for ${a.domain}:\n\n${dkims.map(formatDkim).join("\n\n")}` }] };
        }

        case "get_domain_dkim": {
          const dkim = await valimail.getDomainDkim(a.domain, a.selector);
          return { content: [{ type: "text", text: formatDkim(dkim) }] };
        }

        case "create_domain_dkim": {
          if (!a.public_key && !a.cname_target) {
            return {
              content: [{ type: "text", text: "Provide either public_key or cname_target." }],
              isError: true,
            };
          }
          const dkim = await valimail.createDomainDkim(a.domain, {
            selector: a.selector,
            publicKey: a.public_key,
            cnameTarget: a.cname_target,
            comment: a.comment,
            exactDomainOnly: a.exact_domain_only,
            shortKeyOverride: a.short_key_override,
            skipVersionTag: a.skip_version_tag,
            skipKeyTag: a.skip_key_tag,
          });
          return { content: [{ type: "text", text: `DKIM record created:\n${formatDkim(dkim)}` }] };
        }

        case "update_domain_dkim": {
          const dkim = await valimail.updateDomainDkim(a.domain, a.selector, {
            newSenderSlug: a.new_sender_slug,
            comment: a.comment,
            senderOwner: a.sender_owner,
            domainOwner: a.domain_owner,
          });
          return { content: [{ type: "text", text: `DKIM record updated:\n${formatDkim(dkim)}` }] };
        }

        // -- Netblocks --
        case "list_netblocks": {
          const netblocks = await valimail.listNetblocks(a.domain, a.reverse);
          if (netblocks.length === 0) return { content: [{ type: "text", text: `No netblocks for ${a.domain}.` }] };
          return { content: [{ type: "text", text: `${netblocks.length} netblock(s) for ${a.domain}:\n\n${netblocks.map(formatNetblock).join("\n\n")}` }] };
        }

        case "get_netblock": {
          const netblock = await valimail.getNetblock(a.domain, a.netblock);
          return { content: [{ type: "text", text: formatNetblock(netblock) }] };
        }

        case "create_netblock": {
          const netblock = await valimail.createNetblock(a.domain, {
            netblock: a.netblock,
            comment: a.comment,
            senderSlug: a.sender_slug,
          });
          return { content: [{ type: "text", text: `Netblock created:\n${formatNetblock(netblock)}` }] };
        }

        case "update_netblock": {
          const netblock = await valimail.updateNetblock(a.domain, a.netblock, {
            comment: a.comment,
            senderSlug: a.sender_slug,
          });
          return { content: [{ type: "text", text: `Netblock updated:\n${formatNetblock(netblock)}` }] };
        }

        // -- Reporting --
        case "get_senders_report": {
          const rows = await valimail.getSendersReport({
            domains: a.domains,
            startDate: a.start_date,
            endDate: a.end_date,
            reverse: a.reverse,
            page: a.page,
            perPage: a.per_page,
          });
          if (rows.length === 0) return { content: [{ type: "text", text: "No sender report data for the given filters." }] };
          const lines = rows.map((r) =>
            block([
              ["Service", r.service_name],
              ["Status", r.service_status],
              ["Total messages", r.total_messages_count],
              ["Passing %", r.passing_percentage],
              ["DMARC pass / fail", `${r.dmarc_passing_count} / ${r.dmarc_failing_count}`],
              ["SPF aligned / unaligned", `${r.aligned_spf_count} / ${r.failing_or_unaligned_spf_count}`],
              ["Allowed (no enforcement / with enforcement)", `${r.allowed_through_no_enforcement_count} / ${r.allowed_through_with_enforcement_count}`],
              ["DMARC overridden", r.dmarc_overridden_count],
              ["Quarantined / Rejected", `${r.quarantined_count} / ${r.rejected_count}`],
            ])
          );
          return { content: [{ type: "text", text: `${rows.length} sender(s):\n\n${lines.join("\n\n")}` }] };
        }

        case "get_unidentified_report": {
          const rows = await valimail.getUnidentifiedReport({
            domains: a.domains,
            startDate: a.start_date,
            endDate: a.end_date,
            reverse: a.reverse,
            page: a.page,
            perPage: a.per_page,
          });
          if (rows.length === 0) return { content: [{ type: "text", text: "No unidentified traffic for the given filters." }] };
          const lines = rows.map((r) =>
            block([
              ["Source IP", r["source-ip"]],
              ["PTR name", r["ptr-name"]],
              ["Country", r["geo-country-code"]],
              ["SPF domain", r["spf-domain"]],
              ["DMARC policy org domain", r["dmarc-policy-org-domain"]],
              ["Total messages", r["total-messages-count"]],
              ["Passing %", r["passing-percentage"]],
              ["DMARC pass / fail", `${r["dmarc-passing-count"]} / ${r["dmarc-failing-count"]}`],
              ["SPF aligned / failing / unaligned", `${r["aligned-spf-count"]} / ${r["failing-spf-count"]} / ${r["unaligned-spf-count"]}`],
              ["Quarantined / Rejected", `${r["quarantined-count"]} / ${r["rejected-count"]}`],
            ])
          );
          return { content: [{ type: "text", text: `${rows.length} unidentified source(s):\n\n${lines.join("\n\n")}` }] };
        }

        case "get_events_report": {
          const rows = await valimail.getEventsReport({
            subjects: a.subjects,
            userId: a.user_id,
            eventType: a.event_type,
            startDate: a.start_date,
            endDate: a.end_date,
            reverse: a.reverse,
            page: a.page,
            perPage: a.per_page,
          });
          if (rows.length === 0) return { content: [{ type: "text", text: "No events for the given filters." }] };
          const lines = rows.map((e) => `[${e["performed-at"]}] ${e.subject} — ${e["event-type"]}: ${e["event-change"]} (by ${e.user})`);
          return { content: [{ type: "text", text: `${rows.length} event(s):\n\n${lines.join("\n")}` }] };
        }

        case "get_dkim_continuous_protection_report": {
          const rows = await valimail.getDkimContinuousProtectionReport({
            senderName: a.sender_name,
            domainName: a.domain_name,
            uploadedStartDate: a.uploaded_start_date,
            uploadedEndDate: a.uploaded_end_date,
            lastSeenStartDate: a.last_seen_start_date,
            lastSeenEndDate: a.last_seen_end_date,
            sortKey: a.sort_key,
            reverse: a.reverse,
            page: a.page,
            perPage: a.per_page,
          });
          if (rows.length === 0) return { content: [{ type: "text", text: "No DKIM continuous protection data for the given filters." }] };
          const lines = rows.map((r) =>
            block([
              ["Sender", r["sender-name"]],
              ["Domain", r["domain-name"]],
              ["Selector", r["dkim-selector"]],
              ["Type", r["dkim-type"]],
              ["Key bits", r["dkim-bits"]],
              ["Uploaded", r["uploaded-date"]],
              ["Last seen", r["last-seen-date"]],
              ["Sender owner", r["sender-owner"]],
              ["Domain owner", r["domain-owner"]],
              ["Comment", r.comment],
            ])
          );
          return { content: [{ type: "text", text: `${rows.length} DKIM key(s):\n\n${lines.join("\n\n")}` }] };
        }

        case "get_senders_continuous_protection_report": {
          const rows = await valimail.getSendersContinuousProtectionReport({
            senderName: a.sender_name,
            domainName: a.domain_name,
            lastSeenStartDate: a.last_seen_start_date,
            lastSeenEndDate: a.last_seen_end_date,
            sortKey: a.sort_key,
            reverse: a.reverse,
            page: a.page,
            perPage: a.per_page,
          });
          if (rows.length === 0) return { content: [{ type: "text", text: "No sender continuous protection data for the given filters." }] };
          const lines = rows.map((r) =>
            block([
              ["Sender", r["sender-name"]],
              ["Domain", r["domain-name"]],
              ["Last seen", r["last-seen-date"]],
              ["Email volume", r["email-volume"]],
              ["Notes", r.notes],
            ])
          );
          return { content: [{ type: "text", text: `${rows.length} sender(s):\n\n${lines.join("\n\n")}` }] };
        }

        case "get_tls_report": {
          const result = await valimail.getTlsReport({
            startDate: a.start_date,
            endDate: a.end_date,
            domainNames: a.domain_names,
            policyMxHost: a.policy_mx_host,
            policyMode: a.policy_mode,
            limit: a.limit,
            page: a.page,
            sort: a.sort,
          });
          if (result.rows.length === 0) return { content: [{ type: "text", text: "No TLS report data for the given filters." }] };
          const lines = result.rows.map(
            (r) => `[${r["report-id"]}] ${r.domain} | mode: ${r["policy-mode"]} | mx: ${r["policy-mx-host"]} | max-age: ${r["max-age"]}s`
          );
          return {
            content: [
              {
                type: "text",
                text: `${result.count} total, showing ${result.rows.length}:\n\n${lines.join("\n")}`,
              },
            ],
          };
        }

        case "get_tls_failure_details": {
          const rows = await valimail.getTlsFailureDetails({
            reportId: a.report_id,
            domainName: a.domain_name,
            policyMode: a.policy_mode,
            policyType: a.policy_type,
          });
          if (rows.length === 0) return { content: [{ type: "text", text: "No TLS failure details for the given filters." }] };
          const lines = rows.map((r) =>
            block([
              ["Domain", r.domain_name],
              ["Report ID", r.report_id],
              ["Sending MTA IP", r.sending_mta_ip],
              ["Receiving IP", r.receiving_ip],
              ["Receiving MX host", r.receiving_mx_host_name],
              ["Period", `${r.start_date} to ${r.end_date}`],
              ["Success / Failure", `${r.success_count} / ${r.failure_count}`],
            ])
          );
          return { content: [{ type: "text", text: `${rows.length} failure detail(s):\n\n${lines.join("\n\n")}` }] };
        }

        default:
          return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : String(error);
      return { content: [{ type: "text", text: `Valimail API error: ${msg}` }], isError: true };
    }
  });

  return server;
}

await startServer(createServer, "Valimail MCP server", { credentialHeaders: [CLIENT_ID_HEADER, APP_ID_HEADER] });
