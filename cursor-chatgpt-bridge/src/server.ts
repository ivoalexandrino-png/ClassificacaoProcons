import { randomUUID } from "node:crypto";
import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import type { McpServer } from "@modelcontextprotocol/server";
import type { Express, Request, Response } from "express";
import type { BridgeConfig } from "./config.js";
import type { CursorAgentProvider } from "./cursor/types.js";
import { createBearerAuthMiddleware } from "./security/auth.js";
import type { Logger } from "./logger.js";
import type { BridgeStore } from "./storage/store.js";
import { createMcpServer, type ToolDeps } from "./mcp/tools.js";

interface SessionEntry {
  transport: NodeStreamableHTTPServerTransport;
  server: McpServer;
}

export interface BridgeApp {
  app: Express;
  close: () => Promise<void>;
}

export function createBridgeApp(options: {
  config: BridgeConfig;
  store: BridgeStore;
  provider: CursorAgentProvider;
  deps: ToolDeps;
  logger: Logger;
}): BridgeApp {
  const { config, store, provider, deps, logger } = options;
  const allowedHosts = Array.from(
    new Set([
      ...config.allowedHosts,
      "localhost",
      "127.0.0.1",
      "[::1]",
    ]),
  );
  const app = createMcpExpressApp({
    host: config.host,
    allowedHosts,
    allowedOrigins: allowedHosts,
    jsonLimit: "4mb",
  });

  app.get("/health", (_req, res) => {
    const db = store.healthCheck();
    res.status(db.ok ? 200 : 503).json({
      status: db.ok ? "ok" : "degraded",
      service: "cursor-chatgpt-bridge",
      cursor_sdk_configured: provider.isConfigured(),
      database: db.ok ? "ok" : "error",
      database_error: db.ok ? undefined : db.error,
    });
  });

  const auth = createBearerAuthMiddleware(config.bridgeToken);
  const sessions = new Map<string, SessionEntry>();

  const mcpHandler = async (req: Request, res: Response) => {
    try {
      const sessionIdHeader = req.header("mcp-session-id") ?? undefined;

      if (sessionIdHeader && sessions.has(sessionIdHeader)) {
        const existing = sessions.get(sessionIdHeader)!;
        await existing.transport.handleRequest(req, res, req.body);
        return;
      }

      if (req.method === "POST") {
        const server = createMcpServer(deps);
        const transport = new NodeStreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (sessionId) => {
            sessions.set(sessionId, { transport, server });
            logger.info("mcp_session_initialized", { session_id: sessionId });
          },
        });

        transport.onclose = () => {
          const sid = transport.sessionId;
          if (sid && sessions.has(sid)) {
            sessions.delete(sid);
            logger.info("mcp_session_closed", { session_id: sid });
          }
        };

        await server.connect(transport);
        await transport.handleRequest(req, res, req.body);
        return;
      }

      res.status(400).json({
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid or missing MCP session",
          details: {},
        },
      });
    } catch (error) {
      logger.error("mcp_request_failed", {
        message: error instanceof Error ? error.message : String(error),
      });
      if (!res.headersSent) {
        res.status(500).json({
          error: {
            code: "INTERNAL_ERROR",
            message: "MCP request failed",
            details: {},
          },
        });
      }
    }
  };

  app.post("/mcp", auth, mcpHandler);
  app.get("/mcp", auth, mcpHandler);
  app.delete("/mcp", auth, mcpHandler);

  return {
    app,
    close: async () => {
      for (const [sessionId, entry] of sessions) {
        try {
          await entry.transport.close();
          await entry.server.close();
        } catch {
          // ignore close errors during shutdown
        }
        sessions.delete(sessionId);
      }
    },
  };
}

export async function startHttpServer(options: {
  config: BridgeConfig;
  store: BridgeStore;
  provider: CursorAgentProvider;
  deps: ToolDeps;
  logger: Logger;
}): Promise<{ close: () => Promise<void> }> {
  const bridge = createBridgeApp(options);
  const server = bridge.app.listen(options.config.port, options.config.host, () => {
    options.logger.info("bridge_listening", {
      host: options.config.host,
      port: options.config.port,
      mcp_endpoint: "/mcp",
      health_endpoint: "/health",
    });
  });

  return {
    close: async () => {
      await bridge.close();
      await new Promise<void>((resolve, reject) => {
        server.close((err) => (err ? reject(err) : resolve()));
      });
    },
  };
}

export async function startStdioServer(options: {
  deps: ToolDeps;
  logger: Logger;
}): Promise<void> {
  const server = createMcpServer(options.deps);
  const transport = new StdioServerTransport();
  await server.connect(transport);
  options.logger.info("bridge_stdio_started", {
    transport: "stdio",
  });
}
