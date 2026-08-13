#!/usr/bin/env node
import { loadConfig } from "./config.js";
import { AgentService } from "./cursor/agents.js";
import { SdkCursorAgentProvider } from "./cursor/client.js";
import { RunService } from "./cursor/runs.js";
import { createLogger } from "./logger.js";
import { startHttpServer, startStdioServer } from "./server.js";
import { BridgeStore } from "./storage/store.js";

async function main(): Promise<void> {
  const stdioMode = process.argv.includes("--stdio");
  const config = loadConfig({ requireToken: !stdioMode });
  const logger = createLogger(config.logLevel);
  const store = new BridgeStore(config.databasePath);
  const provider = new SdkCursorAgentProvider(
    config.cursorApiKey,
    config.defaultModel,
    logger,
  );
  const agents = new AgentService(
    store,
    provider,
    logger,
    config.runTimeoutMs,
  );
  const runs = new RunService(store, provider, logger);
  const deps = { store, agents, runs, logger };

  const shutdown = async () => {
    logger.info("bridge_shutdown");
    store.close();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown());
  process.on("SIGTERM", () => void shutdown());

  if (stdioMode) {
    if (!config.bridgeToken) {
      logger.warn("stdio_mode_without_bridge_token", {
        note: "HTTP auth token not required for stdio",
      });
    }
    await startStdioServer({ deps, logger });
    return;
  }

  if (!config.bridgeToken) {
    throw new Error("CURSOR_BRIDGE_TOKEN is required for HTTP/MCP mode");
  }

  await startHttpServer({ config, store, provider, deps, logger });
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(
    JSON.stringify({
      level: "error",
      event: "bridge_fatal",
      message,
      ts: new Date().toISOString(),
    }),
  );
  process.exit(1);
});
