import { resolve } from "node:path";
import { z } from "zod";

const environmentSchema = z.object({
  PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  CURSOR_BRIDGE_TOKEN: z.string().min(16),
  DATABASE_PATH: z.string().default("./data/bridge.db"),
  CURSOR_RUN_TIMEOUT_MS: z.coerce.number().int().min(1_000).default(900_000),
  LOG_LEVEL: z.enum(["fatal", "error", "warn", "info", "debug", "trace"]).default("info")
});

export type Config = ReturnType<typeof loadConfig>;

export function loadConfig(environment = process.env) {
  const parsed = environmentSchema.safeParse(environment);
  if (!parsed.success) {
    throw new Error(`Invalid configuration: ${parsed.error.issues.map((issue) => issue.path.join(".")).join(", ")}`);
  }
  return { ...parsed.data, DATABASE_PATH: resolve(parsed.data.DATABASE_PATH) };
}
