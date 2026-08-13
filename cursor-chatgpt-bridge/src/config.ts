import path from "node:path";
import { z } from "zod";

const environmentSchema = z.object({
  PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  HOST: z.string().default("0.0.0.0"),
  CURSOR_BRIDGE_TOKEN: z.string().min(32, "CURSOR_BRIDGE_TOKEN must contain at least 32 characters"),
  CURSOR_API_KEY: z.string().min(1).optional(),
  CURSOR_MODEL: z.string().min(1).default("composer-2.5"),
  DATABASE_PATH: z.string().min(1).default("./data/bridge.db"),
  CURSOR_RUN_TIMEOUT_MS: z.coerce.number().int().positive().default(900_000),
  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),
  MAX_DIFF_CHARS: z.coerce.number().int().min(1_000).max(200_000).default(30_000),
});

export type BridgeConfig = {
  port: number;
  host: string;
  bridgeToken: string;
  cursorApiKey?: string;
  cursorModel: string;
  databasePath: string;
  runTimeoutMs: number;
  logLevel: "debug" | "info" | "warn" | "error";
  maxDiffChars: number;
};

export function loadConfig(environment: NodeJS.ProcessEnv = process.env): BridgeConfig {
  const parsed = environmentSchema.parse(environment);
  return {
    port: parsed.PORT,
    host: parsed.HOST,
    bridgeToken: parsed.CURSOR_BRIDGE_TOKEN,
    cursorApiKey: parsed.CURSOR_API_KEY,
    cursorModel: parsed.CURSOR_MODEL,
    databasePath: path.resolve(parsed.DATABASE_PATH),
    runTimeoutMs: parsed.CURSOR_RUN_TIMEOUT_MS,
    logLevel: parsed.LOG_LEVEL,
    maxDiffChars: parsed.MAX_DIFF_CHARS,
  };
}
