import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { startServer } from "./transport.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { QualysClient } from "./qualys-client.js";
import { resolveCredentials } from "./creds.js";

const QUALYS_BASE_URL = process.env.QUALYS_BASE_URL;
const QUALYS_INSECURE = process.env.QUALYS_INSECURE === "true";
const QUALYS_KB_VERSION = process.env.QUALYS_KB_VERSION;

if (!QUALYS_BASE_URL) {
  console.error(
    "Error: QUALYS_BASE_URL is required (your platform/POD API URL, e.g. https://qualysapi.qg3.apps.qualys.com)."
  );
  process.exit(1);
}

const credentials = await resolveCredentials().catch((err: Error) => {
  console.error(`Error resolving Qualys credentials: ${err.message}`);
  process.exit(1);
});

const qualys = new QualysClient({
  baseUrl: QUALYS_BASE_URL,
  username: credentials.username,
  password: credentials.password,
  insecure: QUALYS_INSECURE,
  kbVersion: QUALYS_KB_VERSION,
});

const TOOLS: Tool[] = [
  {
    name: "list_host_detections",
    description:
      "List vulnerability detections on hosts from Qualys VMDR (Host List Detection API). " +
      "Returns one row per detected vulnerability (QID) per host. Use this to answer 'what vulnerabilities " +
      "are on host X' or 'show me all critical/severe findings'. Pair QIDs with get_vulnerability_info for titles and fixes.",
    inputSchema: {
      type: "object",
      properties: {
        tags: {
          type: "string",
          description:
            "Filter to hosts carrying these asset tags, comma-separated tag names (e.g. 'LF_Server_Infra,LF_Server_Security'). " +
            "When set, tag selection replaces the ips filter. Use list_tags to discover tag names.",
        },
        tag_match: {
          type: "string",
          description: "When multiple tags are given: 'any' (host has at least one, default) or 'all' (host has every tag).",
          enum: ["any", "all"],
        },
        ips: {
          type: "string",
          description: "Filter to specific IPs/ranges, comma-separated (e.g. '10.0.0.30,10.0.0.1-10.0.0.50'). Ignored if 'tags' is set. Omit for all hosts.",
        },
        severities: {
          type: "string",
          description: "Severity filter, 1-5. Accepts a list or range (e.g. '4,5' or '4-5'). 5 = most severe.",
        },
        qids: {
          type: "string",
          description: "Filter to specific QIDs, comma-separated.",
        },
        status: {
          type: "string",
          description: "Detection status filter.",
          enum: ["New", "Active", "Fixed", "Re-Opened"],
        },
        show_info_gathered: {
          type: "boolean",
          description: "Include Information Gathered (type IG) detections, not just confirmed/potential vulns. Default false.",
        },
        include_cloud_metadata: {
          type: "boolean",
          description:
            "Add Azure instance metadata (e.g. the VM name) to each row when an Azure connector has synced the host. " +
            "Default false; it makes responses larger.",
        },
        include_instance_details: {
          type: "boolean",
          description:
            "Add the fields that distinguish multi-instance detections of one QID on one host: unique vuln id, port, protocol, " +
            "FQDN, SSL flag, instance, and a truncated results excerpt. Emitted as ' | inst: key=value ...' right after 'last seen'. " +
            "Default false; it makes responses larger.",
        },
        limit: {
          type: "number",
          description: "Max host records to pull (truncation_limit). Default 500.",
        },
      },
    },
  },
  {
    name: "get_vulnerability_info",
    description:
      "Look up vulnerability details from the Qualys KnowledgeBase by QID or CVE. " +
      "Returns title, severity, category, CVEs, diagnosis, and remediation/solution. " +
      "Use after list_host_detections to explain a QID or find its fix.",
    inputSchema: {
      type: "object",
      properties: {
        qids: {
          type: "string",
          description: "One or more QIDs, comma-separated.",
        },
        cve_ids: {
          type: "string",
          description: "One or more CVE IDs, comma-separated (e.g. 'CVE-2021-44228').",
        },
      },
    },
  },
  {
    name: "list_scans",
    description:
      "List Qualys VM scans with their status (Running, Finished, Canceled, Error), launch time, duration, and target. " +
      "Use to check scan progress or find a recent scan reference.",
    inputSchema: {
      type: "object",
      properties: {
        state: {
          type: "string",
          description: "Filter by scan state.",
          enum: ["Running", "Paused", "Canceled", "Finished", "Error", "Queued", "Loading"],
        },
        scan_ref: {
          type: "string",
          description: "A specific scan reference (e.g. 'scan/1234567890.12345') to look up.",
        },
      },
    },
  },
  {
    name: "list_host_assets",
    description:
      "List host assets from the Qualys asset inventory (Host List API): IP, DNS, NetBIOS, OS, asset tags, tracking method, " +
      "and last scan dates. Use for inventory questions, to list what's in an asset tag, or to confirm a host is known to Qualys.",
    inputSchema: {
      type: "object",
      properties: {
        tags: {
          type: "string",
          description:
            "Filter to hosts carrying these asset tags, comma-separated tag names (e.g. 'LF_Server_All'). " +
            "When set, tag selection replaces the ips filter. Use list_tags to discover tag names.",
        },
        tag_match: {
          type: "string",
          description: "When multiple tags are given: 'any' (default) or 'all'.",
          enum: ["any", "all"],
        },
        ips: {
          type: "string",
          description: "Filter to specific IPs/ranges, comma-separated. Ignored if 'tags' is set. Omit for all hosts.",
        },
        include_cloud_metadata: {
          type: "boolean",
          description:
            "Add Azure instance metadata (e.g. the VM name) to each row when an Azure connector has synced the host. " +
            "Use this to get a clean host name when DNS shows an Azure-internal cloudapp.net name. Default false.",
        },
        limit: {
          type: "number",
          description: "Max host records (truncation_limit). Default 500.",
        },
      },
    },
  },
  {
    name: "list_tags",
    description:
      "List Qualys asset tags (Asset Management & Tagging) with their IDs. " +
      "Use to discover tag names before filtering hosts by tag, or to look up a tag's ID.",
    inputSchema: {
      type: "object",
      properties: {
        name_contains: {
          type: "string",
          description: "Filter to tags whose name contains this substring (e.g. 'LF_Server').",
        },
        limit: {
          type: "number",
          description: "Max tags to return. Default 200.",
        },
      },
    },
  },
  {
    name: "list_web_apps",
    description:
      "List web applications configured in Qualys Web Application Scanning (WAS). " +
      "Returns app ID, name, URL, and owner. Use to find a web app's ID before querying its findings.",
    inputSchema: {
      type: "object",
      properties: {
        name_contains: {
          type: "string",
          description: "Filter to web apps whose name contains this substring.",
        },
        limit: {
          type: "number",
          description: "Max web apps to return. Default 100.",
        },
      },
    },
  },
  {
    name: "list_was_findings",
    description:
      "List findings (detected vulnerabilities) from Qualys WAS, optionally scoped to a web app. " +
      "Returns QID, name, type, severity, status, and URL. Use to review web-app security posture.",
    inputSchema: {
      type: "object",
      properties: {
        web_app_id: {
          type: "string",
          description: "Scope findings to a single web app by its WAS ID (from list_web_apps).",
        },
        severity: {
          type: "string",
          description: "Severity filter 1-5 (5 = most severe).",
          enum: ["1", "2", "3", "4", "5"],
        },
        status: {
          type: "string",
          description: "Finding status filter.",
          enum: ["NEW", "ACTIVE", "REOPENED", "FIXED"],
        },
        limit: {
          type: "number",
          description: "Max findings to return. Default 100.",
        },
      },
    },
  },
];

function createServer(): Server {
  const server = new Server(
    { name: "qualys-mcp-server", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

  function sev(s: string): string {
    const n = parseInt(s, 10);
    return isNaN(n) ? s : `${"!".repeat(Math.min(n, 5))} (${n})`;
  }

  function truncate(s: string, max = 300): string {
    const t = (s ?? "").replace(/\s+/g, " ").trim();
    return t.length > max ? `${t.slice(0, max)}…` : t;
  }

  /** Render Azure metadata attributes as " | azure: name=value, ..." (empty when none). */
  function azureText(m: Record<string, string>): string {
    const parts = Object.entries(m).map(([k, v]) => `${k}=${truncate(v, 80)}`);
    return parts.length ? ` | azure: ${parts.join(", ")}` : "";
  }

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const a = (args ?? {}) as Record<string, unknown>;

    try {
      switch (name) {
        case "list_host_detections": {
          const rows = await qualys.listHostDetections({
            tags: a.tags as string | undefined,
            tagsMatch: a.tag_match as "any" | "all" | undefined,
            ips: a.ips as string | undefined,
            severities: a.severities as string | undefined,
            qids: a.qids as string | undefined,
            status: a.status as string | undefined,
            showIgs: a.show_info_gathered as boolean | undefined,
            includeCloudMetadata: a.include_cloud_metadata as boolean | undefined,
            includeResults: a.include_instance_details as boolean | undefined,
            truncationLimit: a.limit as number | undefined,
          });
          if (rows.length === 0) {
            return { content: [{ type: "text", text: "No detections found for the given filters." }] };
          }
          const wantInst = a.include_instance_details === true;
          // One-line instance descriptor; newlines in results are collapsed so each detection stays on one row.
          const inst = (d: (typeof rows)[number]) => {
            const kv: Array<[string, string]> = [
              ["uid", d.uniqueVulnId], ["port", d.port], ["proto", d.protocol], ["fqdn", d.fqdn],
              ["ssl", d.ssl], ["instance", d.instance], ["results", truncate(d.results.replace(/\s+/g, " ").trim(), 120)],
            ];
            return ` | inst: ${kv.filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(", ")}`;
          };
          const lines = rows.map(
            (d) =>
              `${d.ip}${d.dns ? ` (${d.dns})` : ""} | QID ${d.qid} | sev ${sev(d.severity)} | ${d.type} | ${d.status} | last seen ${d.lastFound}${wantInst ? inst(d) : ""}${d.tags ? ` | tags: ${d.tags}` : ""}${azureText(d.azure)}`
          );
          return {
            content: [{ type: "text", text: `${rows.length} detection(s):\n\n${lines.join("\n")}` }],
          };
        }

        case "get_vulnerability_info": {
          const vulns = await qualys.getVulnerabilityInfo({
            ids: a.qids as string | undefined,
            cveIds: a.cve_ids as string | undefined,
          });
          if (vulns.length === 0) {
            return { content: [{ type: "text", text: "No matching vulnerabilities in the KnowledgeBase." }] };
          }
          const blocks = vulns.map((v) =>
            [
              `QID ${v.qid} — ${v.title}`,
              `  Severity: ${sev(v.severity)}   Category: ${v.category}   Patchable: ${v.patchable}`,
              v.cveIds ? `  CVEs: ${v.cveIds}` : "",
              v.diagnosis ? `  Diagnosis: ${truncate(v.diagnosis, 400)}` : "",
              v.solution ? `  Solution:  ${truncate(v.solution, 400)}` : "",
            ]
              .filter(Boolean)
              .join("\n")
          );
          return { content: [{ type: "text", text: blocks.join("\n\n") }] };
        }

        case "list_scans": {
          const scans = await qualys.listScans({
            state: a.state as string | undefined,
            scanRef: a.scan_ref as string | undefined,
          });
          if (scans.length === 0) {
            return { content: [{ type: "text", text: "No scans found." }] };
          }
          const lines = scans.map(
            (s) => `[${s.ref}] ${s.title} | ${s.status} | launched ${s.launchDate} | ${s.duration} | ${s.type}`
          );
          return { content: [{ type: "text", text: `${scans.length} scan(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_host_assets": {
          const hosts = await qualys.listHostAssets({
            tags: a.tags as string | undefined,
            tagsMatch: a.tag_match as "any" | "all" | undefined,
            ips: a.ips as string | undefined,
            includeCloudMetadata: a.include_cloud_metadata as boolean | undefined,
            truncationLimit: a.limit as number | undefined,
          });
          if (hosts.length === 0) {
            return { content: [{ type: "text", text: "No host assets found." }] };
          }
          const lines = hosts.map(
            (h) =>
              `[${h.id}] ${h.ip}${h.dns ? ` (${h.dns})` : ""} | ${h.os || "OS unknown"} | track: ${h.tracking} | last scan ${h.lastScan}${h.tags ? ` | tags: ${h.tags}` : ""}${azureText(h.azure)}`
          );
          return { content: [{ type: "text", text: `${hosts.length} host asset(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_tags": {
          const tags = await qualys.listTags({
            nameContains: a.name_contains as string | undefined,
            limit: a.limit as number | undefined,
          });
          if (tags.length === 0) {
            return { content: [{ type: "text", text: "No tags found." }] };
          }
          const lines = tags.map((t) => `[${t.id}] ${t.name}${t.parentId ? ` (parent ${t.parentId})` : ""}`);
          return { content: [{ type: "text", text: `${tags.length} tag(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_web_apps": {
          const apps = await qualys.listWebApps({
            nameContains: a.name_contains as string | undefined,
            limit: a.limit as number | undefined,
          });
          if (apps.length === 0) {
            return { content: [{ type: "text", text: "No web apps found." }] };
          }
          const lines = apps.map((w) => `[${w.id}] ${w.name} | ${w.url} | owner: ${w.owner}`);
          return { content: [{ type: "text", text: `${apps.length} web app(s):\n\n${lines.join("\n")}` }] };
        }

        case "list_was_findings": {
          const findings = await qualys.listWasFindings({
            webAppId: a.web_app_id as string | undefined,
            severity: a.severity as string | undefined,
            status: a.status as string | undefined,
            limit: a.limit as number | undefined,
          });
          if (findings.length === 0) {
            return { content: [{ type: "text", text: "No WAS findings found for the given filters." }] };
          }
          const lines = findings.map(
            (f) =>
              `[${f.id}] QID ${f.qid} | ${f.name} | sev ${sev(f.severity)} | ${f.type} | ${f.status} | ${f.url}`
          );
          return { content: [{ type: "text", text: `${findings.length} finding(s):\n\n${lines.join("\n")}` }] };
        }

        default:
          return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : String(error);
      return { content: [{ type: "text", text: `Qualys API error: ${msg}` }], isError: true };
    }
  });

  return server;
}

await startServer(createServer, "Qualys MCP server");
