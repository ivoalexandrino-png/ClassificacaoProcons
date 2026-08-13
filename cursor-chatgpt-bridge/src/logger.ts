type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_ORDER: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

export interface Logger {
  debug(event: string, fields?: Record<string, unknown>): void;
  info(event: string, fields?: Record<string, unknown>): void;
  warn(event: string, fields?: Record<string, unknown>): void;
  error(event: string, fields?: Record<string, unknown>): void;
}

/**
 * Structured JSON-lines logger. Never pass secrets (tokens, API keys, .env
 * contents) in `fields` — callers are responsible for only logging identifiers
 * and metadata.
 */
export function createLogger(minLevel: LogLevel = "info"): Logger {
  const threshold = LEVEL_ORDER[minLevel];

  function log(level: LogLevel, event: string, fields?: Record<string, unknown>): void {
    if (LEVEL_ORDER[level] < threshold) return;
    const entry = { level, event, ts: new Date().toISOString(), ...fields };
    process.stderr.write(`${JSON.stringify(entry)}\n`);
  }

  return {
    debug: (event, fields) => log("debug", event, fields),
    info: (event, fields) => log("info", event, fields),
    warn: (event, fields) => log("warn", event, fields),
    error: (event, fields) => log("error", event, fields),
  };
}

export const nullLogger: Logger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
};
