type LogLevel = "debug" | "info" | "warn" | "error";

const priorities: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

export class Logger {
  constructor(private readonly minimumLevel: LogLevel = "info") {}

  log(level: LogLevel, event: string, fields: Record<string, unknown> = {}): void {
    if (priorities[level] < priorities[this.minimumLevel]) return;
    const record = {
      level,
      event,
      timestamp: new Date().toISOString(),
      ...fields,
    };
    process.stderr.write(`${JSON.stringify(record)}\n`);
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
