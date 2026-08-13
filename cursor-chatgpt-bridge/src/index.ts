import dotenv from "dotenv";
import { serveStdio } from "@modelcontextprotocol/server/stdio";
import { loadConfig } from "./config.js";
import { CursorSdkProvider } from "./cursor/client.js";
import { Logger } from "./logger.js";
import { BridgeTools } from "./mcp/tools.js";
import { createBridgeMcpServer, createHttpServer } from "./server.js";
import { BridgeStore } from "./storage/store.js";

dotenv.config({ quiet: true });

const config = loadConfig();
const logger = new Logger(config.logLevel);
const store = new BridgeStore(config.databasePath);
const provider = new CursorSdkProvider(config.cursorApiKey, config.cursorModel);
const tools = new BridgeTools(
  store,
  provider,
  config.runTimeoutMs,
  config.maxDiffChars,
  logger,
);

if (process.argv.includes("--stdio")) {
  const handle = serveStdio(() => createBridgeMcpServer(tools), {
    onerror: (error) => logger.error("mcp_stdio_error", { message: error.message }),
  });
  const shutdown = async () => {
    await handle.close();
    store.close();
  };
  process.once("SIGINT", () => {
    void shutdown();
  });
  process.once("SIGTERM", () => {
    void shutdown();
  });
  logger.info("bridge_started", { transport: "stdio" });
} else {
  const server = createHttpServer({
    host: config.host,
    port: config.port,
    bridgeToken: config.bridgeToken,
    store,
    provider,
    tools,
    logger,
  });
  server.listen(config.port, config.host, () => {
    logger.info("bridge_started", {
      transport: "streamable_http",
      host: config.host,
      port: config.port,
      endpoint: "/mcp",
    });
  });
  const shutdown = () => {
    server.close(() => {
      store.close();
    });
  };
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
}
