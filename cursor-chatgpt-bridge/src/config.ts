import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

export interface AppConfig {
  port: number;
  mcpPath: string;
  bridgeToken: string;
  cursorApiKey: string | undefined;
  databasePath: string;
  runTimeoutMs: number;
  logLevel: "debug" | "info" | "warn" | "error";
  transport: "http" | "stdio";
  defaultModel: string;
}

function parseLogLevel(value: string | undefined): AppConfig["logLevel"] {
  const level = value?.toLowerCase();
  if (level === "debug" || level === "info" || level === "warn" || level === "error") {
    return level;
  }
  return "info";
}

export function loadConfig(env: Record<string, string | undefined> = process.env): AppConfig {
  const databasePath = resolve(env.DATABASE_PATH ?? "./data/bridge.db");
  const dbDir = dirname(databasePath);
  if (!existsSync(dbDir)) {
    mkdirSync(dbDir, { recursive: true });
  }

  return {
    port: Number.parseInt(env.PORT ?? "3000", 10),
    mcpPath: env.MCP_PATH ?? "/mcp",
    bridgeToken: env.CURSOR_BRIDGE_TOKEN ?? "",
    cursorApiKey: env.CURSOR_API_KEY,
    databasePath,
    runTimeoutMs: Number.parseInt(env.CURSOR_RUN_TIMEOUT_MS ?? "900000", 10),
    logLevel: parseLogLevel(env.LOG_LEVEL),
    transport: env.TRANSPORT === "stdio" ? "stdio" : "http",
    defaultModel: env.CURSOR_DEFAULT_MODEL ?? "composer-2.5",
  };
}

export function isCursorSdkConfigured(config: AppConfig): boolean {
  return Boolean(config.cursorApiKey?.trim());
}
