#!/usr/bin/env node
import { loadConfig } from "./config.js";
import { startServer } from "./server.js";

async function main(): Promise<void> {
  const config = loadConfig();
  await startServer(config);
}

main().catch((error) => {
  console.error(
    JSON.stringify({
      level: "error",
      event: "startup_failed",
      message: error instanceof Error ? error.message : String(error),
    }),
  );
  process.exit(1);
});
