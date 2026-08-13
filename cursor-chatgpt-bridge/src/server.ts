import { randomUUID } from "node:crypto";
import type { Server as HttpServer } from "node:http";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";
import express, { type NextFunction, type Request, type Response } from "express";

import { redactedConfig } from "./config.js";
import { ErrorCodes } from "./errors.js";
import { registerTools, type ToolContext } from "./mcp/tools.js";
import { authorize } from "./security/auth.js";

const SERVER_NAME = "cursor-chatgpt-bridge";
const SERVER_VERSION = "0.1.0";

/** Build a fresh MCP server instance with all bridge tools registered. */
export function buildMcpServer(ctx: ToolContext): McpServer {
  const server = new McpServer({ name: SERVER_NAME, version: SERVER_VERSION });
  registerTools(server, ctx);
  return server;
}

function sendUnauthorized(res: Response, reason: string): void {
  res.status(401).json({
    error: { code: ErrorCodes.UNAUTHORIZED, message: reason, details: {} },
  });
}

/** Express middleware enforcing the bridge bearer token. */
function bearerAuth(ctx: ToolContext) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const auth = authorize(ctx.config.bridgeToken, req.header("authorization"));
    if (auth.ok) {
      next();
      return;
    }
    const reason =
      auth.reason === "not_configured"
        ? "Server is not configured with CURSOR_BRIDGE_TOKEN"
        : "Missing or invalid bearer token";
    ctx.logger.warn("unauthorized_request", { reason: auth.reason });
    sendUnauthorized(res, reason);
  };
}

/**
 * Create the Express app exposing `/health` and the MCP `/mcp` endpoint over
 * Streamable HTTP with session management (required for the ChatGPT connector's
 * initialize → tools/list → tools/call handshake).
 */
export function createHttpApp(ctx: ToolContext) {
  const app = express();
  app.use(express.json({ limit: "8mb" }));

  const transports = new Map<string, StreamableHTTPServerTransport>();

  app.get("/health", (_req: Request, res: Response) => {
    res.json({
      status: "ok",
      service: SERVER_NAME,
      version: SERVER_VERSION,
      cursor_sdk_configured: ctx.provider.configured,
      bridge_token_configured: ctx.config.bridgeToken !== undefined,
      database: ctx.store.healthcheck() ? "ok" : "error",
    });
  });

  const auth = bearerAuth(ctx);

  app.post("/mcp", auth, async (req: Request, res: Response) => {
    try {
      const sessionId = req.header("mcp-session-id");
      const existing = sessionId ? transports.get(sessionId) : undefined;

      let transport: StreamableHTTPServerTransport;
      if (existing) {
        transport = existing;
      } else if (!sessionId && isInitializeRequest(req.body)) {
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (sid) => {
            transports.set(sid, transport);
            ctx.logger.debug("mcp_session_initialized", { session_id: sid });
          },
        });
        transport.onclose = () => {
          if (transport.sessionId) transports.delete(transport.sessionId);
        };
        const server = buildMcpServer(ctx);
        await server.connect(transport);
      } else {
        res.status(400).json({
          jsonrpc: "2.0",
          error: { code: -32000, message: "Bad Request: No valid session ID provided" },
          id: null,
        });
        return;
      }

      await transport.handleRequest(req, res, req.body);
    } catch (err) {
      ctx.logger.error("mcp_request_failed", {
        message: err instanceof Error ? err.message : String(err),
      });
      if (!res.headersSent) {
        res.status(500).json({
          error: { code: ErrorCodes.INTERNAL_ERROR, message: "Internal error", details: {} },
        });
      }
    }
  });

  // GET (server-sent events) and DELETE (session teardown) require a live session.
  const handleSessionRequest = async (req: Request, res: Response): Promise<void> => {
    const sessionId = req.header("mcp-session-id");
    const transport = sessionId ? transports.get(sessionId) : undefined;
    if (!transport) {
      res.status(400).json({
        error: {
          code: ErrorCodes.VALIDATION_ERROR,
          message: "Invalid or missing mcp-session-id",
          details: {},
        },
      });
      return;
    }
    await transport.handleRequest(req, res);
  };

  app.get("/mcp", auth, handleSessionRequest);
  app.delete("/mcp", auth, handleSessionRequest);

  return app;
}

/** Start the HTTP transport (used for remote ChatGPT connections). */
export function startHttp(ctx: ToolContext): Promise<HttpServer> {
  const app = createHttpApp(ctx);
  return new Promise((resolve) => {
    const httpServer = app.listen(ctx.config.port, ctx.config.host, () => {
      ctx.logger.info("http_server_started", {
        ...redactedConfig(ctx.config),
        endpoint: `http://${ctx.config.host}:${ctx.config.port}/mcp`,
      });
      resolve(httpServer);
    });
  });
}

/** Start the stdio transport (used for local MCP clients). */
export async function startStdio(ctx: ToolContext): Promise<void> {
  const server = buildMcpServer(ctx);
  const transport = new StdioServerTransport();
  await server.connect(transport);
  ctx.logger.info("stdio_server_started", { service: SERVER_NAME });
}
