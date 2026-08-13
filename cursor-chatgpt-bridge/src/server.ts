import { randomUUID } from "node:crypto";
import express from "express";
import type { Request, Response } from "express";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import pino from "pino";
import type { Config } from "./config.js";
import { BridgeService } from "./cursor/agents.js";
import { bearerAuth } from "./security/auth.js";
import { BridgeStore } from "./storage/store.js";
import { createMcpServer } from "./mcp/tools.js";
import type { CursorAgentProvider } from "./cursor/types.js";

export function createHttpServer(config: Config, provider: CursorAgentProvider) {
  const app = express();
  const logger = pino({ level: config.LOG_LEVEL, base: undefined });
  const store = new BridgeStore(config.DATABASE_PATH);
  const service = new BridgeService(store, provider, config.CURSOR_RUN_TIMEOUT_MS);
  const transports = new Map<string, StreamableHTTPServerTransport>();

  app.use(express.json({ limit: "1mb" }));
  app.get("/health", (_request, response) => {
    response.json({ status: "ok", service: "cursor-chatgpt-bridge", cursor_sdk_configured: Boolean(process.env.CURSOR_API_KEY), database: "ok" });
  });
  app.use("/mcp", bearerAuth(config.CURSOR_BRIDGE_TOKEN));

  const handleMcp = async (request: Request, response: Response): Promise<void> => {
    const sessionId = request.header("mcp-session-id");
    let transport = sessionId ? transports.get(sessionId) : undefined;
    if (!transport) {
      if (sessionId) {
        response.status(404).json({ error: { code: "INVALID_SESSION", message: "MCP session not found", details: {} } });
        return;
      }
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: randomUUID,
        onsessioninitialized: (id) => transports.set(id, transport!)
      });
      transport.onclose = () => {
        if (transport?.sessionId) transports.delete(transport.sessionId);
      };
      await createMcpServer(service).connect(transport);
    }
    await transport.handleRequest(request, response, request.body);
  };

  app.post("/mcp", (request, response, next) => { void handleMcp(request, response).catch(next); });
  app.get("/mcp", (request, response, next) => { void handleMcp(request, response).catch(next); });
  app.delete("/mcp", (request, response, next) => { void handleMcp(request, response).catch(next); });
  app.use((error: unknown, _request: Request, response: Response, _next: express.NextFunction) => {
    logger.error({ event: "http_request_failed", message: error instanceof Error ? error.message : "Unknown error" });
    response.status(500).json({ error: { code: "INTERNAL_ERROR", message: "Internal server error", details: {} } });
  });

  return { app, store, service, logger };
}
