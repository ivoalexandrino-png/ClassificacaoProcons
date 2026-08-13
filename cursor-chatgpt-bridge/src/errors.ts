export type ErrorCode =
  | "UNAUTHORIZED"
  | "PROJECT_NOT_FOUND"
  | "AGENT_NOT_FOUND"
  | "RUN_NOT_FOUND"
  | "AGENT_BUSY"
  | "CURSOR_API_ERROR"
  | "RUN_TIMEOUT"
  | "BLOCKED_BY_POLICY"
  | "INTERNAL_ERROR"
  | "VALIDATION_ERROR";

export interface BridgeErrorBody {
  error: {
    code: ErrorCode;
    message: string;
    details?: Record<string, unknown>;
  };
}

export class BridgeError extends Error {
  readonly code: ErrorCode;
  readonly details?: Record<string, unknown>;

  constructor(code: ErrorCode, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.details = details;
  }

  toJSON(): BridgeErrorBody {
    return {
      error: {
        code: this.code,
        message: this.message,
        details: this.details,
      },
    };
  }
}

export function isBridgeError(error: unknown): error is BridgeError {
  return error instanceof BridgeError;
}
