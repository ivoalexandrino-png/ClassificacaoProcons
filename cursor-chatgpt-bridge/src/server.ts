import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isCursorSdkConfigured, loadConfig, type AppConfig } from "./config.js";
import { AgentService } from "./cursor/agents.js";
import { CursorSdkProvider } from "./cursor/client.js";
import { RunService } from "./cursor/runs.js";
import { createLogger } from "./logger.js";
import { registerMcpTools } from "./mcp/tools.js";
import { isAuthorized } from "./security/auth.js";
import { BridgeStore } from "./storage/store.js";

const MCP_SERVER_INFO = {
  name: "cursor-chatgpt-bridge",
  version: "0.1.0",
};

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function parseJsonBody(raw: string): unknown {
  if (!raw) {
    return undefined;
  }
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return undefined;
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function setCorsHeaders(res: ServerResponse): void {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type, Authorization, Accept, Mcp-Session-Id, Mcp-Protocol-Version",
  );
  res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");
}

function createMcpServer(ctx: {
  store: BridgeStore;
  agentService: AgentService;
  runService: RunService;
  cursor: CursorSdkProvider;
}): McpServer {
  const server = new McpServer(MCP_SERVER_INFO, {
    instructions:
      "Bridge between ChatGPT and Cursor Agents. Use cursor_list_projects and cursor_list_agents to find sessions, cursor_get_conversation and cursor_get_changes to review work, and cursor_send_followup to continue agents.",
  });
  registerMcpTools(server, ctx);
  return server;
}

export async function startHttpServer(config: AppConfig): Promise<void> {
  const logger = createLogger(config);
  const store = new BridgeStore(config.databasePath);
  const cursor = new CursorSdkProvider(config, logger);
  const agentService = new AgentService(store);
  const runService = new RunService(store, cursor, logger, config.runTimeoutMs);

  const mcpServer = createMcpServer({
    store,
    agentService,
    runService,
    cursor,
  });

  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });

  await mcpServer.connect(transport);

  const server = createServer(async (req, res) => {
    setCorsHeaders(res);

    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }

    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);

    if (req.method === "GET" && url.pathname === "/health") {
      sendJson(res, 200, {
        status: "ok",
        service: "cursor-chatgpt-bridge",
        cursor_sdk_configured: isCursorSdkConfigured(config),
        database: store.healthCheck() ? "ok" : "error",
      });
      return;
    }

    if (url.pathname === config.mcpPath) {
      if (!isAuthorized(config.bridgeToken, req.headers.authorization)) {
        sendJson(res, 401, {
          error: {
            code: "UNAUTHORIZED",
            message: "Missing or invalid Bearer token",
          },
        });
        return;
      }

      const rawBody = req.method === "POST" ? await readBody(req) : undefined;
      const parsedBody = rawBody ? parseJsonBody(rawBody) : undefined;
      await transport.handleRequest(req, res, parsedBody);
      return;
    }

    sendJson(res, 404, {
      error: {
        code: "INTERNAL_ERROR",
        message: "Not found",
      },
    });
  });

  server.listen(config.port, () => {
    logger.info("server_started", {
      port: config.port,
      mcp_path: config.mcpPath,
      transport: "http",
    });
  });
}

export async function startStdioServer(config: AppConfig): Promise<void> {
  const logger = createLogger(config);
  const store = new BridgeStore(config.databasePath);
  const cursor = new CursorSdkProvider(config, logger);
  const agentService = new AgentService(store);
  const runService = new RunService(store, cursor, logger, config.runTimeoutMs);

  const mcpServer = createMcpServer({
    store,
    agentService,
    runService,
    cursor,
  });

  const transport = new StdioServerTransport();
  await mcpServer.connect(transport);
  logger.info("server_started", { transport: "stdio" });
}

export async function startServer(config?: AppConfig): Promise<void> {
  const resolved = config ?? loadConfig();
  if (!resolved.bridgeToken) {
    throw new Error("CURSOR_BRIDGE_TOKEN is required");
  }

  if (resolved.transport === "stdio") {
    await startStdioServer(resolved);
    return;
  }

  await startHttpServer(resolved);
}
