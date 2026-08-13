import "dotenv/config";

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface BridgeConfig {
  port: number;
  bridgeToken: string | undefined;
  cursorApiKey: string | undefined;
  databasePath: string;
  runTimeoutMs: number;
  logLevel: LogLevel;
}

function parseIntEnv(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function parseLogLevel(value: string | undefined): LogLevel {
  const allowed: LogLevel[] = ["debug", "info", "warn", "error"];
  return allowed.includes(value as LogLevel) ? (value as LogLevel) : "info";
}

/**
 * Loads configuration from the environment. Re-read on demand (instead of
 * cached at import time) so tests can mutate `process.env` per case.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): BridgeConfig {
  return {
    port: parseIntEnv(env.PORT, 3000),
    bridgeToken: env.CURSOR_BRIDGE_TOKEN?.trim() || undefined,
    cursorApiKey: env.CURSOR_API_KEY?.trim() || undefined,
    databasePath: env.DATABASE_PATH?.trim() || "./data/bridge.db",
    runTimeoutMs: parseIntEnv(env.CURSOR_RUN_TIMEOUT_MS, 900_000),
    logLevel: parseLogLevel(env.LOG_LEVEL),
  };
}
