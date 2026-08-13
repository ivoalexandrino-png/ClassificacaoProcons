export type ErrorCode =
  | "UNAUTHORIZED"
  | "PROJECT_NOT_FOUND"
  | "AGENT_NOT_FOUND"
  | "RUN_NOT_FOUND"
  | "AGENT_BUSY"
  | "CURSOR_API_ERROR"
  | "RUN_TIMEOUT"
  | "BLOCKED_BY_POLICY"
  | "VALIDATION_ERROR"
  | "INTERNAL_ERROR";

export interface ErrorEnvelope {
  error: {
    code: ErrorCode;
    message: string;
    details?: Record<string, unknown>;
  };
}

export function errorBody(
  code: ErrorCode,
  message: string,
  details?: Record<string, unknown>,
): ErrorEnvelope {
  return details !== undefined
    ? { error: { code, message, details } }
    : { error: { code, message } };
}

/** Structured error carried through the bridge so handlers can map it to `errorBody`. */
export class BridgeError extends Error {
  readonly code: ErrorCode;
  readonly details?: Record<string, unknown>;

  constructor(code: ErrorCode, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.details = details;
  }

  toErrorBody(): ErrorEnvelope {
    return errorBody(this.code, this.message, this.details);
  }
}
