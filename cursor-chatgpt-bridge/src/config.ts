import { config as loadEnv } from "dotenv";
import path from "node:path";

loadEnv();

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface BridgeConfig {
  port: number;
  host: string;
  bridgeToken: string;
  cursorApiKey: string | undefined;
  databasePath: string;
  runTimeoutMs: number;
  defaultModel: string;
  allowedHosts: string[];
  logLevel: LogLevel;
}

function required(name: string, optional = false): string | undefined {
  const value = process.env[name]?.trim();
  if (!value && !optional) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value || undefined;
}

function parseLogLevel(value: string | undefined): LogLevel {
  const normalized = (value ?? "info").toLowerCase();
  if (
    normalized === "debug" ||
    normalized === "info" ||
    normalized === "warn" ||
    normalized === "error"
  ) {
    return normalized;
  }
  return "info";
}

export function loadConfig(options?: {
  requireToken?: boolean;
}): BridgeConfig {
  const requireToken = options?.requireToken ?? true;
  const bridgeToken = required("CURSOR_BRIDGE_TOKEN", !requireToken);
  if (requireToken && !bridgeToken) {
    throw new Error("Missing required environment variable: CURSOR_BRIDGE_TOKEN");
  }

  const databasePath =
    process.env.DATABASE_PATH?.trim() ||
    path.resolve(process.cwd(), "data", "bridge.db");

  const runTimeoutMs = Number(process.env.CURSOR_RUN_TIMEOUT_MS ?? "900000");
  if (!Number.isFinite(runTimeoutMs) || runTimeoutMs < 1_000) {
    throw new Error("CURSOR_RUN_TIMEOUT_MS must be a number >= 1000");
  }

  const port = Number(process.env.PORT ?? "3000");
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("PORT must be an integer between 1 and 65535");
  }

  const allowedHosts = (process.env.ALLOWED_HOSTS ?? "localhost,127.0.0.1")
    .split(",")
    .map((h) => h.trim())
    .filter(Boolean);

  return {
    port,
    host: process.env.HOST?.trim() || "0.0.0.0",
    bridgeToken: bridgeToken ?? "",
    cursorApiKey: process.env.CURSOR_API_KEY?.trim() || undefined,
    databasePath: path.resolve(databasePath),
    runTimeoutMs,
    defaultModel: process.env.CURSOR_DEFAULT_MODEL?.trim() || "composer-2.5",
    allowedHosts,
    logLevel: parseLogLevel(process.env.LOG_LEVEL),
  };
}
