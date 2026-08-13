import type { LogLevel } from "./config.js";

const LEVEL_WEIGHT: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

/** Keys that must never reach a log line, even if a caller accidentally includes them. */
const SENSITIVE_KEYS = new Set([
  "token",
  "bridgetoken",
  "cursor_bridge_token",
  "apikey",
  "api_key",
  "cursorapikey",
  "cursor_api_key",
  "authorization",
  "secret",
  "password",
]);

function redact(value: unknown, depth = 0): unknown {
  if (depth > 4 || value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map((item) => redact(item, depth + 1));
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      out[key] = SENSITIVE_KEYS.has(key.toLowerCase()) ? "[REDACTED]" : redact(val, depth + 1);
    }
    return out;
  }
  return value;
}

export interface LogFields {
  event: string;
  [key: string]: unknown;
}

export class Logger {
  constructor(private readonly minLevel: LogLevel) {}

  private log(level: LogLevel, fields: LogFields): void {
    if (LEVEL_WEIGHT[level] < LEVEL_WEIGHT[this.minLevel]) return;
    const line = {
      level,
      time: new Date().toISOString(),
      ...(redact(fields) as Record<string, unknown>),
    };
    // Always stderr, never stdout: in --stdio mode, stdout is reserved
    // exclusively for the JSON-RPC transport (MCP stdio transport spec).
    // Mixing log lines into it would corrupt the protocol stream.
    process.stderr.write(`${JSON.stringify(line)}\n`);
  }

  debug(fields: LogFields): void {
    this.log("debug", fields);
  }

  info(fields: LogFields): void {
    this.log("info", fields);
  }

  warn(fields: LogFields): void {
    this.log("warn", fields);
  }

  error(fields: LogFields): void {
    this.log("error", fields);
  }
}

export function createLogger(level: LogLevel = "info"): Logger {
  return new Logger(level);
}
