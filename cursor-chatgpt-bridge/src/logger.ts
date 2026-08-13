import type { AppConfig } from "./config.js";

export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const SECRET_PATTERNS = [
  /api[_-]?key/i,
  /token/i,
  /password/i,
  /secret/i,
  /authorization/i,
  /bearer/i,
];

function sanitizeValue(key: string, value: unknown): unknown {
  if (SECRET_PATTERNS.some((pattern) => pattern.test(key))) {
    return "[REDACTED]";
  }
  if (typeof value === "string" && value.length > 500) {
    return `${value.slice(0, 500)}…`;
  }
  return value;
}

function sanitizeRecord(record: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(record)) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      out[key] = sanitizeRecord(value as Record<string, unknown>);
    } else {
      out[key] = sanitizeValue(key, value);
    }
  }
  return out;
}

export class Logger {
  constructor(private readonly minLevel: LogLevel = "info") {}

  private shouldLog(level: LogLevel): boolean {
    return LEVEL_ORDER[level] >= LEVEL_ORDER[this.minLevel];
  }

  log(level: LogLevel, event: string, fields: Record<string, unknown> = {}): void {
    if (!this.shouldLog(level)) {
      return;
    }
    const payload = {
      level,
      event,
      timestamp: new Date().toISOString(),
      ...sanitizeRecord(fields),
    };
    const line = JSON.stringify(payload);
    if (level === "error") {
      console.error(line);
    } else if (level === "warn") {
      console.warn(line);
    } else {
      console.log(line);
    }
  }

  debug(event: string, fields?: Record<string, unknown>): void {
    this.log("debug", event, fields);
  }

  info(event: string, fields?: Record<string, unknown>): void {
    this.log("info", event, fields);
  }

  warn(event: string, fields?: Record<string, unknown>): void {
    this.log("warn", event, fields);
  }

  error(event: string, fields?: Record<string, unknown>): void {
    this.log("error", event, fields);
  }
}

export function createLogger(config: AppConfig): Logger {
  return new Logger(config.logLevel);
}
