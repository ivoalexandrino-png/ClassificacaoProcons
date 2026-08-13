import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { loadConfig } from "./config.js";
import { CursorSdkProvider } from "./cursor/client.js";
import { createLogger } from "./logger.js";
import { BridgeTools, createMcpServer } from "./mcp/tools.js";
import { createApp } from "./server.js";
import { BridgeStore } from "./storage/store.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = createLogger(config.logLevel);
  const store = new BridgeStore(config.databasePath);
  const provider = new CursorSdkProvider(config.cursorApiKey);
  const tools = new BridgeTools({ store, provider, config, logger });

  const stdioMode = process.argv.includes("--stdio");

  if (stdioMode) {
    // STDIO transport for local MCP clients (Claude Desktop, Cursor, etc.).
    // Auth is the process boundary; the bearer token applies to HTTP only.
    const server = createMcpServer(tools);
    await server.connect(new StdioServerTransport());
    logger.info("bridge_started", { transport: "stdio" });
    return;
  }

  if (!config.bridgeToken) {
    logger.error("missing_bridge_token", {
      hint: "Set CURSOR_BRIDGE_TOKEN — the MCP server never runs over HTTP without authentication",
    });
    process.exit(1);
  }
  if (!config.cursorApiKey) {
    logger.warn("missing_cursor_api_key", {
      hint: "Set CURSOR_API_KEY to enable Cursor agent operations; only local data will be served until then",
    });
  }

  const app = createApp({
    config,
    tools,
    store,
    logger,
    bridgeToken: config.bridgeToken,
  });

  app.listen(config.port, () => {
    logger.info("bridge_started", {
      transport: "http",
      port: config.port,
      endpoint: "/mcp",
      health: "/health",
      cursor_sdk_configured: Boolean(config.cursorApiKey),
    });
  });
}

main().catch((err: unknown) => {
  process.stderr.write(
    `${JSON.stringify({
      level: "error",
      event: "bridge_startup_failed",
      message: err instanceof Error ? err.message : String(err),
    })}\n`,
  );
  process.exit(1);
});
