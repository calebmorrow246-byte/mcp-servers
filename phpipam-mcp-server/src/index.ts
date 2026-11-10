import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { startServer } from "./transport.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { PhpIPAMClient } from "./phpipam-client.js";
import { resolveCredentials } from "./creds.js";

const PHPIPAM_BASE_URL = process.env.PHPIPAM_BASE_URL;
const PHPIPAM_APP_ID = process.env.PHPIPAM_APP_ID ?? "claude";
const PHPIPAM_INSECURE = process.env.PHPIPAM_INSECURE === "true";
const PHPIPAM_APP_TOKEN = process.env.PHPIPAM_APP_TOKEN;

if (!PHPIPAM_BASE_URL) {
  console.error(
    "Error: PHPIPAM_BASE_URL is required (e.g. https://ipam.example.com)."
  );
  process.exit(1);
}

const credentials = PHPIPAM_APP_TOKEN
  ? { username: "", password: "" }
  : await resolveCredentials().catch((err: Error) => {
      console.error(`Error resolving phpIPAM credentials: ${err.message}`);
      process.exit(1);
    });

const client = new PhpIPAMClient({
  baseUrl: PHPIPAM_BASE_URL,
  appId: PHPIPAM_APP_ID,
  // App token mode: token passed directly; skip user auth.
  // Fall back to username/password for user token mode.
  appToken: PHPIPAM_APP_TOKEN || undefined,
  username: PHPIPAM_APP_TOKEN ? undefined : credentials.username,
  password: PHPIPAM_APP_TOKEN ? undefined : credentials.password,
  insecure: PHPIPAM_INSECURE,
});

const TOOLS: Tool[] = [
  {
    name: "list_sections",
    description:
      "List all IP address sections (top-level containers) in phpIPAM. " +
      "Sections organize subnets by location, team, or function. Use this to discover available section IDs before listing subnets.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "list_subnets",
    description:
      "List subnets in phpIPAM. Optionally scope to a single section by section_id. " +
      "Returns subnet CIDR, description, VLAN, VRF, and folder/full status. " +
      "Use list_sections first to find a section_id.",
    inputSchema: {
      type: "object",
      properties: {
        section_id: {
          type: "number",
          description: "Filter to subnets within this section ID (from list_sections). Omit for all subnets.",
        },
      },
    },
  },
  {
    name: "search_subnets",
    description:
      "Search subnets by CIDR notation or description keyword (e.g. '10.0.0.0', '10.0.0', 'dmz'). " +
      "Returns matching subnets with their IDs for use in other subnet tools.",
    inputSchema: {
      type: "object",
      properties: {
        term: {
          type: "string",
          description: "CIDR block or description keyword to search for.",
        },
      },
      required: ["term"],
    },
  },
  {
    name: "get_subnet",
    description:
      "Get full details for a specific subnet by its phpIPAM subnet ID, including CIDR, mask, VLAN, VRF, and description.",
    inputSchema: {
      type: "object",
      properties: {
        subnet_id: {
          type: "number",
          description: "phpIPAM numeric subnet ID.",
        },
      },
      required: ["subnet_id"],
    },
  },
  {
    name: "get_subnet_usage",
    description:
      "Get IP utilization statistics for a subnet: total hosts, used, free, and percentages by state (used/free/reserved/DHCP/offline). " +
      "Use to assess subnet capacity.",
    inputSchema: {
      type: "object",
      properties: {
        subnet_id: {
          type: "number",
          description: "phpIPAM numeric subnet ID.",
        },
      },
      required: ["subnet_id"],
    },
  },
  {
    name: "get_first_free_ip",
    description:
      "Return the first available (unassigned) IP address in a subnet. " +
      "Use when provisioning a new host or VM that needs an IP from a specific subnet.",
    inputSchema: {
      type: "object",
      properties: {
        subnet_id: {
          type: "number",
          description: "phpIPAM numeric subnet ID.",
        },
      },
      required: ["subnet_id"],
    },
  },
  {
    name: "list_addresses",
    description:
      "List all IP address assignments within a subnet, including hostname, description, MAC, owner, and last-seen date. " +
      "Use to audit what is assigned in a subnet or to find a free slot.",
    inputSchema: {
      type: "object",
      properties: {
        subnet_id: {
          type: "number",
          description: "phpIPAM numeric subnet ID.",
        },
      },
      required: ["subnet_id"],
    },
  },
  {
    name: "search_address",
    description:
      "Search for a specific IP address or hostname across all subnets. " +
      "Returns the address record with its subnet, hostname, description, owner, and MAC.",
    inputSchema: {
      type: "object",
      properties: {
        ip: {
          type: "string",
          description: "IP address to look up (e.g. '10.0.0.50').",
        },
      },
      required: ["ip"],
    },
  },
  {
    name: "list_vlans",
    description:
      "List all VLANs configured in phpIPAM with their VLAN number, name, domain, and description. " +
      "Use to find VLAN IDs for cross-referencing with subnets.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "search_vlans",
    description:
      "Search VLANs by name or number keyword (e.g. 'mgmt', '100').",
    inputSchema: {
      type: "object",
      properties: {
        term: {
          type: "string",
          description: "VLAN name or number keyword to search for.",
        },
      },
      required: ["term"],
    },
  },
  {
    name: "list_devices",
    description:
      "List all network devices tracked in phpIPAM with hostname, IP, type, and location.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "search_devices",
    description:
      "Search network devices by hostname or IP keyword.",
    inputSchema: {
      type: "object",
      properties: {
        term: {
          type: "string",
          description: "Hostname or IP keyword to search for.",
        },
      },
      required: ["term"],
    },
  },
  {
    name: "list_vrfs",
    description:
      "List all VRFs (Virtual Routing and Forwarding instances) in phpIPAM with their route-distinguisher and description.",
    inputSchema: { type: "object", properties: {} },
  },
];

function createServer(): Server {
  const server = new Server(
    { name: "phpipam-mcp-server", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

  function fmt(val: string | null | undefined, fallback = "—"): string {
    return val?.trim() || fallback;
  }

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const a = (args ?? {}) as Record<string, unknown>;

    try {
      switch (name) {
        case "list_sections": {
          const sections = await client.listSections();
          if (!sections?.length) {
            return { content: [{ type: "text", text: "No sections found." }] };
          }
          const lines = sections.map(
            (s) =>
              `[${s.id}] ${s.name}${s.description ? ` — ${s.description}` : ""}${s.masterSection !== "0" ? ` (child of section ${s.masterSection})` : ""}`
          );
          return { content: [{ type: "text", text: `${sections.length} section(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_subnets": {
          const sectionId = a.section_id as number | undefined;
          const subnets = sectionId
            ? await client.listSectionSubnets(sectionId)
            : await client.listSubnets();
          if (!subnets?.length) {
            return { content: [{ type: "text", text: "No subnets found." }] };
          }
          const lines = subnets.map(
            (s) =>
              `[${s.id}] ${s.subnet}/${s.mask}${s.description ? ` — ${s.description}` : ""}` +
              `${s.vlanId && s.vlanId !== "0" ? ` | VLAN ${s.vlanId}` : ""}` +
              `${s.vrfId && s.vrfId !== "0" ? ` | VRF ${s.vrfId}` : ""}` +
              `${s.isFull === "1" ? " [FULL]" : ""}` +
              `${s.isFolder === "1" ? " [folder]" : ""}`
          );
          return { content: [{ type: "text", text: `${subnets.length} subnet(s):\n\n${lines.join("\n")}` }] };
        }

        case "search_subnets": {
          const term = a.term as string;
          const subnets = await client.searchSubnets(term);
          if (!subnets?.length) {
            return { content: [{ type: "text", text: `No subnets matching "${term}".` }] };
          }
          const lines = subnets.map(
            (s) =>
              `[${s.id}] ${s.subnet}/${s.mask}${s.description ? ` — ${s.description}` : ""}` +
              `${s.vlanId && s.vlanId !== "0" ? ` | VLAN ${s.vlanId}` : ""}` +
              `${s.vrfId && s.vrfId !== "0" ? ` | VRF ${s.vrfId}` : ""}`
          );
          return { content: [{ type: "text", text: `${subnets.length} matching subnet(s):\n\n${lines.join("\n")}` }] };
        }

        case "get_subnet": {
          const subnet = await client.getSubnet(a.subnet_id as number);
          const lines = [
            `ID: ${subnet.id}`,
            `CIDR: ${subnet.subnet}/${subnet.mask}`,
            `Description: ${fmt(subnet.description)}`,
            `Section: ${subnet.sectionId}`,
            `VLAN ID: ${subnet.vlanId ?? "—"}`,
            `VRF ID: ${subnet.vrfId ?? "—"}`,
            `Master subnet: ${subnet.masterSubnetId === "0" ? "— (root)" : subnet.masterSubnetId}`,
            `Is folder: ${subnet.isFolder === "1" ? "Yes" : "No"}`,
            `Full: ${subnet.isFull === "1" ? "Yes" : "No"}`,
            `Show name: ${subnet.showName === "1" ? "Yes" : "No"}`,
            `Location: ${fmt(subnet.location)}`,
          ];
          return { content: [{ type: "text", text: lines.join("\n") }] };
        }

        case "get_subnet_usage": {
          const usage = await client.getSubnetUsage(a.subnet_id as number);
          const lines = [
            `Total hosts:    ${usage.maxhosts}`,
            `Used:           ${usage.used} (${usage.Used_percent?.toFixed(1)}%)`,
            `Free:           ${usage.freehosts} (${usage.freehosts_percent?.toFixed(1)}%)`,
            `Reserved:       ${usage.reserved_percent?.toFixed(1)}%`,
            `DHCP:           ${usage.dhcp_percent?.toFixed(1)}%`,
            `Offline:        ${usage.Offline_percent?.toFixed(1)}%`,
          ];
          return { content: [{ type: "text", text: lines.join("\n") }] };
        }

        case "get_first_free_ip": {
          const ip = await client.getFirstFreeAddress(a.subnet_id as number);
          return { content: [{ type: "text", text: `First available IP in subnet ${a.subnet_id}: ${ip}` }] };
        }

        case "list_addresses": {
          const addresses = await client.listSubnetAddresses(a.subnet_id as number);
          if (!addresses?.length) {
            return { content: [{ type: "text", text: "No addresses assigned in this subnet." }] };
          }
          const lines = addresses.map(
            (addr) =>
              `${addr.ip}` +
              `${addr.hostname ? ` (${addr.hostname})` : ""}` +
              `${addr.description ? ` — ${addr.description}` : ""}` +
              `${addr.mac ? ` | MAC: ${addr.mac}` : ""}` +
              `${addr.owner ? ` | owner: ${addr.owner}` : ""}` +
              `${addr.is_gateway === "1" ? " [GW]" : ""}` +
              `${addr.lastSeen ? ` | last seen: ${addr.lastSeen}` : ""}`
          );
          return { content: [{ type: "text", text: `${addresses.length} address(es):\n\n${lines.join("\n")}` }] };
        }

        case "search_address": {
          const addresses = await client.searchAddress(a.ip as string);
          if (!addresses?.length) {
            return { content: [{ type: "text", text: `No address record found for ${a.ip}.` }] };
          }
          const lines = addresses.map(
            (addr) =>
              `[id:${addr.id}] ${addr.ip}` +
              `${addr.hostname ? ` (${addr.hostname})` : ""}` +
              `${addr.description ? ` — ${addr.description}` : ""}` +
              ` | subnet: ${addr.subnetId}` +
              `${addr.mac ? ` | MAC: ${addr.mac}` : ""}` +
              `${addr.owner ? ` | owner: ${addr.owner}` : ""}` +
              `${addr.is_gateway === "1" ? " [GW]" : ""}` +
              `${addr.lastSeen ? ` | last seen: ${addr.lastSeen}` : ""}`
          );
          return { content: [{ type: "text", text: `${addresses.length} result(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_vlans": {
          const vlans = await client.listVlans();
          if (!vlans?.length) {
            return { content: [{ type: "text", text: "No VLANs found." }] };
          }
          const lines = vlans.map(
            (v) =>
              `[${v.vlanId}] VLAN ${v.number} — ${v.name}` +
              `${v.description ? ` (${v.description})` : ""}` +
              ` | domain: ${v.domainId}`
          );
          return { content: [{ type: "text", text: `${vlans.length} VLAN(s):\n\n${lines.join("\n")}` }] };
        }

        case "search_vlans": {
          const vlans = await client.searchVlans(a.term as string);
          if (!vlans?.length) {
            return { content: [{ type: "text", text: `No VLANs matching "${a.term}".` }] };
          }
          const lines = vlans.map(
            (v) => `[${v.vlanId}] VLAN ${v.number} — ${v.name}${v.description ? ` (${v.description})` : ""}`
          );
          return { content: [{ type: "text", text: `${vlans.length} VLAN(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_devices": {
          const devices = await client.listDevices();
          if (!devices?.length) {
            return { content: [{ type: "text", text: "No devices found." }] };
          }
          const lines = devices.map(
            (d) =>
              `[${d.id}] ${d.hostname || "unnamed"} — ${d.ip}` +
              `${d.type ? ` | type: ${d.type}` : ""}` +
              `${d.description ? ` | ${d.description}` : ""}` +
              `${d.location ? ` | loc: ${d.location}` : ""}`
          );
          return { content: [{ type: "text", text: `${devices.length} device(s):\n\n${lines.join("\n")}` }] };
        }

        case "search_devices": {
          const devices = await client.searchDevices(a.term as string);
          if (!devices?.length) {
            return { content: [{ type: "text", text: `No devices matching "${a.term}".` }] };
          }
          const lines = devices.map(
            (d) => `[${d.id}] ${d.hostname || "unnamed"} — ${d.ip}${d.type ? ` | type: ${d.type}` : ""}`
          );
          return { content: [{ type: "text", text: `${devices.length} device(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_vrfs": {
          const vrfs = await client.listVrfs();
          if (!vrfs?.length) {
            return { content: [{ type: "text", text: "No VRFs found." }] };
          }
          const lines = vrfs.map(
            (v) =>
              `[${v.vrfId}] ${v.name}` +
              `${v.rd ? ` | RD: ${v.rd}` : ""}` +
              `${v.description ? ` — ${v.description}` : ""}`
          );
          return { content: [{ type: "text", text: `${vrfs.length} VRF(s):\n\n${lines.join("\n")}` }] };
        }

        default:
          return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : String(error);
      return { content: [{ type: "text", text: `phpIPAM API error: ${msg}` }], isError: true };
    }
  });

  return server;
}

await startServer(createServer, "phpIPAM MCP server");
