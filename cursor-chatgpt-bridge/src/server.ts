import { randomUUID } from "node:crypto";
import express, { type Express } from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";
import type { BridgeConfig } from "./config.js";
import type { CursorAgentProvider } from "./cursor/types.js";
import type { Logger } from "./logger.js";
import { createAuthMiddleware } from "./security/auth.js";
import { errorBody } from "./mcp/errors.js";
import { registerCursorTools, type BridgeDependencies } from "./mcp/tools.js";
import type { BridgeStore } from "./storage/store.js";

const MCP_SERVER_NAME = "cursor-chatgpt-bridge";
const MCP_SERVER_VERSION = "0.1.0";

export interface BuildServerOptions {
  config: BridgeConfig;
  store: BridgeStore;
  provider: CursorAgentProvider;
  deps: BridgeDependencies;
  logger: Logger;
}

export function buildMcpServer(deps: BridgeDependencies): McpServer {
  const server = new McpServer({ name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION });
  registerCursorTools(server, deps);
  return server;
}

/**
 * Builds the Express app exposing:
 *   GET  /health         - unauthenticated liveness/readiness probe
 *   POST /mcp, GET /mcp, DELETE /mcp - authenticated Streamable HTTP MCP transport
 *
 * Session-per-connection: each new MCP `initialize` request gets its own
 * `McpServer` + `StreamableHTTPServerTransport` pair, tracked by the
 * `Mcp-Session-Id` header, per the MCP Streamable HTTP transport spec.
 */
export function buildServer(options: BuildServerOptions): Express {
  const { config, store, provider, deps, logger } = options;
  const app = express();
  app.disable("x-powered-by");
  app.use(express.json({ limit: "8mb" }));

  app.get("/health", (_req, res) => {
    let databaseStatus: "ok" | "error" = "ok";
    try {
      store.listProjects();
    } catch {
      databaseStatus = "error";
    }
    res.json({
      status: "ok",
      service: MCP_SERVER_NAME,
      cursor_sdk_configured: provider.isConfigured(),
      database: databaseStatus,
    });
  });

  if (!config.bridgeToken) {
    logger.error({
      event: "startup_missing_bridge_token",
      message: "CURSOR_BRIDGE_TOKEN is not set; refusing to expose /mcp without authentication.",
    });
    app.all("/mcp", (_req, res) => {
      res
        .status(503)
        .json(
          errorBody(
            "INTERNAL_ERROR",
            "Server misconfigured: CURSOR_BRIDGE_TOKEN is not set. Refusing to serve /mcp without authentication.",
          ),
        );
    });
    return app;
  }

  const authMiddleware = createAuthMiddleware(config.bridgeToken);

  const sessions = new Map<string, { transport: StreamableHTTPServerTransport; server: McpServer }>();

  async function handleMcpRequest(
    req: express.Request,
    res: express.Response,
  ): Promise<void> {
    const sessionIdHeader = req.header("mcp-session-id");
    const existing = sessionIdHeader ? sessions.get(sessionIdHeader) : undefined;

    if (existing) {
      await existing.transport.handleRequest(req, res, req.body);
      return;
    }

    if (req.method === "POST" && isInitializeRequest(req.body)) {
      const server = buildMcpServer(deps);
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        enableJsonResponse: true,
        onsessioninitialized: (sessionId) => {
          sessions.set(sessionId, { transport, server });
          logger.debug({ event: "mcp_session_initialized", session_id: sessionId });
        },
        onsessionclosed: (sessionId) => {
          sessions.delete(sessionId);
          logger.debug({ event: "mcp_session_closed", session_id: sessionId });
        },
      });
      transport.onclose = () => {
        if (transport.sessionId) sessions.delete(transport.sessionId);
      };
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
      return;
    }

    res
      .status(400)
      .json(
        errorBody(
          "VALIDATION_ERROR",
          "No active MCP session. Send an 'initialize' request first, or include a valid Mcp-Session-Id header.",
        ),
      );
  }

  app.post("/mcp", authMiddleware, (req, res) => {
    handleMcpRequest(req, res).catch((error: unknown) => {
      logger.error({
        event: "mcp_transport_error",
        message: error instanceof Error ? error.message : String(error),
      });
      if (!res.headersSent) {
        res.status(500).json(errorBody("INTERNAL_ERROR", "Unexpected MCP transport error."));
      }
    });
  });

  app.get("/mcp", authMiddleware, (req, res) => {
    handleMcpRequest(req, res).catch((error: unknown) => {
      logger.error({
        event: "mcp_transport_error",
        message: error instanceof Error ? error.message : String(error),
      });
      if (!res.headersSent) {
        res.status(500).json(errorBody("INTERNAL_ERROR", "Unexpected MCP transport error."));
      }
    });
  });

  app.delete("/mcp", authMiddleware, (req, res) => {
    handleMcpRequest(req, res).catch((error: unknown) => {
      logger.error({
        event: "mcp_transport_error",
        message: error instanceof Error ? error.message : String(error),
      });
      if (!res.headersSent) {
        res.status(500).json(errorBody("INTERNAL_ERROR", "Unexpected MCP transport error."));
      }
    });
  });

  return app;
}
