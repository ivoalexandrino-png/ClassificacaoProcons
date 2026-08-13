import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express, { type Express } from "express";

import type { BridgeConfig } from "./config.js";
import type { Logger } from "./logger.js";
import { createMcpServer, type BridgeTools } from "./mcp/tools.js";
import { createAuthMiddleware } from "./security/auth.js";
import type { BridgeStore } from "./storage/store.js";

export interface CreateAppOptions {
  config: BridgeConfig;
  tools: BridgeTools;
  store: BridgeStore;
  logger: Logger;
  /** Must be a non-empty token; the bridge never runs HTTP without auth. */
  bridgeToken: string;
}

const METHOD_NOT_ALLOWED = {
  jsonrpc: "2.0",
  error: { code: -32000, message: "Method not allowed. Use POST for MCP requests." },
  id: null,
};

export function createApp(options: CreateAppOptions): Express {
  const { config, tools, store, logger, bridgeToken } = options;
  const app = express();
  app.use(express.json({ limit: "8mb" }));

  app.get("/health", (_req, res) => {
    let database = "ok";
    try {
      store.listProjects();
    } catch {
      database = "error";
    }
    res.json({
      status: database === "ok" ? "ok" : "degraded",
      service: "cursor-chatgpt-bridge",
      cursor_sdk_configured: Boolean(config.cursorApiKey),
      database,
    });
  });

  const auth = createAuthMiddleware(bridgeToken);

  // Stateless Streamable HTTP: one MCP server + transport per request.
  // This is the transport ChatGPT custom connectors use (URL ending in /mcp).
  app.post("/mcp", auth, async (req, res) => {
    const server = createMcpServer(tools);
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });
    res.on("close", () => {
      void transport.close();
      void server.close();
    });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (err) {
      logger.error("mcp_request_failed", {
        message: err instanceof Error ? err.message : String(err),
      });
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: { code: -32603, message: "Internal server error" },
          id: null,
        });
      }
    }
  });

  app.get("/mcp", auth, (_req, res) => {
    res.status(405).json(METHOD_NOT_ALLOWED);
  });
  app.delete("/mcp", auth, (_req, res) => {
    res.status(405).json(METHOD_NOT_ALLOWED);
  });

  return app;
}
