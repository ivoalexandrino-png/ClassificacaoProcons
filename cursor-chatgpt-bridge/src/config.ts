import { z } from "zod";

/**
 * Environment-driven configuration for the bridge.
 *
 * Only variables that map to real behavior are read. Secrets are never logged;
 * see {@link redactedConfig} for the safe-to-log projection.
 */
const EnvSchema = z.object({
  PORT: z.coerce.number().int().positive().default(3000),
  HOST: z.string().default("0.0.0.0"),

  /** Bearer token required on every MCP/HTTP request. */
  CURSOR_BRIDGE_TOKEN: z.string().optional(),

  /** Cursor API key forwarded to the official @cursor/sdk. */
  CURSOR_API_KEY: z.string().optional(),

  /** Path to the SQLite database file used for bridge persistence. */
  DATABASE_PATH: z.string().default("./data/bridge.db"),

  /** Directory used by the Cursor SDK local agent store (JSONL). */
  CURSOR_LOCAL_STORE_PATH: z.string().default("./data/cursor-local-store"),

  /** Default model id used when starting agents. */
  CURSOR_MODEL: z.string().default("auto"),

  /** Max wall-clock time to wait for a run to complete before recording a timeout. */
  CURSOR_RUN_TIMEOUT_MS: z.coerce.number().int().positive().default(900_000),

  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),

  /** Transport to start: "http" (remote, ChatGPT) or "stdio" (local clients). */
  MCP_TRANSPORT: z.enum(["http", "stdio"]).default("http"),
});

export type Config = Readonly<{
  port: number;
  host: string;
  bridgeToken: string | undefined;
  cursorApiKey: string | undefined;
  databasePath: string;
  cursorLocalStorePath: string;
  cursorModel: string;
  runTimeoutMs: number;
  logLevel: "debug" | "info" | "warn" | "error";
  transport: "http" | "stdio";
}>;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = EnvSchema.parse(env);
  return {
    port: parsed.PORT,
    host: parsed.HOST,
    bridgeToken: emptyToUndefined(parsed.CURSOR_BRIDGE_TOKEN),
    cursorApiKey: emptyToUndefined(parsed.CURSOR_API_KEY),
    databasePath: parsed.DATABASE_PATH,
    cursorLocalStorePath: parsed.CURSOR_LOCAL_STORE_PATH,
    cursorModel: parsed.CURSOR_MODEL,
    runTimeoutMs: parsed.CURSOR_RUN_TIMEOUT_MS,
    logLevel: parsed.LOG_LEVEL,
    transport: parsed.MCP_TRANSPORT,
  };
}

function emptyToUndefined(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const trimmed = value.trim();
  return trimmed.length === 0 ? undefined : trimmed;
}

/** A projection of config that is always safe to log (no secrets). */
export function redactedConfig(config: Config): Record<string, unknown> {
  return {
    port: config.port,
    host: config.host,
    databasePath: config.databasePath,
    cursorLocalStorePath: config.cursorLocalStorePath,
    cursorModel: config.cursorModel,
    runTimeoutMs: config.runTimeoutMs,
    logLevel: config.logLevel,
    transport: config.transport,
    bridgeTokenConfigured: config.bridgeToken !== undefined,
    cursorApiKeyConfigured: config.cursorApiKey !== undefined,
  };
}
