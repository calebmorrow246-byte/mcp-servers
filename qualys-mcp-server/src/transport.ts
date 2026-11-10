import { createHash, timingSafeEqual } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { createServer as createHttpServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

/**
 * Starts the MCP server on the transport selected by environment variables:
 *
 *   MCP_TRANSPORT         stdio (default) - a local client launches this process and talks over stdin/stdout
 *                         http            - Streamable HTTP (stateless) at http://MCP_HOST:MCP_PORT/mcp
 *   MCP_HOST              bind address for http mode (default 127.0.0.1)
 *   MCP_PORT              port for http mode (required when MCP_TRANSPORT=http)
 *   MCP_AUTH_TOKENS_FILE  JSON list of per-user bearer token hashes (required when MCP_TRANSPORT=http):
 *                         { "tokens": [ { "user": "first.last", "sha256": "<hex of SHA-256(token)>" } ] }
 *
 * HTTP mode requires "Authorization: Bearer <token>" on every /mcp request, checks the token's
 * SHA-256 against the tokens file (re-read whenever it changes, so revocation is immediate), and
 * writes an audit line per request: user, JSON-RPC method, and tool name (never arguments).
 * It has no TLS of its own; it binds to loopback by default and is published through the TLS
 * front end. GET /health is unauthenticated and returns 200 for monitoring.
 *
 * Stateless mode builds a fresh Server per request, so createServer must be a factory. Servers
 * whose backend credential is per-user list the request headers that carry it in
 * options.credentialHeaders; those headers are handed to createServer in the RequestContext
 * (values never logged), and the audit line records cred=user when any is present, else cred=shared.
 * In stdio mode the context is empty and servers use their local credential.
 */
export interface RequestContext {
  /** Per-user backend credential headers (lower-case names) present on this request */
  credentials: Record<string, string>;
}

export interface StartOptions {
  /** Lower-case request header names that carry a user's own backend credential */
  credentialHeaders?: string[];
}

export async function startServer(
  createServer: (context: RequestContext) => Server,
  name: string,
  options: StartOptions = {}
): Promise<void> {
  const mode = (process.env.MCP_TRANSPORT ?? "stdio").toLowerCase();
  const credentialHeaders = (options.credentialHeaders ?? []).map((h) => h.toLowerCase());

  if (mode === "stdio") {
    await createServer({ credentials: {} }).connect(new StdioServerTransport());
    log(name, "running (stdio)");
    return;
  }
  if (mode !== "http") {
    throw new Error(`Unsupported MCP_TRANSPORT '${mode}' (use 'stdio' or 'http')`);
  }

  const host = process.env.MCP_HOST ?? "127.0.0.1";
  const port = Number(process.env.MCP_PORT);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("MCP_PORT must be set to a valid port number when MCP_TRANSPORT=http");
  }
  const tokensFile = process.env.MCP_AUTH_TOKENS_FILE;
  if (!tokensFile) {
    throw new Error("MCP_AUTH_TOKENS_FILE must be set when MCP_TRANSPORT=http");
  }
  const tokens = new TokenStore(tokensFile);
  tokens.load(); // fail at startup, not on the first request, if the file is missing or malformed

  const httpServer = createHttpServer(async (req, res) => {
    const path = new URL(req.url ?? "/", "http://localhost").pathname;

    if (path === "/health" && req.method === "GET") {
      res.writeHead(200, { "Content-Type": "application/json" }).end(JSON.stringify({ status: "ok", server: name }));
      return;
    }
    if (path !== "/mcp") {
      res.writeHead(404).end();
      return;
    }
    // Stateless server: no sessions, so no server-initiated GET stream and nothing to DELETE
    if (req.method !== "POST") {
      sendJsonRpcError(res, 405, "Method not allowed");
      return;
    }

    // Behind the TLS front end every connection comes from loopback; log the forwarded client instead
    const forwarded = req.headers["x-forwarded-for"];
    const from = (Array.isArray(forwarded) ? forwarded[0] : forwarded)?.split(",")[0].trim() || req.socket.remoteAddress;

    let user: string | undefined;
    try {
      user = tokens.authenticate(req.headers.authorization);
    } catch (error: unknown) {
      log(name, `auth unavailable: ${error instanceof Error ? error.message : String(error)}`);
      sendJsonRpcError(res, 503, "Authentication unavailable");
      return;
    }
    if (!user) {
      log(name, `audit user=- status=401 from=${from}`);
      res.setHeader("WWW-Authenticate", 'Bearer realm="mcp"');
      sendJsonRpcError(res, 401, "Unauthorized");
      return;
    }

    let body: unknown;
    try {
      body = JSON.parse(await readBody(req));
    } catch {
      sendJsonRpcError(res, 400, "Parse error", -32700);
      return;
    }
    // Per-user backend credentials (only the headers this server declares; values never logged)
    const credentials: Record<string, string> = {};
    for (const header of credentialHeaders) {
      const value = req.headers[header];
      const first = Array.isArray(value) ? value[0] : value;
      if (first && first.trim()) credentials[header] = first.trim();
    }
    const credKind = credentialHeaders.length === 0 ? "" : Object.keys(credentials).length > 0 ? " cred=user" : " cred=none";
    log(name, `audit user=${user} from=${from}${credKind} ${describe(body)}`);

    const server = createServer({ credentials });
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on("close", () => {
      void transport.close();
      void server.close();
    });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, body);
    } catch (error: unknown) {
      log(name, `request failed: ${error instanceof Error ? error.message : String(error)}`);
      if (!res.headersSent) sendJsonRpcError(res, 500, "Internal server error");
    }
  });

  httpServer.listen(port, host, () => log(name, `running (Streamable HTTP) on http://${host}:${port}/mcp`));
}

/** Per-user bearer token hashes from MCP_AUTH_TOKENS_FILE, reloaded when the file changes. */
class TokenStore {
  private entries: { user: string; hash: Buffer }[] = [];
  private loadedMtime = -1;

  constructor(private readonly file: string) {}

  load(): void {
    const mtime = statSync(this.file).mtimeMs;
    if (mtime === this.loadedMtime) return;
    const parsed = JSON.parse(readFileSync(this.file, "utf8")) as { tokens?: { user?: string; sha256?: string }[] };
    this.entries = (parsed.tokens ?? [])
      .filter((t): t is { user: string; sha256: string } => !!t.user && /^[0-9a-f]{64}$/i.test(t.sha256 ?? ""))
      .map((t) => ({ user: t.user, hash: Buffer.from(t.sha256, "hex") }));
    this.loadedMtime = mtime;
  }

  /** Returns the user name for a valid "Bearer <token>" header, otherwise undefined. */
  authenticate(header: string | undefined): string | undefined {
    const match = /^Bearer\s+(\S+)$/i.exec(header ?? "");
    if (!match) return undefined;
    this.load();
    const presented = createHash("sha256").update(match[1]).digest();
    // Compare against every entry so timing doesn't reveal which (if any) matched
    let user: string | undefined;
    for (const entry of this.entries) {
      if (timingSafeEqual(presented, entry.hash) && user === undefined) user = entry.user;
    }
    return user;
  }
}

const MAX_BODY_BYTES = 4 * 1024 * 1024;

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    req.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new Error("Request body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

/** Audit summary of a JSON-RPC message or batch: method and tool name only, never arguments. */
function describe(body: unknown): string {
  const messages = Array.isArray(body) ? body : [body];
  return messages
    .map((m) => {
      const msg = m as { method?: unknown; params?: { name?: unknown } };
      const method = typeof msg?.method === "string" ? msg.method : "?";
      const tool = method === "tools/call" && typeof msg.params?.name === "string" ? ` tool=${msg.params.name}` : "";
      return `method=${method}${tool}`;
    })
    .join("; ");
}

function sendJsonRpcError(res: ServerResponse, status: number, message: string, code = -32000): void {
  res
    .writeHead(status, { "Content-Type": "application/json" })
    .end(JSON.stringify({ jsonrpc: "2.0", error: { code, message }, id: null }));
}

function log(name: string, message: string): void {
  console.error(`${new Date().toISOString()} ${name} ${message}`);
}
