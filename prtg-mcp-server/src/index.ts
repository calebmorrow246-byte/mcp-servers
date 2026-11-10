import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { startServer, type RequestContext } from "./transport.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { PrtgClient, PRTG_STATUS } from "./prtg-client.js";

const PRTG_BASE_URL = process.env.PRTG_BASE_URL;
const PRTG_API_TOKEN = process.env.PRTG_API_TOKEN;
const PRTG_INSECURE = process.env.PRTG_INSECURE === "true";

// PRTG access is per user: when hosted over HTTP each caller sends their own API token in this
// header, so PRTG attributes pauses/resumes to them. Locally (stdio) the launcher's token is used.
const USER_TOKEN_HEADER = "x-prtg-api-token";
const HTTP_MODE = (process.env.MCP_TRANSPORT ?? "stdio").toLowerCase() === "http";

if (!PRTG_BASE_URL || (!HTTP_MODE && !PRTG_API_TOKEN)) {
  console.error("Error: PRTG_BASE_URL and PRTG_API_TOKEN environment variables are required.");
  process.exit(1);
}
const BASE_URL: string = PRTG_BASE_URL;

const TOOLS: Tool[] = [
  {
    name: "get_active_alarms",
    description:
      "Get all active alarms and alerts from PRTG. Returns sensors that are Down, Warning, or Down (Acknowledged). " +
      "Use this to check current infrastructure health or investigate incidents.",
    inputSchema: {
      type: "object",
      properties: {
        status_filter: {
          type: "string",
          description:
            "Filter by specific status. Leave empty to return all active alarms.",
          enum: ["down", "warning", "down_acknowledged", "down_partial"],
        },
        count: {
          type: "number",
          description: "Max alarms to return (default 100, max 500).",
        },
      },
    },
  },
  {
    name: "get_sensor_details",
    description:
      "Get full details for a specific PRTG sensor by its object ID (objid). " +
      "Includes uptime/downtime history, last check time, status message, and tags.",
    inputSchema: {
      type: "object",
      properties: {
        sensor_id: {
          type: "number",
          description: "The PRTG object ID (objid) of the sensor.",
        },
      },
      required: ["sensor_id"],
    },
  },
  {
    name: "list_sensors",
    description:
      "List PRTG sensors with optional filtering by status, name, device, group, or probe. " +
      "Useful for finding sensor IDs or reviewing sensor health across a device or group.",
    inputSchema: {
      type: "object",
      properties: {
        status_filter: {
          type: "string",
          description:
            "Filter by status. Options: up, warning, down, paused, down_acknowledged, down_partial.",
          enum: ["up", "warning", "down", "paused", "down_acknowledged", "down_partial"],
        },
        name_filter: {
          type: "string",
          description: "Filter by sensor name (case-insensitive substring match).",
        },
        device_filter: {
          type: "string",
          description: "Filter by device name (case-insensitive substring match).",
        },
        group_filter: {
          type: "string",
          description: "Filter by group name (case-insensitive substring match).",
        },
        probe_filter: {
          type: "string",
          description: "Filter by probe name (case-insensitive substring match).",
        },
        tag_filter: {
          type: "string",
          description: "Filter by tag (case-insensitive substring match against sensor tags).",
        },
        count: {
          type: "number",
          description: "Max sensors to return (default 200).",
        },
      },
    },
  },
  {
    name: "pause_sensor",
    description:
      "Pause a PRTG sensor to suppress alerts during maintenance. " +
      "Always include a clear reason message for the audit trail.",
    inputSchema: {
      type: "object",
      properties: {
        sensor_id: {
          type: "number",
          description: "The PRTG object ID of the sensor to pause.",
        },
        message: {
          type: "string",
          description: "Reason for pausing — recorded in the PRTG audit log.",
        },
        duration_minutes: {
          type: "number",
          description:
            "How long to pause in minutes. Omit to pause indefinitely until manually resumed.",
        },
      },
      required: ["sensor_id", "message"],
    },
  },
  {
    name: "resume_sensor",
    description: "Resume a paused PRTG sensor and restore normal monitoring.",
    inputSchema: {
      type: "object",
      properties: {
        sensor_id: {
          type: "number",
          description: "The PRTG object ID of the sensor to resume.",
        },
      },
      required: ["sensor_id"],
    },
  },
];

function stripHtml(text: string): string {
  return (text ?? "").replace(/<[^>]*>/g, "").trim();
}

function stars(priority: string): string {
  const n = parseInt(priority, 10);
  return isNaN(n) ? "" : "★".repeat(Math.min(n, 5));
}

function createServer(context: RequestContext): Server {
  const token = context.credentials[USER_TOKEN_HEADER] ?? (HTTP_MODE ? undefined : PRTG_API_TOKEN);
  const prtg = token ? new PrtgClient({ baseUrl: BASE_URL, apiToken: token, insecure: PRTG_INSECURE }) : undefined;

  const server = new Server(
    { name: "prtg-mcp-server", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const a = (args ?? {}) as Record<string, unknown>;

    if (!prtg) {
      return {
        content: [{ type: "text", text: "PRTG access is per user: no PRTG API token was sent. Store your own token in Credential Manager as 'PRTG API' and start Claude Code with the MCP launcher so it is sent as the X-PRTG-Api-Token header." }],
        isError: true,
      };
    }

    try {
      switch (name) {
        case "get_active_alarms": {
          const statusFilter = a.status_filter as string | undefined;
          const count = a.count as number | undefined;
          const numericFilter = statusFilter ? PRTG_STATUS[statusFilter] : undefined;

          const result = await prtg.getActiveAlarms({ count: count ?? 100, statusFilter: numericFilter });
          const alarms = result.alarms ?? [];

          if (alarms.length === 0) {
            return { content: [{ type: "text", text: "No active alarms found." }] };
          }

          const lines = alarms.map((alarm) =>
            [
              `[ID: ${alarm.objid}] ${alarm.name}`,
              `  Status:   ${alarm.status}`,
              `  Device:   ${alarm.device}`,
              `  Group:    ${alarm.group}`,
              `  Message:  ${stripHtml(alarm.message)}`,
              `  Priority: ${stars(alarm.priority)} (${alarm.priority})`,
              alarm.tags ? `  Tags:     ${alarm.tags}` : "",
            ]
              .filter(Boolean)
              .join("\n")
          );

          return {
            content: [
              {
                type: "text",
                text: `${alarms.length} active alarm(s)${statusFilter ? ` (${statusFilter})` : ""}:\n\n${lines.join("\n\n")}`,
              },
            ],
          };
        }

        case "get_sensor_details": {
          const sensorId = a.sensor_id as number;
          const result = await prtg.getSensorDetails(sensorId);
          const d = result.sensordata;

          const text = [
            `Sensor Details — ID ${sensorId}`,
            `  Name:          ${d.name}`,
            `  Type:          ${d.sensortype}`,
            `  Status:        ${d.statustext}`,
            `  Message:       ${stripHtml(d.message)}`,
            `  Check interval:${d.intervaltext}`,
            `  Last check:    ${d.lastcheck}`,
            `  Last up:       ${d.lastup}`,
            `  Last down:     ${d.lastdown}`,
            `  Uptime:        ${d.uptime} (${d.uptimetime})`,
            `  Downtime:      ${d.downtime} (${d.downtimetime})`,
            `  Monitoring since: ${d.cumsince}`,
            `  Priority:      ${stars(d.priority)} (${d.priority})`,
            d.tags ? `  Tags:          ${d.tags}` : "",
          ]
            .filter(Boolean)
            .join("\n");

          return { content: [{ type: "text", text }] };
        }

        case "list_sensors": {
          const statusFilter = a.status_filter as string | undefined;
          const nameFilter = a.name_filter as string | undefined;
          const deviceFilter = a.device_filter as string | undefined;
          const groupFilter = a.group_filter as string | undefined;
          const probeFilter = a.probe_filter as string | undefined;
          const tagFilter = a.tag_filter as string | undefined;
          const count = a.count as number | undefined;

          const result = await prtg.getSensors({
            count: count ?? 200,
            statusFilter: statusFilter ? PRTG_STATUS[statusFilter] : undefined,
            nameFilter,
            deviceFilter,
            groupFilter,
            probeFilter,
            tagFilter,
          });
          const sensors = result.sensors ?? [];

          if (sensors.length === 0) {
            return { content: [{ type: "text", text: "No sensors found matching the given criteria." }] };
          }

          const lines = sensors.map(
            (s) =>
              `[${s.objid}] ${s.name} | ${s.status} | ${s.device} (${s.group}) | ${stripHtml(s.message)}`
          );

          return {
            content: [
              {
                type: "text",
                text: `${sensors.length} sensor(s) found:\n\n${lines.join("\n")}`,
              },
            ],
          };
        }

        case "pause_sensor": {
          const sensorId = a.sensor_id as number;
          const message = a.message as string;
          const durationMinutes = a.duration_minutes as number | undefined;

          await prtg.pauseSensor(sensorId, message, durationMinutes);

          const duration = durationMinutes ? ` for ${durationMinutes} minute(s)` : " indefinitely";
          return {
            content: [
              {
                type: "text",
                text: `Sensor ${sensorId} paused${duration}.\nReason: ${message}`,
              },
            ],
          };
        }

        case "resume_sensor": {
          const sensorId = a.sensor_id as number;
          await prtg.resumeSensor(sensorId);
          return { content: [{ type: "text", text: `Sensor ${sensorId} resumed successfully.` }] };
        }

        default:
          return {
            content: [{ type: "text", text: `Unknown tool: ${name}` }],
            isError: true,
          };
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : String(error);
      return {
        content: [{ type: "text", text: `PRTG API error: ${msg}` }],
        isError: true,
      };
    }
  });

  return server;
}

await startServer(createServer, "PRTG MCP server", { credentialHeaders: [USER_TOKEN_HEADER] });
