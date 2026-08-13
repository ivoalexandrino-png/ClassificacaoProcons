#!/usr/bin/env node
import { loadConfig, redactedConfig } from "./config.js";
import { AgentLockManager } from "./cursor/agents.js";
import { CursorSdkProvider } from "./cursor/client.js";
import { createLogger } from "./logger.js";
import type { ToolContext } from "./mcp/tools.js";
import { startHttp, startStdio } from "./server.js";
import { SqliteStore } from "./storage/store.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = createLogger(config.logLevel);

  const store = new SqliteStore(config.databasePath);
  const provider = new CursorSdkProvider({
    apiKey: config.cursorApiKey,
    model: config.cursorModel,
    localStorePath: config.cursorLocalStorePath,
    logger,
  });
  const locks = new AgentLockManager();

  const ctx: ToolContext = { store, provider, locks, config, logger };

  logger.info("bridge_starting", redactedConfig(config));

  if (config.transport === "stdio") {
    await startStdio(ctx);
  } else {
    const httpServer = await startHttp(ctx);
    const shutdown = (signal: string) => {
      logger.info("bridge_shutting_down", { signal });
      httpServer.close(() => {
        store.close();
        process.exit(0);
      });
    };
    process.on("SIGINT", () => shutdown("SIGINT"));
    process.on("SIGTERM", () => shutdown("SIGTERM"));
  }
}

main().catch((err: unknown) => {
  process.stderr.write(
    `${JSON.stringify({
      level: "error",
      event: "bridge_fatal",
      message: err instanceof Error ? err.message : String(err),
      ts: new Date().toISOString(),
    })}\n`,
  );
  process.exit(1);
});
