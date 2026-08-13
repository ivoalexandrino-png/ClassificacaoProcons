export type BridgeErrorCode =
  | "UNAUTHORIZED"
  | "PROJECT_NOT_FOUND"
  | "AGENT_NOT_FOUND"
  | "RUN_NOT_FOUND"
  | "AGENT_BUSY"
  | "CURSOR_API_ERROR"
  | "RUN_TIMEOUT"
  | "BLOCKED_BY_POLICY"
  | "INVALID_INPUT"
  | "NOT_CONFIGURED"
  | "INTERNAL_ERROR";

export class BridgeError extends Error {
  readonly code: BridgeErrorCode;
  readonly details: Record<string, unknown>;

  constructor(code: BridgeErrorCode, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.details = details;
  }

  toJSON(): { error: { code: BridgeErrorCode; message: string; details: Record<string, unknown> } } {
    return { error: { code: this.code, message: this.message, details: this.details } };
  }
}

/** Normalize any thrown value into a structured error payload (never a raw stack trace). */
export function toErrorPayload(err: unknown): {
  error: { code: BridgeErrorCode; message: string; details: Record<string, unknown> };
} {
  if (err instanceof BridgeError) return err.toJSON();
  const message = err instanceof Error ? err.message : String(err);
  return { error: { code: "INTERNAL_ERROR", message, details: {} } };
}
