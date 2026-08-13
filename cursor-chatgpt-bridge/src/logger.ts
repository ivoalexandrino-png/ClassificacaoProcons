/**
 * Minimal structured JSON logger with secret redaction.
 *
 * Every entry is a single JSON line: { level, event, ...fields, ts }.
 * Values are scrubbed so that tokens, API keys and other secrets never reach
 * the log stream even if accidentally passed as a field.
 */

export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

/** Field names whose values must never be logged. */
const SENSITIVE_KEYS = new Set(
  [
    "token",
    "authorization",
    "bridge_token",
    "bridgetoken",
    "cursor_api_key",
    "cursorapikey",
    "apikey",
    "api_key",
    "secret",
    "password",
    "credential",
    "credentials",
    "env",
    "envvars",
    "env_vars",
  ].map((k) => k.toLowerCase()),
);

export interface Logger {
  debug(event: string, fields?: Record<string, unknown>): void;
  info(event: string, fields?: Record<string, unknown>): void;
  warn(event: string, fields?: Record<string, unknown>): void;
  error(event: string, fields?: Record<string, unknown>): void;
}

export function createLogger(level: LogLevel = "info"): Logger {
  const threshold = LEVEL_ORDER[level];

  function emit(entryLevel: LogLevel, event: string, fields?: Record<string, unknown>): void {
    if (LEVEL_ORDER[entryLevel] < threshold) return;
    const line = {
      level: entryLevel,
      event,
      ...redact(fields ?? {}),
      ts: new Date().toISOString(),
    };
    const sink = entryLevel === "error" || entryLevel === "warn" ? process.stderr : process.stdout;
    sink.write(`${JSON.stringify(line)}\n`);
  }

  return {
    debug: (event, fields) => emit("debug", event, fields),
    info: (event, fields) => emit("info", event, fields),
    warn: (event, fields) => emit("warn", event, fields),
    error: (event, fields) => emit("error", event, fields),
  };
}

function redact(input: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (SENSITIVE_KEYS.has(key.toLowerCase())) {
      out[key] = "[REDACTED]";
      continue;
    }
    out[key] = redactValue(value);
  }
  return out;
}

function redactValue(value: unknown): unknown {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map(redactValue);
  return redact(value as Record<string, unknown>);
}
