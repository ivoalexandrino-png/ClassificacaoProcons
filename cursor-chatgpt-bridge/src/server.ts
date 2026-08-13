import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import { toNodeHandler } from "@modelcontextprotocol/node";
import { errorResponse } from "./errors.js";
import { Logger } from "./logger.js";
import {
  cancelRunSchema,
  emptyInputSchema,
  getAgentSchema,
  getChangesSchema,
  getConversationSchema,
  getRunSchema,
  registerProjectSchema,
  sendFollowupSchema,
  startAgentSchema,
} from "./mcp/schemas.js";
import { BridgeTools } from "./mcp/tools.js";
import { isAuthorized } from "./security/auth.js";
import type { BridgeStore } from "./storage/store.js";
import type { CursorAgentProvider } from "./cursor/types.js";

function toolResult(value: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
    structuredContent: value,
  };
}

async function callTool(action: () => Record<string, unknown> | Promise<Record<string, unknown>>) {
  try {
    return toolResult(await action());
  } catch (error) {
    const response = errorResponse(error);
    return {
      ...toolResult(response),
      isError: true,
    };
  }
}

export function createBridgeMcpServer(tools: BridgeTools): McpServer {
  const server = new McpServer({
    name: "cursor-chatgpt-bridge",
    version: "0.1.0",
  });

  server.registerTool(
    "cursor_list_agents",
    {
      description: "List Cursor agents and sessions known to this bridge.",
      inputSchema: emptyInputSchema,
      annotations: { readOnlyHint: true },
    },
    () => callTool(() => tools.listAgents()),
  );
  server.registerTool(
    "cursor_get_agent",
    {
      description: "Get one Cursor agent, active run, project metadata, and capabilities.",
      inputSchema: getAgentSchema,
      annotations: { readOnlyHint: true },
    },
    ({ agent_id }) => callTool(() => tools.getAgent(agent_id)),
  );
  server.registerTool(
    "cursor_get_conversation",
    {
      description: "Read recent persisted user, assistant, tool, and system messages.",
      inputSchema: getConversationSchema,
      annotations: { readOnlyHint: true },
    },
    ({ agent_id, limit }) => callTool(() => tools.getConversation(agent_id, limit)),
  );
  server.registerTool(
    "cursor_send_followup",
    {
      description: "Continue an existing Cursor agent session with preserved context.",
      inputSchema: sendFollowupSchema,
    },
    (input) => callTool(() => tools.sendFollowup(input)),
  );
  server.registerTool(
    "cursor_start_agent",
    {
      description: "Start a local or cloud Cursor agent for a registered project.",
      inputSchema: startAgentSchema,
    },
    (input) => callTool(() => tools.startAgent(input)),
  );
  server.registerTool(
    "cursor_get_run",
    {
      description: "Read and refresh the state and result of a Cursor run.",
      inputSchema: getRunSchema,
      annotations: { readOnlyHint: true },
    },
    ({ run_id }) => callTool(() => tools.getRun(run_id)),
  );
  server.registerTool(
    "cursor_cancel_run",
    {
      description: "Cancel a Cursor run only when the official SDK supports cancellation.",
      inputSchema: cancelRunSchema,
      annotations: { destructiveHint: true },
    },
    ({ run_id }) => callTool(() => tools.cancelRun(run_id)),
  );
  server.registerTool(
    "cursor_get_changes",
    {
      description: "Inspect bounded git status, diff, diff stat, and recent commits for a local agent.",
      inputSchema: getChangesSchema,
      annotations: { readOnlyHint: true },
    },
    ({ agent_id, max_diff_chars }) =>
      callTool(() => tools.getChanges(agent_id, max_diff_chars)),
  );
  server.registerTool(
    "cursor_project_register",
    {
      description: "Register an immutable project-to-repository mapping.",
      inputSchema: registerProjectSchema,
    },
    (input) => callTool(() => tools.registerProject(input)),
  );
  server.registerTool(
    "cursor_list_projects",
    {
      description: "List projects registered with the bridge.",
      inputSchema: emptyInputSchema,
      annotations: { readOnlyHint: true },
    },
    () => callTool(() => tools.listProjects()),
  );
  return server;
}

export interface HttpServerOptions {
  host: string;
  port: number;
  bridgeToken: string;
  store: BridgeStore;
  provider: CursorAgentProvider;
  tools: BridgeTools;
  logger: Logger;
}

function json(res: ServerResponse, status: number, value: Record<string, unknown>): void {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(value));
}

function rejectUnauthorized(res: ServerResponse): void {
  res.setHeader("WWW-Authenticate", 'Bearer realm="cursor-chatgpt-bridge"');
  json(res, 401, {
    error: {
      code: "UNAUTHORIZED",
      message: "Missing or invalid bearer token",
      details: {},
    },
  });
}

function authorizationHeader(req: IncomingMessage): string | undefined {
  const value = req.headers.authorization;
  return typeof value === "string" ? value : undefined;
}

function databaseHealth(store: BridgeStore): "ok" | "error" {
  try {
    return store.isHealthy() ? "ok" : "error";
  } catch {
    return "error";
  }
}

function requestPath(req: IncomingMessage): string | undefined {
  const rawUrl = req.url ?? "/";
  if (!rawUrl.startsWith("/")) return undefined;
  try {
    return new URL(rawUrl, "http://localhost").pathname;
  } catch {
    return undefined;
  }
}

export function createHttpServer(options: HttpServerOptions): Server {
  const handler = createMcpHandler(() => createBridgeMcpServer(options.tools));
  const nodeHandler = toNodeHandler(handler, {
    onerror: (error) => options.logger.error("mcp_transport_error", { message: error.message }),
  });

  return createServer((req, res) => {
    const pathname = requestPath(req);
    if (!pathname) {
      json(res, 400, {
        error: { code: "INVALID_INPUT", message: "Malformed request URL", details: {} },
      });
      return;
    }
    if (req.method === "GET" && pathname === "/health") {
      const database = databaseHealth(options.store);
      json(res, database === "ok" ? 200 : 503, {
        status: database === "ok" ? "ok" : "error",
        service: "cursor-chatgpt-bridge",
        cursor_sdk_configured: options.provider.isConfigured(),
        database,
      });
      return;
    }
    if (pathname !== "/mcp") {
      json(res, 404, {
        error: { code: "NOT_FOUND", message: "Route not found", details: {} },
      });
      return;
    }
    if (!isAuthorized(authorizationHeader(req), options.bridgeToken)) {
      rejectUnauthorized(res);
      return;
    }
    void nodeHandler(req, res);
  });
}
