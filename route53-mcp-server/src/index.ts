import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { startServer } from "./transport.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { Route53ClientWrapper } from "./route53-client.js";

if (!process.env.AWS_ACCESS_KEY_ID || !process.env.AWS_SECRET_ACCESS_KEY) {
  console.error(
    "Error: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required (set by Start-Route53MCP.ps1 from Windows Credential Manager)."
  );
  process.exit(1);
}

const AWS_REGION = process.env.AWS_REGION || "us-east-1";
const route53 = new Route53ClientWrapper(AWS_REGION);

// Read-only by design: only List*/Get* Route53 API operations are wired up
// below. There is no create/update/delete tool in this server at all - not
// hidden behind a flag, simply not implemented - so there is no write path
// to accidentally exercise. Technicians make actual DNS changes through
// normal channels, not through this MCP server.
const TOOLS: Tool[] = [
  {
    name: "list_hosted_zones",
    description:
      "List Route53 hosted zones, optionally starting from a DNS name (alphabetical, matches " +
      "'aws route53 list-hosted-zones-by-name --dns-name'). Returns zone ID, name, record count, " +
      "comment, and whether it's a private zone. Use this to find a domain's hosted zone ID before " +
      "calling list_resource_record_sets or get_hosted_zone.",
    inputSchema: {
      type: "object",
      properties: {
        dns_name: {
          type: "string",
          description:
            "Starting DNS name to list from, e.g. 'example.com'. Omit to list " +
            "all zones in the account from the beginning. Results are returned in alphabetical order " +
            "starting at or after this name, not filtered to only this name - check the returned zone " +
            "names if you need an exact match.",
        },
      },
    },
  },
  {
    name: "get_hosted_zone",
    description:
      "Get full detail for a single hosted zone by ID: name, comment, private/public, record count, " +
      "and its delegation set (authoritative NS name servers). Use after list_hosted_zones to confirm " +
      "a zone's name servers.",
    inputSchema: {
      type: "object",
      properties: {
        hosted_zone_id: {
          type: "string",
          description:
            "Hosted zone ID from list_hosted_zones (e.g. 'ZATXBS9JM4NDY'). Accepts either the bare ID " +
            "or the '/hostedzone/...' form.",
        },
      },
      required: ["hosted_zone_id"],
    },
  },
  {
    name: "list_resource_record_sets",
    description:
      "List DNS resource record sets (A, CNAME, TXT, NS, MX, etc.) in a hosted zone. Use to inspect " +
      "actual DNS records - e.g. confirming a DKIM CNAME, checking an NS delegation, or auditing what's " +
      "published for a domain.",
    inputSchema: {
      type: "object",
      properties: {
        hosted_zone_id: {
          type: "string",
          description: "Hosted zone ID from list_hosted_zones (e.g. 'ZATXBS9JM4NDY').",
        },
        name: {
          type: "string",
          description:
            "Optional starting record name to filter/paginate from, e.g. 'selector2._domainkey.example.com'. " +
            "Results begin at the first record whose name is >= this value, not filtered to only this name.",
        },
        type: {
          type: "string",
          description: "Optional starting record type. Only used in combination with 'name'.",
          enum: ["SOA", "A", "AAAA", "TXT", "NS", "CNAME", "MX", "PTR", "SRV", "SPF"],
        },
      },
      required: ["hosted_zone_id"],
    },
  },
];

function createServer(): Server {
  const server = new Server(
    { name: "route53-mcp-server", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const a = (args ?? {}) as Record<string, unknown>;

    try {
      switch (name) {
        case "list_hosted_zones": {
          const zones = await route53.listHostedZonesByName(a.dns_name as string | undefined);
          if (zones.length === 0) {
            return { content: [{ type: "text", text: "No hosted zones found." }] };
          }
          const lines = zones.map(
            (z) =>
              `[${z.id}] ${z.name} | ${z.recordCount} record(s)${z.privateZone ? " | PRIVATE" : ""}${z.comment ? ` | ${z.comment}` : ""}`
          );
          return { content: [{ type: "text", text: `${zones.length} hosted zone(s):\n\n${lines.join("\n")}` }] };
        }

        case "get_hosted_zone": {
          const { zone, nameServers } = await route53.getHostedZone(a.hosted_zone_id as string);
          const text = [
            `[${zone.id}] ${zone.name}`,
            `Records: ${zone.recordCount}   Private: ${zone.privateZone}`,
            zone.comment ? `Comment: ${zone.comment}` : "",
            `Name servers:\n${nameServers.map((ns) => `  ${ns}`).join("\n")}`,
          ]
            .filter(Boolean)
            .join("\n");
          return { content: [{ type: "text", text }] };
        }

        case "list_resource_record_sets": {
          const records = await route53.listResourceRecordSets(
            a.hosted_zone_id as string,
            a.name as string | undefined,
            a.type as string | undefined
          );
          if (records.length === 0) {
            return { content: [{ type: "text", text: "No resource record sets found." }] };
          }
          const lines = records.map((r) => {
            const value = r.aliasTarget ? `ALIAS -> ${r.aliasTarget}` : r.values.join(", ");
            return `${r.name} | ${r.type}${r.ttl !== undefined ? ` | TTL ${r.ttl}` : ""} | ${value}`;
          });
          return { content: [{ type: "text", text: `${records.length} record set(s):\n\n${lines.join("\n")}` }] };
        }

        default:
          return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : String(error);
      return { content: [{ type: "text", text: `Route53 API error: ${msg}` }], isError: true };
    }
  });

  return server;
}

await startServer(createServer, "Route53 MCP server");
