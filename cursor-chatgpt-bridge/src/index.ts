import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { loadConfig } from "./config.js";
import { AgentService } from "./cursor/agents.js";
import { CursorSdkAgentProvider } from "./cursor/client.js";
import { RunService } from "./cursor/runs.js";
import { createLogger } from "./logger.js";
import { buildMcpServer, buildServer } from "./server.js";
import { BridgeStore } from "./storage/store.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = createLogger(config.logLevel);
  const useStdio = process.argv.includes("--stdio");

  const store = new BridgeStore(config.databasePath);
  const provider = new CursorSdkAgentProvider({ apiKey: config.cursorApiKey, logger });
  const agents = new AgentService(store, provider);
  const runs = new RunService(store, provider, agents, logger, config.runTimeoutMs);
  const deps = { agents, runs, logger };

  if (!provider.isConfigured()) {
    logger.warn({
      event: "startup_missing_cursor_api_key",
      message: "CURSOR_API_KEY is not set. Tools that call Cursor will return CURSOR_API_ERROR until it is configured.",
    });
  }

  if (useStdio) {
    logger.info({ event: "startup", transport: "stdio" });
    const server = buildMcpServer(deps);
    const transport = new StdioServerTransport();
    await server.connect(transport);
    return;
  }

  if (!config.bridgeToken) {
    logger.warn({
      event: "startup_missing_bridge_token",
      message: "CURSOR_BRIDGE_TOKEN is not set. /mcp will refuse all requests until it is configured.",
    });
  }

  const app = buildServer({ config, store, provider, deps, logger });
  app.listen(config.port, () => {
    logger.info({ event: "startup", transport: "http", port: config.port });
  });
}

main().catch((error: unknown) => {
  // eslint-disable-next-line no-console -- last-resort fatal startup failure, before the logger can help
  console.error("Fatal startup error:", error);
  process.exit(1);
});
