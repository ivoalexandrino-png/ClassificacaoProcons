export interface BridgeConfig {
  port: number;
  bridgeToken: string | undefined;
  cursorApiKey: string | undefined;
  databasePath: string;
  runTimeoutMs: number;
  logLevel: "debug" | "info" | "warn" | "error";
  maxDiffChars: number;
}

const DEFAULT_RUN_TIMEOUT_MS = 900_000; // 15 minutes
const DEFAULT_MAX_DIFF_CHARS = 30_000;

function parsePositiveInt(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): BridgeConfig {
  const logLevel = env.LOG_LEVEL;
  return {
    port: parsePositiveInt(env.PORT, 3000),
    bridgeToken: env.CURSOR_BRIDGE_TOKEN || undefined,
    cursorApiKey: env.CURSOR_API_KEY || undefined,
    databasePath: env.DATABASE_PATH || "./data/bridge.db",
    runTimeoutMs: parsePositiveInt(env.CURSOR_RUN_TIMEOUT_MS, DEFAULT_RUN_TIMEOUT_MS),
    logLevel:
      logLevel === "debug" || logLevel === "warn" || logLevel === "error" ? logLevel : "info",
    maxDiffChars: parsePositiveInt(env.MAX_DIFF_CHARS, DEFAULT_MAX_DIFF_CHARS),
  };
}
